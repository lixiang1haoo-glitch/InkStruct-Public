"""Fit reports describe actual layout failures without changing the document."""

import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest
from test_template_binding_cli import command, project
from test_template_fields import setup
from test_template_slots import design

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Region
from inkstruct.document.template_fit import template_fit_report
from inkstruct.layout.blocks import layout_markdown


def test_required_optional_and_global_diagnostics_are_separate():
    t = design()
    t = replace(
        t,
        first=replace(t.first, reserved=t.first.reserved + (Region("optional", 130, 10, 20, 10),)),
    )
    doc = parse_markdown(SourceSession("缺字"))
    flow = FlowStyle(template=t)
    snapshot = layout_markdown(doc, AssetResolver(builtin_numbers=True), flow=flow)
    report = template_fit_report(doc, flow, snapshot)
    fields = {f["region"]: f for f in report["fields"]}
    required = fields["record-key"]
    assert required["required"] and required["status"] == "error"
    assert fields["optional"]["status"] == "unbound"
    assert [report["diagnostics"][i]["code"] for i in required["diagnostic_indices"]] == [
        "template-slot-required"
    ]
    assert any(d["code"] == "asset-missing" and not d.get("target") for d in report["diagnostics"])
    assert not report["exportable"] and not report["physical_alignment_verified"]
    assert not report["machine_svg_verified"]
    assert json.loads(json.dumps(report))["source_sha256"] == report["source_sha256"]


def test_repeated_overflow_targets_real_pages_and_retains_inputs():
    session, doc, resolver, flow = setup(source="1 " * 60 + "\n\n2\n\n3", repeat=True)
    t = flow.template
    flow = replace(
        flow,
        template=replace(t, first=replace(t.first, reserved=(Region("header", 15, 95, 60, 1),))),
    )
    snapshot = layout_markdown(doc, resolver, flow=flow)
    identities, choices = session.identity_record(), resolver.selections.copy()
    report = template_fit_report(doc, flow, snapshot)
    field = report["fields"][0]
    assert field["status"] == "error"
    issues = [report["diagnostics"][i] for i in field["diagnostic_indices"]]
    assert any(d["code"] == "template-field-height-overflow" for d in issues)
    assert all(d["target"]["page_index"] is not None for d in issues)
    assert report == template_fit_report(doc, flow, snapshot)
    assert session.identity_record() == identities and resolver.selections == choices


def test_valid_report_and_stale_or_absent_template_rejection():
    _, doc, resolver, flow = setup(repeat=True)
    snapshot = layout_markdown(doc, resolver, flow=flow)
    report = template_fit_report(doc, flow, snapshot)
    assert report["exportable"] and report["plotter_exportable"]
    assert report["fields"][0]["status"] == "no-local-error"
    for stale in (replace(doc, revision=doc.revision + 1), replace(doc, document_id="other")):
        with pytest.raises(ValueError, match="过期"):
            template_fit_report(stale, flow, snapshot)
    with pytest.raises(ValueError, match="模板"):
        template_fit_report(doc, FlowStyle(), snapshot)


def test_agent_report_uses_identical_shared_model(tmp_path, capsys):
    path = project(tmp_path)
    before = path.read_bytes()
    code, result = command(capsys, "validate-document", path)
    loaded = load_package(path)
    doc = parse_markdown(loaded.session, dialect=loaded.flow.markdown_dialect)
    snapshot = layout_markdown(
        doc, loaded.resolver, page=loaded.page, style=loaded.style, flow=loaded.flow
    )
    expected = template_fit_report(doc, loaded.flow, snapshot)
    assert code == 0 and result["fit_report"] == json.loads(json.dumps(expected))
    assert path.read_bytes() == before


def test_gui_report_save_navigation_cancel_and_stale_guard(tmp_path):
    pytest.importorskip("PySide6")
    program = r"""
import json,time,sys
from dataclasses import replace
from pathlib import Path
from PySide6 import QtCore,QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.template_fit import TemplateFitDialog
from inkstruct.editor.template_settings import TemplateSettingsDialog
from inkstruct.document.template_authoring import read_template
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(Path(sys.argv[1])/'settings'))
w=MixedWindow(source='12\n\n34');w.show()
def ready():
    end=time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
assert not w.template_fit_button.isEnabled()
w.flow=replace(w.flow,template=read_template(Path('configs/templates/generic-record-v2.json')))
w.schedule_layout();assert not w.template_fit_button.isEnabled();ready()
assert w.template_fit_button.isEnabled() and not w.snapshot.exportable
original=w.flow
path=Path(sys.argv[1])/'report.json'
def inspect(d):
    assert not d.report['exportable'] and d.fields.rowCount()>0
    assert not d.locate.isEnabled()
    QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'')
    d.save_report()
    saved=path.read_bytes()
    assert json.loads(saved)==json.loads(json.dumps(d.report))
    d.report['pages']=999
    d.save_report();assert path.read_bytes()==saved # Existing output protected.
    return QtWidgets.QDialog.Rejected
TemplateFitDialog.exec=inspect
w.template_fit_button.click();assert w.flow==original

def select(d):
    i=next(i for i,x in enumerate(d.diagnostics) if x.code=='template-slot-required')
    d.issues.setCurrentItem(d.issues.topLevelItem(i))
    assert d.locate.isEnabled()
    d.locate_issue()
    return QtWidgets.QDialog.Accepted
TemplateFitDialog.exec=select
calls=[]
def repair(d):
    calls.append(d.target.region)
    assert d.binding_editor.region.currentData()=='record-key'
    d.binding_editor.nodes.item(0).setSelected(True);d.binding_editor.apply_binding()
    return QtWidgets.QDialog.Accepted
TemplateSettingsDialog.exec=repair
w.template_fit_report();ready()
assert calls==['record-key'] and w.snapshot.exportable
# A report may stay open while a programmatic project change arrives: no stale navigation.
def stale(d):
    d.selected_diagnostic=next(x for x in d.diagnostics)
    w.schedule_layout()
    return QtWidgets.QDialog.Accepted
TemplateFitDialog.exec=stale
w.template_fit_report();assert calls==['record-key'];ready()
w.mode_picker.setCurrentIndex(0 if w.mode_picker.currentIndex()!=0 else 1)
assert not w.template_fit_button.isEnabled()
w.dirty=False;w.close();w.pool.waitForDone(10000)
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
