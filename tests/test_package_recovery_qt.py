"""Failed imports are transactional and independent editor drafts never share a recovery file."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_failed_load_and_recovery_sessions_preserve_user_state(tmp_path):
    program = r"""
import os, sys, time
from pathlib import Path
from PySide6 import QtWidgets, QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.package import load_package
from test_package_resilience import fixture, archive

root = Path(sys.argv[1]); os.chdir(root)
app = QtWidgets.QApplication([])
w = MixedWindow(source='12.50 $12_3$')
errors=[]
w.message_error=lambda e: errors.append(str(e))
w.show()
def ready():
    end=time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            w.recovery_timer.stop()
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
w.optimize.setChecked(True)
w.flow_controls['paragraph_gap_mm'].setValue(5)
ready()
w.select_fragment(next(f for f in w.snapshot.fragments if f.text=='1'))
w.rate('bad')
project=root/'正式 项目.inkdoc'
w.session_path=project
assert w.save_project(), errors
original=project.read_bytes()
w.load_project_path(project); ready()
w.editor.insertPlainText('2 '); ready()

def state():
    return (w.source_session.identity_record(), w.buffer.raw, w.resolver,
            w.resolver.selection_records(), w.flow, w.page, w.style,
            dict(w.book.records), w.snapshot, w.session_path, w.session_hash,
            w.dirty, w.edit_generation, w.editor.toPlainText(), w.optimize.isChecked(),
            w.recovery_path, w.recovery_hash)

before=state()
for name,value in [('styles.json',b'[]'),('reviews.json',b'[{}]'),
                   ('resources.json',b'[null]'),('identity.json',b'{}')]:
    members=fixture(); members[name]=value
    path=root/'损坏.inkdoc'; archive(path,members)
    QtWidgets.QFileDialog.getOpenFileName=lambda *a,**k:(str(path),'')
    w.confirm_discard=lambda:True
    w.open_project()
    assert errors and state()==before, name
assert project.read_bytes()==original

# First editor session owns one recovery path; updates use its expected hash.
w.write_recovery(); first=w.recovery_path
assert first.is_file() and first.parent==root/'artifacts/editor_recovery'
first_bytes=first.read_bytes()
first_loaded=load_package(first)
assert first_loaded.session.identity_record()==w.source_session.identity_record()
assert first_loaded.flow==w.flow and first_loaded.reviews and first_loaded.optimize
w.write_recovery()
assert load_package(first).session.source==first_loaded.session.source
first_bytes=first.read_bytes()

# Reopening a formal project starts a distinct editing session, even with the same document ID.
w.load_project_path(project); ready()
assert w.recovery_path is None and w.recovery_hash is None
w.editor.insertPlainText('3 '); ready(); w.write_recovery()
second=w.recovery_path
assert second!=first and second.is_file() and first.read_bytes()==first_bytes
assert load_package(second).session.document_id==first_loaded.session.document_id
assert load_package(second).session.source!=first_loaded.session.source

# A second window of the same project also cannot take ownership of either prior recovery.
other=MixedWindow(source='1')
other.load_project_path(project)
other.editor.insertPlainText('4 ')
other.recovery_timer.stop()
other.write_recovery()
third=other.recovery_path
assert third not in {first,second} and third.is_file()
assert first.read_bytes()==first_bytes
other.dirty=False; other.close()

# External edits stay intact; errors are visible without touching the formal project.
second.write_bytes(b'external draft')
w.write_recovery()
assert second.read_bytes()==b'external draft'
assert '自动恢复副本未保存' in w.status.text()
assert project.read_bytes()==original

# Opening a valid recovery creates an unsaved project, never a save over its source.
QtWidgets.QFileDialog.getOpenFileName=lambda *a,**k:(str(first),'')
w.open_recovery(); ready()
assert w.session_path is None and w.session_hash is None and w.dirty
assert w.source_session.identity_record()==first_loaded.session.identity_record()
assert w.flow==first_loaded.flow and w.book.records and w.optimize.isChecked()
w.write_recovery()
assert w.recovery_path not in {first,second,third}
assert first.read_bytes()==first_bytes and project.read_bytes()==original
assert not list(root.rglob('.inkstruct-review-*'))
w.dirty=False; w.close()
print('Qt failed-load transaction and four independent recovery sessions passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONPATH": str(os.path.abspath("tests"))
            + os.pathsep
            + os.environ.get("PYTHONPATH", ""),
        },
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
