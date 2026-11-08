"""Desktop Markdown import uses checked local resources and retains them in projects."""

import os
import subprocess
import sys


def test_markdown_import_and_new_document(tmp_path):
    script = r"""
import sys
import time
from dataclasses import replace
from pathlib import Path
from PIL import Image
from PySide6 import QtCore, QtWidgets
from inkstruct.document.package import load_package
from inkstruct.editor.mixed import MixedWindow
from inkstruct.global_defaults import GlobalDefaultsStore, LayoutDefaults

root = Path(sys.argv[1])
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root))
defaults = LayoutDefaults()
defaults = replace(defaults, style=replace(defaults.style, em_mm=7))
GlobalDefaultsStore().save(defaults)
w = MixedWindow(source="12")
base = root / "source"
base.mkdir()
(base / "plots").mkdir()
png = base / "plots/拟合 图.png"
jpeg = base / "表.jpg"
Image.new("RGB", (80, 40), "red").save(png)
Image.new("RGB", (80, 40), "green").save(jpeg)
svg = base / "line.svg"
svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" viewBox="0 0 20 10"><path d="M1 1L19 9" fill="none" stroke="black"/></svg>')
source = ("![1](<plots/拟合 图.png>)\n\n![2](%E8%A1%A8.jpg)\n\n![3](line.svg)"
          "\n\n![4](missing.png)\n\n![5](https://example.com/x.png)"
          "\n\n![6](../escape.png)")
path = base / "notes.md"
path.write_bytes(source.encode("utf-8-sig"))
warnings = []
def acknowledge(box):
    warnings.append((box.text(), box.detailedText()))
    return QtWidgets.QMessageBox.Ok
QtWidgets.QMessageBox.exec = acknowledge
QtWidgets.QFileDialog.getOpenFileName = lambda *a: (str(path), "")
w.open_text()
assert w.source_session.source == source and len(w.flow.images) == 3, (w.flow.images, warnings)
assert len(warnings) == 1 and "3 处引用" in warnings[0][0]
assert all(s in warnings[0][1] for s in ("missing.png", "example.com", "../escape.png"))

def ready():
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        app.processEvents()
        if w.snapshot is not None and w.worker is None and not w.timer.isActive():
            w.recovery_timer.stop()
            return
        time.sleep(.01)
    raise AssertionError(w.status.text())

ready()
assert sum(d.code == "image-resource-missing" for d in w.snapshot.diagnostics) == 3
w.source_history("undo")
assert w.source_session.source == "12" and not w.flow.images
w.source_history("redo")
assert w.source_session.source == source and len(w.flow.images) == 3
out = root / "saved.inkdoc"
QtWidgets.QFileDialog.getSaveFileName = lambda *a: (str(out), "")
assert w.save_project()
frozen = load_package(out)
png.unlink()
jpeg.unlink()
svg.unlink()
w.load_project_path(out)
ready()
assert w.flow.images == frozen.flow.images and w.resolver.selection_records() == frozen.resolver.selection_records()
old_id = w.source_session.document_id
w.editor.insertPlainText("1")
QtWidgets.QMessageBox.question = lambda *a, **kw: QtWidgets.QMessageBox.Cancel
w.new_document()
assert w.source_session.document_id == old_id and w.dirty
QtWidgets.QMessageBox.question = lambda *a, **kw: QtWidgets.QMessageBox.Discard
w.new_document()
assert w.source_session.document_id != old_id and w.source_session.source == ""
assert not w.flow.images and w.session_path is None and not w.dirty
assert w.style == defaults.style and w.snapshot is None and w.canvas.snapshot is None
assert not w.book.records and not w.resolver.selection_records()
assert load_package(out).session.source == source
w.timer.stop()
if w.cancelled:
    w.cancelled.set()
w.pool.waitForDone()
w.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
