"""Exercise real Qt source transactions and portable projects in an isolated process."""

import importlib.util
import json
import os
import subprocess
import sys
import zipfile

import pytest
from test_document_layout import glyph
from test_symbol_provider import specimen


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_markdown_editor_identity_ime_projects_recovery_and_exports(tmp_path):
    run = tmp_path / "run"
    (run / "trajectories").mkdir(parents=True)
    for c in "人𠀀":
        (run / "trajectories" / f"U+{ord(c):04X}.json").write_text(json.dumps(glyph(c)))
    samples = tmp_path / "samples.zip"
    with zipfile.ZipFile(samples, "w") as z:
        for i in range(5):
            z.writestr(f"symbols/1-{i}.json", json.dumps(specimen(sid=str(i), height=10 + i)))
    program = r"""
import sys, time
from dataclasses import asdict
from pathlib import Path
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.plotter.options import ExportOptions
from inkstruct.editor.export_check import check_export
def configure(self,snapshot):
 check=check_export(snapshot,self.markdown_document,self.flow,ExportOptions(tuple(range(len(snapshot.pages)))),machine=True)
 return ('machine',check,check.machine,self.optimize.isChecked()) if not check.errors else None
MixedWindow.configure_document_export=configure
import inkstruct.editor.mixed as mixed
from inkstruct.document.package import load_package
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg

app = QtWidgets.QApplication([])
root = Path(sys.argv[1])
w = MixedWindow(source="# 人人\r\n\r\n𠀀 1.20 1.20", run=root / "run", symbols=root / "samples.zip")
errors = []
w.message_error = lambda e: errors.append(str(e))
w.show()
def ready():
    end = time.monotonic() + 10
    while time.monotonic() < end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            assert not w.source_error, w.source_error
            return
        QtTest.QTest.qWait(10)
    raise AssertionError((w.status.text(), w.source_error))
def ids():
    return [(f.occurrence_id, f.asset_id) for f in w.snapshot.fragments]
def move(position):
    c = w.editor.textCursor(); c.setPosition(position); w.editor.setTextCursor(c)
ready()
original, identities = w.buffer.raw, ids()
assert w.snapshot.exportable
assert len(w.resolver.pools["1"]) == 5  # No builtin mixed into a handwritten pool.
move(0)
w.editor.insertPlainText("人 1.20\n\n")
ready()
assert set(identities) <= set(ids())
assert w.buffer.raw.startswith("人 1.20\r\n\r\n")
w.editor.undo(); ready()
assert w.buffer.raw == original and ids() == identities
w.editor.redo(); ready()
assert set(identities) <= set(ids())
w.editor.undo(); ready()

# Preedit is not a source transaction. Its commit and undo preserve untouched anchors.
c = w.editor.textCursor(); c.movePosition(QtGui.QTextCursor.MoveOperation.End)
w.editor.setTextCursor(c)
atoms = w.source_session.atom_ids
QtWidgets.QApplication.sendEvent(w.editor, QtGui.QInputMethodEvent("ren", []))
assert w.source_session.atom_ids == atoms and w.buffer.raw == original
commit = QtGui.QInputMethodEvent(); commit.setCommitString("人")
QtWidgets.QApplication.sendEvent(w.editor, commit)
assert w.buffer.raw == original + "人" and not w.canvas.isEnabled()
assert w.source_session.atom_ids[:-1] == atoms
ready()
w.editor.undo(); ready()
assert ids() == identities and w.source_session.atom_ids == atoms

# Canceling composition changes no anchors; explicit replacement is one undo step.
QtWidgets.QApplication.sendEvent(w.editor, QtGui.QInputMethodEvent("ren", []))
QtWidgets.QApplication.sendEvent(w.editor, QtGui.QInputMethodEvent())
assert w.source_session.atom_ids == atoms and w.buffer.raw == original
commit = QtGui.QInputMethodEvent(); commit.setCommitString("𠀀", -1, 1)
QtWidgets.QApplication.sendEvent(w.editor, commit)
ready()
assert w.buffer.raw == original[:-1] + "𠀀"
assert w.source_session.atom_ids[:-1] == atoms[:-1]
w.editor.undo(); ready()
assert ids() == identities and w.source_session.atom_ids == atoms

# Page hit and source navigation work across UTF-16 / CRLF, including non-BMP Han.
f = next(f for f in w.snapshot.fragments if f.text == "𠀀")
QtTest.QTest.mouseClick(w.canvas, QtCore.Qt.MouseButton.LeftButton,
                       pos=w.canvas.rect_for(f).center().toPoint())
assert w.editor.textCursor().selectedText() == "𠀀"
one = next(f for f in w.snapshot.fragments if f.text == "1")
w.select_fragment(one); w.rate("bad")
assert w.inspector.asset.asset_id == one.asset_id
assert w.book.records[one.asset_id].writer_id == "fixture"
w.flow_controls["first_line_indent_mm"].setValue(7)
w.flow_controls["paragraph_gap_mm"].setValue(4)
w.optimize.setChecked(True)
ready()
project = root / "body.inkdoc"
w.session_path = project
assert w.save_project(), errors
saved_geometry = [asdict(p) for p in w.snapshot.pages]
selected = w.resolver.selection_records()
saved = load_package(project)
assert saved.flow.first_line_indent_mm == 7 and saved.optimize and len(saved.reviews) == 1
w.load_project_path(project); ready()
assert not w.dirty and w.run_path == "" and w.symbol_path == ""
assert [asdict(p) for p in w.snapshot.pages] == saved_geometry
assert w.resolver.selection_records() == selected
assert len(w.resolver.pools["1"]) == 5
assert w.book.records[one.asset_id].rating == "bad"

# Update writes a prior valid project; external edits block replacement.
w.optimize.setChecked(False)
previous_bytes = project.read_bytes()
assert w.save_project()
assert project.with_name(project.name + ".previous.inkdoc").read_bytes() == previous_bytes
valid_bytes = project.read_bytes()
project.write_bytes(valid_bytes + b"external")
assert not w.save_project() and "修改" in errors[-1]
assert project.read_bytes() == valid_bytes + b"external"
project.write_bytes(valid_bytes)

# Even non-layout changes made while saving remain dirty, with the saved state frozen.
real_save = mixed.save_package
class SaveEdit(QtCore.QObject):
    requested = QtCore.Signal()

save_edit = SaveEdit()
save_edit.requested.connect(lambda: w.optimize.setChecked(True), QtCore.Qt.ConnectionType.BlockingQueuedConnection)
def editing_save(*a, **k):
    save_edit.requested.emit()
    return real_save(*a, **k)
mixed.save_package = editing_save
assert w.save_project()
assert w.dirty and not load_package(project).optimize
mixed.save_package = real_save

# Recovery never replaces the user's project and preserves identity / style / reviews.
w.recovery_path = root / "recovery.inkdoc"
w.recovery_hash = None
w.write_recovery()
recovered = load_package(w.recovery_path)
assert recovered.session.atom_ids == w.source_session.atom_ids
assert recovered.optimize and recovered.reviews and recovered.flow == w.flow
assert not load_package(project).optimize

# Both exports freeze the accepted page revision before the file picker nested event loop.
frozen = w.snapshot
target = root / "machine"
def choose_export(*a, **k):
    w.editor.insertPlainText("缺")
    return str(target), ""
QtWidgets.QFileDialog.getSaveFileName = staticmethod(choose_export)
w.optimize.setChecked(False)
w.export_document()
end_export=time.monotonic()+20
while w.export_job is not None and time.monotonic()<end_export:
    app.processEvents();QtTest.QTest.qWait(10)
assert w.export_job is None and not w.last_export_result['error'], getattr(w,'last_export_result',{})

assert (target / "page-001.svg").read_text() == page_svg(plan_from_snapshot(frozen).pages[0])
ready()
assert not w.snapshot.exportable
index = next(i for i in range(w.diagnostic_picker.count())
             if "asset-missing" in w.diagnostic_picker.itemText(i))
w.diagnostic_picker.setCurrentIndex(index); w.navigate_diagnostic()
assert w.editor.textCursor().selectedText() == "缺"
assert w.export_button.isEnabled() and configure(w,w.snapshot) is None

# Mode changes reject stale success and failure; source undo remains usable.
old_key, old_revision, old_snapshot = w.current_key, w.revision, w.snapshot
w.mode_picker.setCurrentIndex(w.mode_picker.findData("plain-text"))
w.publish({"revision": old_revision, "key": old_key, "error": "STALE"})
assert "STALE" not in w.status.text() and not w.canvas.isEnabled()
w.mode_picker.setCurrentIndex(w.mode_picker.findData("markdown"))
w.editor.undo(); ready()
assert w.snapshot.exportable
assert errors and all("修改" in e for e in errors)
w.dirty = False; w.close()
print("Qt Markdown acceptance passed")
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
