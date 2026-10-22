"""Explicit SVG import, transactional settings, source selection and machine capability."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_svg_settings_import_and_source_selection(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.image_settings import ImageSettingsDialog
from inkstruct.document.package import load_package,save_package
app=QtWidgets.QApplication([])
root=Path(sys.argv[1]); image=root/'plot.svg'
image.write_text('<svg width="100mm" height="60mm" viewBox="0 0 100 60" fill="none" stroke="black"><path d="M10 10 Q50 50 90 10"/></svg>')
w=MixedWindow(source='1\n\n![12](plot.svg)\n\n2');w.show()
def ready():
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();assert not w.snapshot.exportable
before=w.flow
def cancel(dialog):
 dialog.picker.setCurrentIndex(1)
 dialog.import_file(image)
 dialog.controls['svg_tolerance_mm'].setValue(.0123)
 return QtWidgets.QDialog.Rejected
ImageSettingsDialog.exec=cancel
w.image_settings();assert w.flow==before
def accept(dialog):
 dialog.picker.setCurrentIndex(1)
 dialog.import_file(image)
 dialog.controls['width_mm'].setValue(50)
 dialog.controls['svg_tolerance_mm'].setValue(.0123)
 assert '单线 SVG' in dialog.info.text()
 return QtWidgets.QDialog.Accepted
ImageSettingsDialog.exec=accept
w.image_settings();ready()
assert w.snapshot.plotter_exportable and w.machine_export.isEnabled()
f=next(f for f in w.snapshot.fragments if f.status=='image-vector')
w.select_fragment(f)
assert w.editor.textCursor().selectedText()=='![12](plot.svg)'
assert '单线 SVG' in w.selection_label.text() and f.asset_id is None
assert w.flow.image_for(f.node_id).svg_tolerance_mm==.0123
p=root/'vector.inkdoc';save_package(p,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
assert load_package(p).flow==w.flow
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
