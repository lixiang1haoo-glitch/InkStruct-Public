import os
import subprocess
import sys
import uuid

import pytest

from inkstruct import symbol_reuse


def test_capture_inventory_scopes_to_writer_and_accepts_an_older_layout(tmp_path, monkeypatch):
    root = tmp_path / "collection"
    writer = root / "samples" / "synthetic"
    writer.mkdir(parents=True)
    calls = []

    def inventory(path, selected, *, cancelled):
        calls.append((path, selected, cancelled()))
        return {}

    monkeypatch.setattr(symbol_reuse, "inventory", inventory)
    assert symbol_reuse.capture_inventory(root, "synthetic", lambda: False) == {}
    assert symbol_reuse.capture_inventory(root, "legacy", lambda: True) == {}
    assert calls == [(writer, "synthetic", False), (root, "legacy", True)]
    with pytest.raises(ValueError):
        symbol_reuse.capture_inventory(root, "../other", lambda: False)


def test_create_dialog_author_selection_lazy_controls_and_shared_scan(tmp_path):
    program = r"""
from functools import partial
from pathlib import Path
from threading import Event
from time import monotonic, sleep
import sys

from PySide6 import QtCore, QtWidgets
from handwriting_collector import config
from inkstruct import capture_task_dialog
from inkstruct.capture_task_dialog import CaptureTaskDialog
from inkstruct.collector import main
from inkstruct.symbol_tasks import TASK_GROUPS

root = Path(sys.argv[1])
config.UiSettingsStore = partial(config.UiSettingsStore, root / "collector-ui.json")
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root / "settings"))
app = QtWidgets.QApplication([])
window = main(["InkStruct"], create_only=True, workspace=root / "workspace")
symbol = window.symbol_widget
window.tabs.setCurrentWidget(symbol)
window.show()
app.processEvents()
catalog = symbol._capture_catalog
first, second = catalog.create_writer("甲"), catalog.create_writer("乙")
assert not symbol.writer_edit.text() and symbol.capture_workspace.begin.isEnabled()

def pump(predicate):
    deadline = monotonic() + 8
    while not predicate():
        app.processEvents()
        assert monotonic() < deadline
        sleep(.002)

entered, release = Event(), Event()
calls = []
style = TASK_GROUPS["digits"][2]

def slow_inventory(scope, writer, cancelled):
    calls.append(writer)
    if writer == first:
        entered.set()
        assert release.wait(8) and cancelled()
        return {("1", style): {"old": {}}, ("2", style): {"old": {}}}
    return {("1", style): {"current": {}}} if writer == second else {}

capture_task_dialog.capture_inventory = slow_inventory
dialog = CaptureTaskDialog(symbol)
assert dialog.import_selection is None and not any(dialog.selection.characters.values())
dialog.selection.groups["digits"].setChecked(True)
dialog.selection.repeats.setValue(1)
dialog.name.setText("测试新建任务")
dialog.name.setModified(True)
dialog.show()
pump(lambda: dialog.writer_picker.findData(second) > 0)
assert calls == [] and not dialog.start.isEnabled()
assert dialog.counts["existing"].text() == "—" and dialog.preview.count() == 10
dialog.writer_picker.setText(first)
pump(entered.is_set)
assert dialog.status.text() == "正在核对已有样本…" and not dialog.start.isEnabled()
dialog.findChild(QtWidgets.QPushButton, "task_expand_digits").click()
assert len(dialog.selection.characters["digits"]) == 10
two = dialog.selection.characters["digits"]["2"]
assert two.isChecked()
two.setChecked(False)
dialog.selection.reuse[("latin_italic", "A")] = {}
dialog.writer_picker.setText(second)
assert not dialog.selection.reuse and not two.isChecked()
assert dialog.name.text() == "测试新建任务" and dialog.selection.repeats.value() == 1
release.set()
pump(lambda: dialog.symbol_inventory is not None)
assert calls == [first, second]
assert dialog.start.isEnabled() and len(dialog.entries) == 8
assert dialog.counts["existing"].text() == "1 字"
assert not symbol.writer_edit.text()

dialog.sources.setCurrentIndex(1)
assert dialog.import_selection.available is dialog.selection.available
assert not any(dialog.import_selection.characters.values())
dialog.file_path = root / "导入.txt"
dialog.file_path.write_text("12\n", encoding="utf-8")
dialog.repeats.setValue(1)
assert [char for char, *_ in dialog.entries] == ["2"]
assert calls == [first, second]
dialog.reject()
dialog.dispose()
assert not symbol.writer_edit.text() and not catalog.tasks()

new = CaptureTaskDialog(symbol)
new.show()
pump(new.isVisible)

def name_writer():
    prompt = app.activeModalWidget()
    assert isinstance(prompt, QtWidgets.QInputDialog)
    prompt.setTextValue("弹窗内新建")
    prompt.accept()

QtCore.QTimer.singleShot(0, name_writer)
new.add_writer_button.click()
assert new.writer and new.writer_picker.currentData() == new.writer
assert catalog.writers()[new.writer]["name"] == "弹窗内新建" and not symbol.writer_edit.text()
pump(lambda: new.symbol_inventory is not None)
created = new.writer
new.reject()
new.dispose()

reopened = CaptureTaskDialog(symbol)
reopened.show()
pump(lambda: reopened.writer_picker.findData(created) > 0)
assert not reopened.writer and not symbol.writer_edit.text()
reopened.reject()
reopened.dispose()
window.close()
app.processEvents()
"""
    isolated = tmp_path.parents[1] / ("task-" + uuid.uuid4().hex[:8])
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", program, str(isolated)],
        env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen")},
        capture_output=True, text=True, encoding="utf-8", timeout=35, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
