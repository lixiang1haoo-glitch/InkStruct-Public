"""Actual dialog transactions, source/selection stability and portable reopening."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_footnote_settings_transaction_reset_precision_and_project(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.footnote_settings import FootnoteSettingsDialog
from inkstruct.document.footnote_style import FootnoteStyle
from inkstruct.document.package import load_package
app=QtWidgets.QApplication([])
precise=FootnoteStyle(text_scale=.700000001,body_gap_mm=2.123456789)
d=FootnoteSettingsDialog(precise);d.show();app.processEvents()
assert d.configuration()==precise
d.controls['text_scale'].setValue(90)
assert d.configuration().text_scale==.9
QtTest.QTest.mouseClick(d.findChild(QtWidgets.QPushButton,'reset_footnote_settings'),QtCore.Qt.LeftButton)
assert d.configuration()==FootnoteStyle()
d.reject();assert d.original==precise
d.deleteLater()
w=MixedWindow(source='1[^a]\n\n[^a]: 12 34 56 78')
w.show()
def ready():
 end=time.monotonic()+15
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();assert w.snapshot.plotter_exportable,w.snapshot.diagnostics
w.dirty=False
source=w.source_session.source;atoms=w.source_session.atom_ids
flow=w.flow;pages=w.snapshot.pages;choices=w.resolver.selection_records()
def cancel(dialog):
 dialog.controls['text_scale'].setValue(95)
 return QtWidgets.QDialog.Rejected
FootnoteSettingsDialog.exec=cancel
w.footnote_settings();app.processEvents()
assert w.flow==flow and w.snapshot.pages==pages and not w.dirty
FootnoteSettingsDialog.exec=lambda d:QtWidgets.QDialog.Accepted
w.footnote_settings();app.processEvents()
assert not w.dirty
def accept(dialog):
 dialog.controls['text_scale'].setValue(90)
 dialog.controls['reference_scale'].setValue(80)
 dialog.controls['body_gap_mm'].setValue(5)
 dialog.controls['separator_length_mm'].setValue(24)
 return QtWidgets.QDialog.Accepted
FootnoteSettingsDialog.exec=accept
QtTest.QTest.mouseClick(w.footnote_settings_button,QtCore.Qt.LeftButton)
ready()
assert w.flow.footnote.text_scale==.9 and w.flow.footnote.reference_scale==.8
assert w.flow.table==flow.table and w.flow.math==flow.math and w.flow.code==flow.code
assert w.dirty and w.snapshot.pages!=pages and w.snapshot.plotter_exportable
assert w.source_session.source==source and w.source_session.atom_ids==atoms
assert w.resolver.selection_records()==choices
path=Path(sys.argv[1])/'footnote-settings.inkdoc'
QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'')
assert w.save_project();after=w.snapshot.pages;config=w.flow.footnote
assert load_package(path).flow.footnote==config
w.load_project_path(path);ready()
assert w.snapshot.pages==after and w.flow.footnote==config
w.mode_picker.setCurrentIndex(w.mode_picker.findData('plain-text'))
assert not w.footnote_settings_button.isEnabled()
w.dirty=False;w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
