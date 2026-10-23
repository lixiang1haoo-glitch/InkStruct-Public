"""Prefix/suffix resume goes through the worker, revision gate and project save."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
@pytest.mark.parametrize("position", ["middle", "tail"])
@pytest.mark.parametrize("notes", [False, True])
def test_edit_publishes_current_snapshot_and_saves_exact_project(tmp_path, position, notes):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtWidgets, QtGui, QtTest, QtCore
from inkstruct.editor.mixed import MixedWindow, build_markdown
from inkstruct.document.package import load_package
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(Path(sys.argv[1])/'settings'))
source="\n\n".join(["12.34 56.78"] * 80)
notes=sys.argv[3]=='True'
if notes:
 source=source.replace('56.78','56.78[^a]',1)
body_end=len(source)
if notes:
 source+='\n\n[^a]: '+'12 34 '*80
w=MixedWindow(source=source);w.show()
def ready():
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
   w.recovery_timer.stop();return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();before=w.snapshot
cursor=w.editor.textCursor()
if sys.argv[2]=='middle':
 cursor.setPosition(source.index('12.34',body_end//2))
 cursor.movePosition(QtGui.QTextCursor.NextCharacter, QtGui.QTextCursor.KeepAnchor)
else:
 cursor.setPosition(body_end)
 cursor.movePosition(QtGui.QTextCursor.PreviousCharacter, QtGui.QTextCursor.KeepAnchor)
cursor.insertText('9');w.editor.setTextCursor(cursor)
assert not w.canvas.isEnabled() and not w.machine_export.isEnabled()
ready()
assert w.snapshot.revision == w.revision
stats=w.build_cache.continuation.statistics()
assert stats['reused_blocks']==79 and stats['reused_pages']>0
assert w.snapshot.pages[0] == before.pages[0]
if not notes:
 assert w.snapshot.pages[0] is before.pages[0]
if sys.argv[2]=='middle':
 assert stats['reused_suffix_blocks']==39
 assert w.snapshot.pages[-1] == before.pages[-1]
 if not notes:
  assert w.snapshot.pages[-1] is before.pages[-1]
path=Path(sys.argv[1])/'resumed.inkdoc'
w.session_path=path
assert w.save_project()
p=load_package(path)
expected=build_markdown(p.session,w.revision,p.resolver,'','',p.page,p.style,p.flow,None)
assert expected['snapshot']==w.snapshot
assert p.session.source==w.buffer.raw
w.load_project_path(path);ready()
assert w.snapshot.pages==expected['snapshot'].pages
w.dirty=False;w.close()
print('Qt continuation, revision gate, save and reload passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path), position, str(notes)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
