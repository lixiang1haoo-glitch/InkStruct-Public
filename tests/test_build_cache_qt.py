"""Exercise cache revision rebinding through the actual Qt worker and publish gate."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_cached_preview_revision_stale_request_and_save(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.package import load_package
app=QtWidgets.QApplication([])
w=MixedWindow(source='12.50 $12_3$');w.show()
def ready():
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
   w.recovery_timer.stop();return
  time.sleep(.01)
 raise AssertionError(w.status.text())
ready();original=w.snapshot
w.refresh_assets();ready()
assert w.build_cache.layouts.statistics()['hits']>=1
assert w.snapshot.revision==w.revision and w.snapshot.revision!=original.revision
assert w.snapshot.pages is original.pages
assert w.snapshot.job_key==original.job_key
old_key,old_revision=w.current_key,w.revision
old_snapshot=w.snapshot
w.editor.insertPlainText('2 ')
assert not w.canvas.isEnabled() and not w.export_button.isEnabled()
w.publish({'key':old_key,'revision':old_revision,'snapshot':old_snapshot})
assert not w.canvas.isEnabled() and not w.export_button.isEnabled()
ready()
assert w.snapshot.revision==w.revision and w.snapshot.pages!=original.pages
w.editor.undo();ready()
assert w.snapshot.pages==original.pages
assert w.build_cache.measurements.statistics()['hits']>0
w.refresh_assets();ready()
assert w.snapshot.revision==w.revision
hits=w.build_cache.layouts.statistics()['hits']
path=Path(sys.argv[1])/'cached.inkdoc'
w.session_path=path
assert w.save_project()
assert w.build_cache.layouts.statistics()['hits']>hits
p=load_package(path)
assert p.session.source==w.buffer.raw and p.resolver.selection_records()==w.resolver.selection_records()
w.load_project_path(path);ready()
assert w.snapshot.revision==w.revision and w.snapshot.pages==original.pages
w.dirty=False;w.close()
print('Qt cached preview, request identity and save passed')
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
