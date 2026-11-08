"""Page/source selection, repeated markers, editing and native reopening in Qt."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_footnote_source_selection_edit_undo_and_reopen(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.schema import PageProfile
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(Path(sys.argv[1])/'settings'))
w=MixedWindow(source='1[^a]\r\n\r\n[^a]: '+'12 34 '*80)
w.page=PageProfile(70,65,5)
w.show();w.schedule_layout()
def ready():
 end=time.monotonic()+15
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();assert w.snapshot.plotter_exportable,w.snapshot.diagnostics
before=w.source_session.source;atoms=w.source_session.atom_ids
label=next(f for f in w.snapshot.fragments if f.repeated and f.container_id.startswith('footnote:'))
w.select_fragment(label)
assert w.editor.textCursor().selectedText()=='[^a]:'
assert w.source_session.source==before
reference=next(f for f in w.snapshot.fragments if before[f.span.start:f.span.end]=='[^a]')
w.select_fragment(reference)
assert w.editor.textCursor().selectedText()=='[^a]'
# Ordinary source editing changes only note content; derived numbering is never
# written into Markdown. Undo restores atom identity and page geometry.
pages=w.snapshot.pages
at=before.index('12 34')
w.source_session.apply(at,at+2,'56');w._display_session();w.schedule_layout();ready()
assert w.snapshot.plotter_exportable
assert w.source_session.source[at:at+2]=='56'
w.editor.undo();ready()
assert w.source_session.source==before and w.source_session.atom_ids==atoms
assert w.snapshot.pages==pages
path=Path(sys.argv[1])/'footnotes.inkdoc'
QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'')
assert w.save_project()
w.load_project_path(path);ready()
assert w.snapshot.pages==pages and w.snapshot.plotter_exportable
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
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
