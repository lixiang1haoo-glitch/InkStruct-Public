"""Automatic recovery must not block input or overwrite another editing session."""
import os
import subprocess
import sys


def test_recovery_worker_input_latest_revision_and_stale_result(tmp_path):
    program = r'''
import sys,time,threading
from pathlib import Path
from PySide6 import QtCore,QtWidgets,QtTest
from inkstruct.editor import mixed
from inkstruct.document.package import load_package
from inkstruct.editor.review import file_hash
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
mixed.recovery_directory=lambda:root
w=mixed.MixedWindow(source='12.50 $12_3$');w.show()
def wait(predicate):
    end=time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return
        QtTest.QTest.qWait(5)
    raise AssertionError(w.status.text())
wait(lambda:w.snapshot and not w.worker and not w.timer.isActive())
w.mark_dirty();w.recovery_timer.stop()
before=w.source_session.source
started,release=threading.Event(),threading.Event()
real=mixed.save_package
threads=[]
def slow(path,**kwargs):
    threads.append(threading.get_ident());started.set()
    assert release.wait(8)
    return real(path,**kwargs)
mixed.save_package=slow
w.start_recovery();wait(started.is_set)
assert threads[0]!=threading.get_ident()
ticks=[];heartbeat=QtCore.QTimer();heartbeat.setInterval(2)
heartbeat.timeout.connect(lambda:ticks.append(1));heartbeat.start()
w.editor.insertPlainText('9')
assert w.source_session.source!=before
w.start_recovery();assert w.recovery_pending
QtTest.QTest.qWait(50);app.processEvents()
assert len(ticks)>3 and w.recovery_worker is not None
release.set();wait(lambda:w.recovery_worker is None)
w.recovery_timer.stop()
path=w.recovery_path
assert load_package(path).session.source==before
assert w.recovery_hash==file_hash(path) and w.dirty
w.start_recovery();wait(lambda:w.recovery_worker is None);w.recovery_timer.stop()
assert load_package(path).session.source==w.source_session.source
formal=root/'formal.inkdoc';formal.write_bytes(path.read_bytes());formal_bytes=formal.read_bytes()
# External edits retain their bytes and generate a visible error.
path.write_bytes(b'external draft')
w.start_recovery();wait(lambda:w.recovery_worker is None);w.recovery_timer.stop()
assert path.read_bytes()==b'external draft'
assert '自动恢复副本未保存' in w.status.text()
# A pending old job may finish its own recovery, but cannot claim the new
# project's path, expected hash, selections or dirty status.
w.recovery_path=root/'old-job.inkdoc';w.recovery_hash=None
started.clear();release.clear();w.start_recovery();wait(started.is_set)
w.load_project_path(formal)
epoch=w.recovery_epoch
assert w.recovery_path is None and w.recovery_hash is None
release.set();wait(lambda:w.recovery_worker is None)
assert w.recovery_epoch==epoch and w.recovery_path is None and w.recovery_hash is None
assert formal.read_bytes()==formal_bytes and not w.dirty
heartbeat.stop();w.dirty=False;w.close()
print('background recovery, responsive input, latest revision and stale ownership passed')
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=35, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
