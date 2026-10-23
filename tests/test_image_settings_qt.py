"""Raster import is transactional; reference pages and plotter buttons differ."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_image_settings_and_portable_reference_preview(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from PIL import Image
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.image_settings import ImageSettingsDialog
from inkstruct.document.images import ImageStyle
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.styles import FlowStyle
from inkstruct.document.package import save_package,load_package
app=QtWidgets.QApplication([])
root=Path(sys.argv[1]);image=root/'plot.png';Image.new('RGB',(120,60),'blue').save(image)
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
flow=FlowStyle(image=ImageStyle(width_mm=43.123456789))
d=ImageSettingsDialog(parse_markdown('![12](plot.png)'),flow)
assert d.configuration()==flow
d.picker.setCurrentIndex(1)
d.import_file(image)
d.reject();d.deleteLater()
assert not flow.images
w=MixedWindow(source='1\n\n![12](plot.png)\n\n2');w.show()
def ready():
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();assert not w.snapshot.exportable
def accept(dialog):
 dialog.picker.setCurrentIndex(1)
 dialog.import_file(image)
 dialog.dimension_mode.setCurrentIndex(dialog.dimension_mode.findData('width'))
 dialog.controls['width_mm'].setValue(50)
 return QtWidgets.QDialog.Accepted
ImageSettingsDialog.exec=accept
w.image_settings();ready()
assert w.snapshot.exportable and not w.snapshot.plotter_exportable
assert w.page_export.isEnabled() and w.machine_export.isEnabled()
assert '非 SVG 参考图片' in w.status.text()
fragment=next(f for f in w.snapshot.fragments if f.status=='image-reference')
w.select_fragment(fragment)
assert w.editor.textCursor().selectedText()=='![12](plot.png)'
project=root/'image.inkdoc';save_package(project,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
assert load_package(project).flow==w.flow
before=w.flow
ImageSettingsDialog.exec=lambda dialog:QtWidgets.QDialog.Rejected
w.image_settings();assert w.flow==before
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        check=False,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
