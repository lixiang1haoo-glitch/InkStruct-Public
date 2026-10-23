"""Real source edits cancel obsolete work before identity mapping, including IME commits."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_cancel_before_mapping_preserves_ime_and_undo():
    program = r"""
import time
from PySide6 import QtGui, QtTest, QtWidgets
from inkstruct.editor.mixed import MixedWindow

class Window(MixedWindow):
    def write_recovery(self):
        pass

app = QtWidgets.QApplication([])
w = Window(source="12\r\n😀3")
w.show()
def ready():
    end = time.monotonic() + 10
    while time.monotonic() < end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():
            assert not w.source_error, w.source_error
            return
        QtTest.QTest.qWait(5)
    raise AssertionError(w.status.text())

ready()
source, atoms = w.buffer.raw, w.source_session.atom_ids
for use_ime in (False, True):
    event = w.cancelled
    assert not event.is_set()
    cursor = w.editor.textCursor()
    cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
    w.editor.setTextCursor(cursor)
    if use_ime:
        QtWidgets.QApplication.sendEvent(w.editor, QtGui.QInputMethodEvent("si", []))
        assert not event.is_set()  # Preedit alone is not a source transaction.
        assert w.source_session.atom_ids == atoms and w.buffer.raw == source
    original_apply = w.source_session.apply
    calls = []
    def apply(*args, **kw):
        assert event.is_set(), "old work was not cancelled before source identity mapping"
        calls.append(args)
        return original_apply(*args, **kw)
    w.source_session.apply = apply
    if use_ime:
        commit = QtGui.QInputMethodEvent()
        commit.setCommitString("4")
        QtWidgets.QApplication.sendEvent(w.editor, commit)
    else:
        w.editor.insertPlainText("4")
    w.source_session.apply = original_apply
    assert len(calls) == 1
    assert w.buffer.raw == source + "4" and w.source_session.atom_ids[:-1] == atoms
    assert not w.canvas.isEnabled()
    ready()
    assert w.snapshot.revision == w.revision
    w.editor.undo()
    ready()
    assert w.buffer.raw == source and w.source_session.atom_ids == atoms
w.dirty = False
w.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
