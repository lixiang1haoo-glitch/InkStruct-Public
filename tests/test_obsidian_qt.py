"""Actual editor dialect switch, asynchronous layout, source hit and native reopen."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_dialect_switch_source_navigation_and_save_reopen(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.package import load_package
app=QtWidgets.QApplication([])
source='> [!note]- 12\n> [[不存在的文件|34]] ![[附件|56.5]]'
w=MixedWindow(source=source);w.show()
def ready():
 end=time.monotonic()+15
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready()
assert w.flow.markdown_dialect=='markdown' and not w.snapshot.exportable
w.dialect_picker.setCurrentIndex(w.dialect_picker.findData('obsidian'));ready()
assert w.snapshot.plotter_exportable,w.snapshot.diagnostics
assert w.dirty and w.source_session.source==source
wiki=next(n for r in w.markdown_document.nodes for n in r.walk() if n.kind=='wiki_link')
o=wiki.occurrences[0]
w.select_fragment(next(f for f in w.snapshot.fragments if f.occurrence_id==o.occurrence_id));app.processEvents()
assert w.editor.textCursor().selectedText()=='3'
choices=w.resolver.selection_records()
old_snapshot=w.snapshot
path=Path(sys.argv[1])/'static.inkdoc'
QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'')
assert w.save_project() and load_package(path).flow.markdown_dialect=='obsidian'
w.dialect_picker.setCurrentIndex(w.dialect_picker.findData('markdown'));ready()
assert w.source_session.source==source and not w.snapshot.exportable
w.load_project_path(path);ready()
assert w.dialect_picker.currentData()=='obsidian'
assert w.snapshot.pages==old_snapshot.pages
assert w.resolver.selection_records()==choices
w.mode_picker.setCurrentIndex(w.mode_picker.findData('plain-text'))
assert not w.dialect_picker.isEnabled()
w.mode_picker.setCurrentIndex(w.mode_picker.findData('markdown'));ready()
assert w.dialect_picker.isEnabled() and w.snapshot.plotter_exportable
w.dirty=False;w.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        check=False,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-12000:]
