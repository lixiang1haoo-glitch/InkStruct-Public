import json
import os
import subprocess
import sys

import pytest

from handwriting_collector.tasks import CollectionTask
from inkstruct.capture_management import reconcile_pending_samples


@pytest.mark.parametrize(("kind", "character", "schema"), [
    ("han", "十", "handwriting_single_v1"),
    ("symbol", "?", "inkstruct_symbol_sample_v1"),
])
def test_recovers_interrupted_save_with_matching_identity(tmp_path, kind, character, schema):
    task = CollectionTask.create("Resume", "test", "writer", [(character, 2, 0)])
    writer = tmp_path / "samples" / "writer"
    pending = task.items[0]

    def write(bucket, name, **overrides):
        bucket.mkdir(parents=True, exist_ok=True)
        record = {"schema_version": schema, "sample_id": name, "writer_id": "writer",
                  "character": character, "task": {"task_id": task.task_id, "item_id": pending.item_id}}
        record.update(overrides)
        (bucket / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")

    canonical = writer / f"U+{ord(character):04X}"
    write(canonical, "false-writer", writer_id="other")
    write(canonical, "false-character", character="x")
    write(writer.parent / "other" / canonical.name, "wrong-directory")
    write(writer / "legacy-character-folder", "interrupted")
    assert reconcile_pending_samples(tmp_path, task, kind) == 1
    assert pending.sample_id == "interrupted"
    assert task.current_item() == task.items[1]
    assert reconcile_pending_samples(tmp_path, task, kind) == 0


def test_continue_button_drops_a_stale_result(tmp_path):
    program = r"""
from pathlib import Path
import sys
from functools import partial
from threading import Event
from time import monotonic

from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from handwriting_collector import config
from handwriting_collector.tasks import CollectionTask, TaskRepository
from inkstruct import capture_workspace
from inkstruct.application import InkStructWindow

root = Path(sys.argv[1])
config.UiSettingsStore = partial(config.UiSettingsStore, root / "collector-ui.json")
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root / "settings"))
app = QtWidgets.QApplication([])
window = InkStructWindow(workspace=root / "workspace")
window.show()
window.tabs.setCurrentIndex(0)
han = window.collector.single_widget
catalog = han._capture_catalog
writer = catalog.create_writer("First")
other = catalog.create_writer("Second")
task = CollectionTask.create("Continue", "test", writer, [("一", 1, 0)])
repo = TaskRepository(catalog.root)
path = repo.save(task)
original = path.read_bytes()
han.choose_writer(writer)
ui = han.capture_workspace

def pump(predicate):
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        QtTest.QTest.qWait(5)
    assert predicate()

entered, release = Event(), Event()
prepare = capture_workspace.prepare_managed_task

def wait_before_open(entry, catalog):
    entered.set()
    assert release.wait(5)
    return prepare(entry, catalog)

capture_workspace.prepare_managed_task = wait_before_open
item = ui.recent.topLevelItem(0)
button = ui.recent.itemWidget(item, 2).findChild(QtWidgets.QPushButton)
button.click()
pump(entered.is_set)
assert not button.isEnabled() and button.text() == "正在打开…" and han.task is None
han.choose_writer(other)
release.set()
pump(lambda: ui.opening is None)
assert han.task is None and path.read_bytes() == original
assert "han:" + task.task_id not in catalog.read()["tasks"]
han.choose_writer(writer)
ui.recent.itemWidget(ui.recent.topLevelItem(0), 2).findChild(QtWidgets.QPushButton).click()
pump(lambda: han.task is not None)
assert han.task.task_id == task.task_id and path.read_bytes() == original

hint = han.findChild(QtWidgets.QFrame, "captureInputHint")
assert not hint.isVisible()
pump(han.canvas.isVisible)
pos = QtCore.QPointF(60, 60)
left = QtCore.Qt.MouseButton.LeftButton
press = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, pos, pos, left, left,
                          QtCore.Qt.KeyboardModifier.NoModifier)
app.sendEvent(han.canvas, press)
assert hint.isVisible() and hint.message.text() == "收到鼠标输入"
assert han.canvas.trajectory.point_count == 0
hint.action.click()
assert not hint.isVisible() and han.input_mode_picker.currentData() == "mouse"
assert window.collector.symbol_widget.input_mode_picker.currentData() == "mouse"
window.close()
app.processEvents()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen")},
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
