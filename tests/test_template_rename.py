"""Explicit reference migration preserves geometry, source identity and ordering."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from test_template_fields import setup

from inkstruct.cli import main
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import StyleProfile
from inkstruct.document.template import Region, TemplateBinding
from inkstruct.document.template_authoring import read_template, template_json
from inkstruct.document.template_rename import rename_reference
from inkstruct.document.template_slots import TemplateSlot, upgrade_template
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page
from inkstruct.plotter.svg import page_svg


def fixture(slotted=True):
    session, doc, resolver, flow = setup(repeat=True, anchor="signature", scale=0.65)
    template = replace(flow.template, calibration="user-measured", offset_x_mm=0.123456789)
    if slotted:
        template = replace(
            upgrade_template(template),
            slots=(
                TemplateSlot("record", "记录", "header", "text", True, "all", 0.65, "signature"),
            ),
        )
    return session, doc, resolver, replace(flow, template=template)


@pytest.mark.parametrize("slotted", [False, True])
@pytest.mark.parametrize(
    "kind,old,new", [("region", "header", "测量区"), ("anchor", "signature", "基线")]
)
def test_migration_updates_both_faces_and_refs_without_changing_layout(slotted, kind, old, new):
    session, doc, r, flow = fixture(slotted)
    before = layout_markdown(doc, r, flow=flow)
    identities = session.identity_record()
    choices = dict(r.selections)
    template, bindings = rename_reference(flow.template, flow.template_bindings, kind, old, new)
    after = layout_markdown(
        doc, r, flow=replace(flow, template=template, template_bindings=bindings)
    )
    assert before.exportable and after.exportable, after.diagnostics
    collection, reference = ("reserved", "region") if kind == "region" else ("anchors", "anchor")
    for face in ("first", "continuation"):
        assert any(e.name == new for e in getattr(getattr(template, face), collection))
    assert getattr(bindings[0], reference) == new
    assert bindings[0].node_ids == flow.template_bindings[0].node_ids
    assert (
        template.calibration == "user-measured"
        and template.offset_x_mm == flow.template.offset_x_mm
    )
    if slotted:
        assert template.slots[0].slot_id == "record" and template.slots[0].label == "记录"
        assert getattr(template.slots[0], reference) == new
    for a, b in zip(plan_from_snapshot(before).pages, plan_from_snapshot(after).pages, strict=True):
        assert page_svg(route_page(a, optimize=True).page) == page_svg(
            route_page(b, optimize=True).page
        )
    assert session.identity_record() == identities and r.selections == choices
    assert rename_reference(template, bindings, kind, new, new) == (template, bindings)


@pytest.mark.parametrize(
    "kind,old,new",
    [
        ("region", "header", "body"),
        ("region", "header", "occupied"),
        ("region", "absent", "new"),
        ("region", "header", " "),
        ("anchor", "signature", "x" * 257),
    ],
)
def test_invalid_rename_is_atomic(kind, old, new):
    _, _, _, flow = fixture()
    t = flow.template
    t = replace(
        t, first=replace(t.first, reserved=(*t.first.reserved, Region("occupied", 80, 10, 5, 5)))
    )
    before = template_json(t)
    bindings = flow.template_bindings
    with pytest.raises(ValueError):
        rename_reference(t, bindings, kind, old, new)
    assert template_json(t) == before and bindings == flow.template_bindings


def test_dangling_binding_is_not_adopted_and_binding_order_is_preserved():
    _, doc, _, flow = fixture()
    dangling = TemplateBinding("new", (doc.nodes[1].node_id,))
    with pytest.raises(ValueError):
        rename_reference(flow.template, (dangling,), "region", "header", "new")
    second = TemplateBinding("other", (doc.nodes[1].node_id,))
    _, bindings = rename_reference(
        flow.template, (second, *flow.template_bindings), "region", "header", "renamed"
    )
    assert bindings[0] is second and bindings[1].node_ids == flow.template_bindings[0].node_ids
    dangling = TemplateBinding("other", (doc.nodes[1].node_id,), anchor="new")
    with pytest.raises(ValueError):
        rename_reference(flow.template, (dangling,), "anchor", "signature", "new")


def test_agent_template_and_native_project_rename_with_hash_and_no_overwrite(tmp_path, capsys):
    source = tmp_path / "template.json"
    source.write_text(
        template_json(read_template(Path("configs/templates/generic-record-v2.json"))),encoding='utf-8'
    )
    before = source.read_bytes()
    output = tmp_path / "renamed.json"
    args = [
        "document",
        "template",
        "rename",
        str(source),
        "--kind",
        "region",
        "--from-name",
        "record-key",
        "--to-name",
        "new-record",
        "--output",
        str(output),
    ]
    assert main([*args, "--expect-sha256", "stale"]) == 2 and not output.exists()
    capsys.readouterr()
    assert main([*args, "--expect-sha256", sha256(before).hexdigest()]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["saved"] and not report["content_fit_checked"]
    assert read_template(output).slots[0].region == "new-record"
    assert main(args) == 2 and source.read_bytes() == before
    capsys.readouterr()
    session, doc, r, flow = fixture()
    layout_markdown(doc, r, flow=flow)
    original = tmp_path / "project.inkdoc"
    save_package(original, session, r, flow.template.page, StyleProfile(), flow=flow, optimize=True)
    output = tmp_path / "project-renamed.inkdoc"
    before = original.read_bytes()
    args = [
        "document",
        "template",
        "rename",
        str(original),
        "--kind",
        "anchor",
        "--from-name",
        "signature",
        "--to-name",
        "new-baseline",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert (
        report["content_fit_checked"] and report["bindings_changed"] == 1 and report["exportable"]
    )
    loaded = load_package(output)
    assert loaded.session.identity_record() == session.identity_record()
    assert loaded.resolver.selections == r.selections and loaded.resolver.pools == r.pools
    assert loaded.optimize and loaded.flow.template_bindings[0].anchor == "new-baseline"
    assert original.read_bytes() == before


def test_native_rename_does_not_save_unresolved_content_errors(tmp_path, capsys):
    session, _, r, flow = fixture()
    session.apply(0, 3, "缺字")
    source = tmp_path / "bad.inkdoc"
    save_package(source, session, r, flow.template.page, StyleProfile(), flow=flow)
    output = tmp_path / "renamed.inkdoc"
    assert (
        main(
            [
                "document",
                "template",
                "rename",
                str(source),
                "--kind",
                "region",
                "--from-name",
                "header",
                "--to-name",
                "new",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    report = json.loads(capsys.readouterr().out)
    assert report["content_fit_checked"] and not report["saved"] and not output.exists()


def test_nested_dialog_accept_cancel_and_project_binding_roundtrip():
    pytest.importorskip("PySide6")
    program = r"""
import time
from pathlib import Path
from dataclasses import asdict,replace
import json
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.template_settings import TemplateSettingsDialog
from inkstruct.editor.template_rename import TemplateRenameDialog
from inkstruct.document.template_authoring import read_template,parse_template
app=QtWidgets.QApplication([])
w=MixedWindow(source='12\n\n34');w.show()
def ready():
    end=time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
t=read_template(Path('configs/templates/generic-record-v2.json'))
# Older templates allow long identifiers. Merely opening/accepting must not truncate them.
record=asdict(t);old_name='R'*300
record['first']['reserved'][0]['name']=old_name
record['slots'][0]['region']=old_name
legacy=parse_template(json.dumps(record))
probe=TemplateRenameDialog(legacy)
assert probe.old_name.currentText()==old_name and probe.new_name.text()==old_name
probe.accept();assert probe.configuration()[0] is legacy
probe.deleteLater()
b=t.slots[0].bind((w.markdown_document.nodes[0].node_id,))
w.flow=replace(w.flow,template=t,template_bindings=(b,));w.schedule_layout();ready()
before=w.flow;identity=w.source_session.identity_record();choices=dict(w.resolver.selections)
def rename(dialog):
    assert dialog.old_name.currentText()=='record-key'
    dialog.new_name.setText('body');dialog.accept()
    assert dialog.result()!=QtWidgets.QDialog.Accepted and dialog.error.text()
    dialog.new_name.setText('new-record');dialog.accept()
    return dialog.result()
TemplateRenameDialog.exec=rename
def outer(dialog):
    dialog.rename_button.click()
    assert dialog.configuration().slots[0].region=='new-record'
    assert dialog.binding_configuration()[0].region=='new-record'
    return QtWidgets.QDialog.Rejected
TemplateSettingsDialog.exec=outer
w.template_settings();assert w.flow==before
# Cancelling the inner dialog also preserves the outer draft.
TemplateRenameDialog.exec=lambda d:QtWidgets.QDialog.Rejected
d=TemplateSettingsDialog(t,document=w.markdown_document,bindings=(b,));d.rename_reference()
assert d.configuration()==t and d.binding_configuration()==(b,)
d.deleteLater()
TemplateRenameDialog.exec=rename
def accept(dialog):
    dialog.rename_reference()
    return QtWidgets.QDialog.Accepted
TemplateSettingsDialog.exec=accept
w.template_settings();ready()
assert w.snapshot.exportable
assert w.flow.template_bindings[0].region=='new-record'
assert w.source_session.identity_record()==identity and w.resolver.selections==choices
assert w.flow.template.slots[0].slot_id=='record-number'
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
