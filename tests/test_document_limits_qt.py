"""Over-budget work keeps source/save/recovery and never enables stale exports."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_over_budget_draft_save_recovery_and_next_request(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtWidgets,QtTest,QtCore
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document import limits
from inkstruct.document.package import load_package
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
w=MixedWindow(source='12.50');w.show()
errors=[];w.message_error=lambda e:errors.append(str(e))
def settled(valid):
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if not w.timer.isActive() and not w.worker and bool(w.canvas.isEnabled())==valid:
   w.recovery_timer.stop();return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
settled(True)
original=limits.DEFAULT_LIMITS
limits.DEFAULT_LIMITS=replace(original,points=1)
w.editor.insertPlainText('1');settled(False)
assert '超限' in w.status.text()
assert not w.export_button.isEnabled()
source=w.source_session.source
identity=w.source_session.identity_record()
path=root/'over-limit.inkdoc'
w.session_path=path
assert w.save_project(),errors
assert '草稿' in w.status.text()
saved=load_package(path)
assert saved.session.source==source and saved.session.identity_record()==identity
w.recovery_path=root/'recovery.inkdoc';w.recovery_hash=None;w.mark_dirty()
w.write_recovery()
assert load_package(w.recovery_path).session.source==source
assert not w.export_button.isEnabled()
# Settings that need a new AST report limits instead of raising inside a Qt slot.
limits.DEFAULT_LIMITS=replace(original,nodes=1)
w.template_settings();w.image_settings()
assert len(errors)==2 and all('超限' in e for e in errors)
limits.DEFAULT_LIMITS=original
w.load_project_path(path);settled(True)
assert w.snapshot.exportable and w.source_session.source==source
assert w.export_button.isEnabled()
w.dirty=False;w.close()
print('Qt limits preserve draft/source/recovery and reject stale exports')
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
