from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest
from test_document_layout import glyph


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None, reason="desktop extra not installed"
)
def test_live_editor_review_save_ime_stale_results_and_run_changes(tmp_path):
    run = tmp_path / "run"
    (run / "trajectories").mkdir(parents=True)
    for char in ("人", "天", "𠀀"):
        (run / "trajectories" / f"U+{ord(char):04X}.json").write_text(
            json.dumps(glyph(char), ensure_ascii=False)
        )
    program = r"""
import json, sys, time
from pathlib import Path
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from inkstruct.editor.app import ReviewWindow
from inkstruct.editor.review import load_session
app = QtWidgets.QApplication([])
run = Path(sys.argv[1])
w = ReviewWindow(source="人人\r\n𠀀天", run=run)
w.show()
def ready():
    end = time.monotonic() + 10
    while time.monotonic() < end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
assert w.buffer.raw == "人人\r\n𠀀天"
f = w.snapshot.fragments[0]
# Actual page hit testing selects and maps back into source.
QtTest.QTest.mouseClick(w.canvas, QtCore.Qt.MouseButton.LeftButton,
                       pos=w.canvas.rect_for(f).center().toPoint())
assert w.editor.textCursor().selectedText() == "人"
assert w.inspector.asset.character == "人"
w.findChild(QtWidgets.QPushButton, "rate_bad").click()
key = f.asset_id
assert w.book.records[key].rating == "bad"
assert sum(f.asset_id == key for f in w.snapshot.fragments) == 2
w.note.setFocus()
QtTest.QTest.keyClicks(w.note, "shape")
assert w.book.records[key].note == "shape"
w.filter.setCurrentIndex(w.filter.findData("bad"))
assert w.glyph_list.count() == 1
w.filter.setCurrentIndex(w.filter.findData("all"))
w.next_unrated()
assert w.selected_fragment.text == "𠀀"
assert w.editor.textCursor().selectedText() == "𠀀"
w.rate("good")
w.undo_rating()
assert w.selected_fragment.asset_id not in w.book.records
w.redo_rating()
assert w.book.records[w.selected_fragment.asset_id].rating == "good"
# Save / reopen actual UI project with no dialogs.
w.session_path = run.parent / "review.inkreview"
assert w.save_project()
source, saved_run, book, page, style = load_session(w.session_path)
assert source.raw == w.buffer.raw and key in book.records
QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(w.session_path), ""))
w.open_project()
ready()
assert key in w.book.records and not w.dirty
# Save As cancellation keeps the original save target; a new target preserves the old project.
old_path = w.session_path
old_bytes = old_path.read_bytes()
QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
w.save_project_as()
assert w.session_path == old_path
copy_path = run.parent / "copy.inkreview"
QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(copy_path), ""))
w.save_project_as()
assert w.session_path == copy_path and copy_path.exists() and old_path.read_bytes() == old_bytes
# A preedit never enters the persisted source. Commit is atomic, then native undo works.
w.editor.setFocus()
cursor = w.editor.textCursor()
cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
w.editor.setTextCursor(cursor)
before = w.buffer.raw
QtWidgets.QApplication.sendEvent(w.editor, QtGui.QInputMethodEvent("ren", []))
assert w.buffer.raw == before
assert w.editor.composing
commit = QtGui.QInputMethodEvent()
commit.setCommitString("人")
QtWidgets.QApplication.sendEvent(w.editor, commit)
assert not w.editor.composing and w.buffer.raw == before + "人"
assert not w.canvas.isEnabled()
ready()
assert key in w.book.records
w.editor.undo()
ready()
assert w.buffer.raw == before
# Stale result/exception cannot publish after another revision.
old_snapshot = w.snapshot
old_key, old_revision = w.current_key, w.revision
w.editor.insertPlainText("缺")
w.timer.stop()
assert not w.canvas.isEnabled()
w.publish({"revision": old_revision, "key": old_key, "error": "STALE FAILURE"})
assert "STALE FAILURE" not in w.status.text()
ready()
assert not w.snapshot.exportable and not w.page_export.isEnabled()
missing = next(f for f in w.snapshot.fragments if f.text == "缺")
w.select_fragment(missing)
assert not w.findChild(QtWidgets.QPushButton, "rate_bad").isEnabled()
# Replacing the actual glyph file does not inherit the previous version's review.
p = run / "trajectories" / "U+4EBA.json"
v = json.loads(p.read_bytes())
v["profile_version"] = "changed"
p.write_text(json.dumps(v))
w.refresh_assets()
ready()
new_key = next(f.asset_id for f in w.snapshot.fragments if f.text == "人")
assert new_key != key and new_key not in w.book.records and key in w.book.records
# High zoom preserves click-to-source mapping.
w.zoom.setCurrentIndex(3)
f = next(f for f in w.snapshot.fragments if f.text == "人")
QtTest.QTest.mouseClick(w.canvas, QtCore.Qt.MouseButton.LeftButton,
                       pos=w.canvas.rect_for(f).center().toPoint())
assert w.editor.textCursor().selectedText() == "人"
assert w.canvas.scale == 6.0
w.dirty = False
w.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, str(run)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
