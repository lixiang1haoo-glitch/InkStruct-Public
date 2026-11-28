"""One semantic field design can bind different documents without copying content."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from test_template_binding_cli import command, project

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import PageTemplate
from inkstruct.document.template_authoring import parse_template, read_template, template_json
from inkstruct.document.template_binding_cli import SLOT_REQUEST_VERSION, read_bindings
from inkstruct.document.template_slots import (
    SlottedPageTemplate,
    TemplateSlot,
    geometry_only,
    slot_diagnostics,
    upgrade_template,
)
from inkstruct.layout.blocks import layout_markdown


def design():
    return replace(
        upgrade_template(read_template(Path("configs/templates/generic-record-v1.json"))),
        slots=(
            TemplateSlot(
                "record-number", "记录编号", "record-key", "text", True, anchor="record-baseline"
            ),
        ),
    )


def test_explicit_upgrade_retains_v1_roundtrip_and_all_geometry():
    path = Path("configs/templates/generic-record-v1.json")
    raw = path.read_bytes()
    old = read_template(path)
    new = upgrade_template(old)
    assert type(old) is PageTemplate and "slots" not in asdict(old)
    assert new.schema_version == SlottedPageTemplate.SCHEMA
    assert geometry_only(new) == old and upgrade_template(new) is new
    assert parse_template(template_json(new)) == new
    assert parse_template(template_json(old)) == old and path.read_bytes() == raw
    with pytest.raises(ValueError):
        PageTemplate(**{**asdict(old), "schema_version": SlottedPageTemplate.SCHEMA})
    with pytest.raises(TypeError):
        parse_template(json.dumps({**asdict(old), "slots": []}))
    with pytest.raises(ValueError):
        parse_template(json.dumps({**asdict(old), "schema_version": "future"}))


@pytest.mark.parametrize(
    "change",
    [
        {"slot_id": ""},
        {"label": ""},
        {"kind": "guess"},
        {"required": 1},
        {"region": "absent"},
        {"anchor": "absent"},
        {"pages": "all"},
        {"scale": float("nan")},
    ],
)
def test_invalid_slot_declarations_are_rejected(change):
    template = design()
    with pytest.raises((ValueError, TypeError)):
        replace(template, slots=(replace(template.slots[0], **change),))


def test_duplicates_required_type_and_policy_errors_block_export():
    template = design()
    with pytest.raises(ValueError):
        replace(template, slots=template.slots * 2)
    doc = parse_markdown(SourceSession("12\n\n34"))
    r = AssetResolver(builtin_numbers=True)
    missing = layout_markdown(doc, r, flow=FlowStyle(template=template))
    assert not missing.exportable
    assert "template-slot-required" in {d.code for d in missing.diagnostics}
    binding = template.slots[0].bind((doc.nodes[0].node_id,))
    wrong = replace(binding, scale=0.5)
    result = layout_markdown(doc, r, flow=FlowStyle(template=template, template_bindings=(wrong,)))
    assert not result.exportable and "template-slot-policy" in {d.code for d in result.diagnostics}
    good = layout_markdown(doc, r, flow=FlowStyle(template=template, template_bindings=(binding,)))
    assert good.exportable, good.diagnostics
    legacy = layout_markdown(
        doc, r, flow=FlowStyle(template=geometry_only(template), template_bindings=(binding,))
    )
    assert good.pages == legacy.pages
    # A relabel is cosmetic and does not require changing any document binding.
    renamed = replace(template, slots=(replace(template.slots[0], label="单号"),))
    assert not slot_diagnostics(doc, renamed, (binding,))


@pytest.mark.parametrize(
    "kind,source",
    [
        ("text", "# 123"),
        ("math", "$$\n12\n$$"),
        ("table", "|1|2|\n|-|-|\n|3|4|"),
        ("table", "<table><tr><td>1</td></tr></table>"),
    ],
)
def test_slot_kind_checks_complete_top_level_blocks(kind, source):
    template = design()
    template = replace(template, slots=(replace(template.slots[0], kind=kind),))
    doc = parse_markdown(SourceSession(source))
    binding = template.slots[0].bind((doc.nodes[0].node_id,))
    assert not slot_diagnostics(doc, template, (binding,))
    bad_kind = "text" if kind != "text" else "math"
    wrong = replace(template, slots=(replace(template.slots[0], kind=bad_kind),))
    assert slot_diagnostics(doc, wrong, (binding,))[0].code == "template-slot-kind"


def test_same_design_reused_across_distinct_native_documents(tmp_path, capsys):
    template = design()
    template_path = tmp_path / "design.json"
    template_path.write_text(template_json(template),encoding='utf-8')
    code, inspected = command(capsys, "inspect-slots", template_path)
    assert code == 0 and inspected["slots"][0]["slot_id"] == "record-number"
    ids = []
    for name, source in (("one", "12\n\n34"), ("two", "56\n\n78")):
        folder = tmp_path / name
        folder.mkdir()
        path = project(folder, source=source)
        before = path.read_bytes()
        code, report = command(capsys, "inspect-content", path, "--template", template_path)
        assert code == 0
        ids.append(report["nodes"][0]["node_id"])
        request = report["slot_request"]
        request["slots"] = [{"slot_id": "record-number", "node_ids": [ids[-1]]}]
        request_path = folder / "request.json"
        request_path.write_text(json.dumps(request))
        output = folder / "bound.inkdoc"
        code, result = command(
            capsys,
            "bind",
            path,
            "--template",
            template_path,
            "--bindings",
            request_path,
            "--output",
            output,
        )
        assert code == 0 and result["saved"], result
        loaded = load_package(output)
        assert loaded.flow.template == template and loaded.session.source == source
        assert path.read_bytes() == before
        _, inspection = command(capsys, "inspect-content", output)
        assert inspection["slot_request"]["slots"] == request["slots"]
        code, valid = command(capsys, "validate-document", output)
        assert code == 0 and valid["exportable"]
        # Required slots cannot be bypassed by replacing all bindings with [].
        remove = inspection["binding_request"]
        remove["bindings"] = []
        request_path.write_text(json.dumps(remove))
        absent = folder / "absent.inkdoc"
        code, invalid = command(
            capsys, "bind", output, "--bindings", request_path, "--output", absent
        )
        assert code == 2 and not absent.exists()
        assert "template-slot-required" in {d["code"] for d in invalid["diagnostics"]}
    assert ids[0] != ids[1]
    assert "node_ids" not in template_path.read_text(encoding='utf-8')


def test_field_dialog_cancel_precision_and_binding_controls(tmp_path):
    pytest.importorskip("PySide6")
    program = r"""
from dataclasses import replace
from PySide6 import QtWidgets
from inkstruct.document.template_authoring import read_template
from inkstruct.document.template_slots import upgrade_template, TemplateSlot
from inkstruct.editor.template_slots import TemplateSlotsDialog
from inkstruct.editor.template_designer import TemplateDesignerDialog
from inkstruct.editor.template_bindings import TemplateBindingsWidget
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from pathlib import Path
app = QtWidgets.QApplication([])
original = read_template(Path('configs/templates/generic-record-v1.json'))
dialog = TemplateSlotsDialog(original)
dialog.slot_id.setText('record-id'); dialog.label.setText('记录编号')
dialog.required.setChecked(True)
assert dialog.pending and not dialog.items.isEnabled()
assert dialog.apply_slot()
template = dialog.configuration()
assert len(template.slots) == 1 and not hasattr(original, 'slots')
dialog.reject()
assert dialog.result() == QtWidgets.QDialog.Rejected
precise = replace(template, slots=(replace(template.slots[0], scale=.71234567890123),))
dialog = TemplateSlotsDialog(precise)
dialog.items.setCurrentRow(0)
dialog.label.setText('编号')
dialog.accept()
assert dialog.configuration().slots[0].scale == precise.slots[0].scale
designer = TemplateDesignerDialog(original)
designer.set_design(dialog.configuration())
assert designer.configuration().slots[0].label == '编号'
designer.json_editor.undo()
assert designer.configuration() == original
designer.json_editor.redo()
assert designer.configuration().slots[0].label == '编号'
doc = parse_markdown(SourceSession('123'))
widget = TemplateBindingsWidget(doc, ())
widget.set_template(precise)
widget.nodes.item(0).setSelected(True)
assert not widget.scale.isEnabled() and not widget.policy.isEnabled()
widget.apply_binding()
assert widget.bindings[0] == precise.slots[0].bind((doc.nodes[0].node_id,))
widget.set_template(original)
assert widget.scale.isEnabled() and widget.policy.isEnabled()
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("damage", ["unknown", "duplicate", "stale", "extra", "bypass"])
def test_slot_requests_reject_ambiguous_or_stale_mapping(tmp_path, damage):
    value = {
        "schema_version": SLOT_REQUEST_VERSION,
        "project_sha256": "current",
        "slots": [{"slot_id": "record-number", "node_ids": ["node"]}],
        "bindings": [],
    }
    if damage == "unknown":
        value["slots"][0]["slot_id"] = "unknown"
    elif damage == "duplicate":
        value["slots"] *= 2
    elif damage == "stale":
        value["project_sha256"] = "old"
    elif damage == "extra":
        value["slots"][0]["scale"] = 0.5
    else:
        value["bindings"] = [{"region": "record-key", "node_ids": ["node-2"]}]
    path = tmp_path / "request.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        read_bindings(path, "current", design())


def test_slot_validation_preserves_field_bindings_and_repeated_pages():
    base = design()
    template = replace(base, continuation=base.first, slots=(replace(base.slots[0], pages="all"),))
    doc = parse_markdown(SourceSession("12\n\n" + "34\n\n" * 50 + "56"))
    binding = template.slots[0].bind((doc.nodes[0].node_id,))
    r = AssetResolver(builtin_numbers=True)
    flow = FlowStyle(template=template, template_bindings=(binding,))
    snapshot = layout_markdown(doc, r, flow=flow)
    assert snapshot.exportable and len(snapshot.pages) > 1, snapshot.diagnostics
    legacy = layout_markdown(doc, r, flow=replace(flow, template=geometry_only(template)))
    assert snapshot.pages == legacy.pages
    assert any(f.repeated for f in snapshot.fragments)
