"""Template errors point to authoritative objects, not parsed display strings."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace

import pytest
from test_template_fields import setup
from test_template_slots import design

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Region
from inkstruct.document.template_diagnostics import TemplateDiagnostic
from inkstruct.layout.blocks import layout_markdown


def test_unbound_required_slot_has_object_target_without_fake_source():
    doc = parse_markdown(SourceSession("123"))
    snapshot = layout_markdown(
        doc, AssetResolver(builtin_numbers=True), flow=FlowStyle(template=design())
    )
    diagnostic = next(d for d in snapshot.diagnostics if d.code == "template-slot-required")
    assert isinstance(diagnostic, TemplateDiagnostic)
    assert diagnostic.span.start == diagnostic.span.end == 0
    assert diagnostic.target.slot_id == "record-number"
    assert diagnostic.target.region == "record-key"
    assert diagnostic.target.node_ids == ()
    assert diagnostic.target.anchor == "record-baseline"
    encoded = json.loads(json.dumps(asdict(diagnostic)))
    assert encoded["target"]["region"] == "record-key"
    assert len({diagnostic, diagnostic}) == 1


@pytest.mark.parametrize("kind", ["region", "anchor"])
def test_missing_continuation_object_targets_continuation(kind):
    _, doc, resolver, flow = setup(repeat=True, anchor="signature" if kind == "anchor" else None)
    face = replace(
        flow.template.continuation, **{("reserved" if kind == "region" else "anchors"): ()}
    )
    flow = replace(flow, template=replace(flow.template, continuation=face))
    snapshot = layout_markdown(doc, resolver, flow=flow)
    d = next(d for d in snapshot.diagnostics if d.code == f"template-binding-{kind}-missing")
    assert d.target.face == "continuation"
    assert d.target.region == "header"
    assert d.target.node_ids == (doc.nodes[0].node_id,)


def test_field_local_errors_include_page_and_source_target():
    _, doc, resolver, flow = setup(source="1 " * 60 + "\n\n2\n\n3", repeat=True)
    t = flow.template
    flow = replace(
        flow,
        template=replace(t, first=replace(t.first, reserved=(Region("header", 15, 95, 60, 1),))),
    )
    snapshot = layout_markdown(doc, resolver, flow=flow)
    issues = [d for d in snapshot.diagnostics if getattr(d, "target", None)]
    assert issues and not snapshot.exportable
    assert any(d.code == "template-field-height-overflow" for d in issues)
    for d in issues:
        assert d.target.region == "header"
        assert d.target.node_ids == flow.template_bindings[0].node_ids
        assert d.target.page_index is not None
        assert d.target.face == ("first" if d.target.page_index == 0 else "continuation")
    assert snapshot == layout_markdown(doc, resolver, flow=flow)


def test_field_resource_diagnostic_preserves_source_span_and_kind():
    _, doc, _, flow = setup(source="缺字\n\n1")
    result = layout_markdown(doc, AssetResolver(builtin_numbers=True), flow=flow)
    errors = [d for d in result.diagnostics if d.code == "asset-missing"]
    assert errors and all(d.target.region == "header" for d in errors)
    assert all(doc.nodes[0].span.start <= d.span.start < doc.nodes[0].span.end for d in errors)


def test_editor_repairs_required_field_and_preserves_cancel_and_stale_guard(tmp_path):
    pytest.importorskip("PySide6")
    program = r"""
import time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.template_settings import TemplateSettingsDialog
from inkstruct.editor.template_designer import TemplateDesignerDialog
from inkstruct.document.template_authoring import read_template, template_json
from inkstruct.document.template_diagnostics import TemplateTarget
app=QtWidgets.QApplication([])
w=MixedWindow(source='12\n\n34')
w.show()
def ready():
    end=time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
t=read_template(Path('configs/templates/generic-record-v2.json'))
w.flow=replace(w.flow, template=t)
w.schedule_layout(); ready()
index=next(i for i in range(w.diagnostic_picker.count()) if w.diagnostic_picker.itemData(i).code=='template-slot-required')
w.diagnostic_picker.setCurrentIndex(index)
cursor=w.editor.textCursor();cursor.setPosition(4);w.editor.setTextCursor(cursor)
w.navigate_diagnostic()
assert w.editor.textCursor().position()==4 # No fake source jump for a missing binding.
assert w.repair_template_button.isEnabled()
w.schedule_layout()
assert not w.repair_template_button.isEnabled()
ready()
index=next(i for i in range(w.diagnostic_picker.count()) if w.diagnostic_picker.itemData(i).code=='template-slot-required')
w.diagnostic_picker.setCurrentIndex(index)
assert w.repair_template_button.isEnabled()
before=w.flow
def cancel(dialog):
    assert dialog.binding_editor.region.currentData()=='record-key'
    assert not dialog.binding_editor.nodes.selectedItems()
    assert 'record-number' in dialog.diagnostic_note.text()
    return QtWidgets.QDialog.Rejected
TemplateSettingsDialog.exec=cancel
w.repair_template_button.click()
assert w.flow==before
def repair(dialog):
    dialog.binding_editor.nodes.item(0).setSelected(True)
    dialog.binding_editor.apply_binding()
    assert len(dialog.binding_configuration())==1
    # Design navigation is read-only, including undo state and exact geometry.
    designer=TemplateDesignerDialog(dialog.configuration())
    raw=designer.json_editor.toPlainText()
    assert designer.focus_target(dialog.target)
    assert designer.face.currentData()=='first'
    assert designer.element.currentData()==('reserved',0)
    assert raw==designer.json_editor.toPlainText()
    assert not designer.json_editor.document().isUndoAvailable()
    missing=TemplateTarget('absent',face='continuation')
    assert not designer.focus_target(missing)
    assert designer.face.currentData()=='continuation' and designer.error.text()
    designer.deleteLater()
    return QtWidgets.QDialog.Accepted
TemplateSettingsDialog.exec=repair
w.repair_template_diagnostic();ready()
assert w.snapshot.exportable and w.flow.template_bindings
assert all(d.code!='template-slot-required' for d in w.snapshot.diagnostics)
# A worker rebuild disables actions based on previous diagnostics.
w.schedule_layout()
assert not w.repair_template_button.isEnabled()
ready()
w.dirty=False;w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
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
