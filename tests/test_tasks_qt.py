"""Only actual checkbox activation changes source; stale/programmatic selection does not."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_task_click_undo_and_stale_snapshot(tmp_path):
    program = r"""
import time,sys
from pathlib import Path
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.package import load_package
app=QtWidgets.QApplication([])
w=MixedWindow(source='- [X] 12\r\n- [ ] 3');w.show()
def ready():
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();original=w.source_session.source;atoms=w.source_session.atom_ids
box=next(f for f in w.snapshot.fragments if f.status=='task-checked')
identities=[(f.occurrence_id,f.asset_id) for f in w.snapshot.fragments]
w.select_fragment(box);assert w.source_session.source==original
assert not any(b.isEnabled() for b in w.rating_buttons)
QtTest.QTest.mouseClick(w.canvas,QtCore.Qt.MouseButton.LeftButton,pos=w.canvas.rect_for(box).center().toPoint())
assert w.source_session.source=='- [ ] 12\r\n- [ ] 3'
w.toggle_task(box);assert w.source_session.source=='- [ ] 12\r\n- [ ] 3'
ready();assert identities==[(f.occurrence_id,f.asset_id) for f in w.snapshot.fragments]
assert w.snapshot.exportable
w.editor.undo();ready();assert w.source_session.source==original and w.source_session.atom_ids==atoms
w.editor.redo();ready();assert w.source_session.source=='- [ ] 12\r\n- [ ] 3'
assert not any(w.glyph_list.item(i).text().startswith('\ufffc') for i in range(w.glyph_list.count()))
project=Path(sys.argv[1])/'task-click.inkdoc'
QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(project),'')
assert w.save_project()
assert load_package(project).session.source==w.source_session.source
before=w.snapshot.pages
w.load_project_path(project);ready();assert w.snapshot.pages==before
assert w.source_session.source=='- [ ] 12\r\n- [ ] 3'
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
