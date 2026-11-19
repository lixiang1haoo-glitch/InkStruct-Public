"""Document settings through the layout toolbar and regular project save."""

import os
import subprocess
import sys

import pytest


PROGRAM = r"""
from dataclasses import replace
from pathlib import Path
import sys
import time
from PySide6 import QtCore, QtWidgets

from inkstruct.document.flow_template import FlowTemplate
from inkstruct.document.package import load_package, save_package
from inkstruct.editor.mixed import MixedWindow
from inkstruct.global_defaults import GlobalDefaultsStore

root = Path(sys.argv[1])
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root / "settings"))
window = MixedWindow(source="12.34\n\n56.78")
window.resize(1120, 720)
window.show()

def wait_layout(previous=None):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        app.processEvents()
        if window.snapshot and window.snapshot is not previous and not window.timer.isActive() and not window.worker:
            window.recovery_timer.stop()
            assert window.canvas.snapshot is window.snapshot
            return window.snapshot
        time.sleep(.01)
    raise AssertionError(window.status.text())

def open_section(key):
    window.findChild(QtWidgets.QToolButton, "document_settings_" + key).click()
    app.processEvents()
    assert settings.isVisible() and window.scroll.isVisible()
    return settings.drafts[key][1]

def confirm(accept):
    def finish():
        dialog = app.activeModalWidget()
        assert dialog.objectName() == "document_layout_default_confirmation"
        table = dialog.findChild(QtWidgets.QTreeWidget)
        visible_diff.append([
            tuple(table.topLevelItem(i).text(c) for c in range(3))
            for i in range(table.topLevelItemCount())
        ])
        pending.append(any("仍待应用" in item.text() for item in dialog.findChildren(QtWidgets.QLabel)))
        if accept:
            next(b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == "保存为新建默认").click()
        else:
            dialog.reject()
    QtCore.QTimer.singleShot(0, finish)
    settings.defaults_button.click()

store = GlobalDefaultsStore()
base = store.load()[0]
custom_page = FlowTemplate(name="实验用纸", mode="blank", width_mm=170, height_mm=240,
                           margins_mm=(11, 16, 19, 13))
older = root / "older.inkdoc"
report = root / "report.inkdoc"
save_package(older, window.source_session, window.resolver, window.page, base.style, flow=window.flow)
report_flow = replace(window.flow, template=custom_page, paragraph_align="left",
                      paragraph_gap_mm=3.123456789)
save_package(report, window.source_session, window.resolver, window.page,
             replace(base.style, em_mm=5.123456789), flow=report_flow)
window.load_project_path(report)
before = wait_layout()
settings = window.document_settings
window.workspace_views.set_mode("source", persist=False)
body = open_section("body")
assert settings.document_name.text() == "当前文档 · report.inkdoc"
assert body.style.controls["em_mm"].value() == 5.123457
assert body.flow.controls["paragraph_gap_mm"].value() == 3.123457
assert body.paragraph_align.currentData() == "left"
assert not settings.apply_button.isEnabled() and not window.dirty
body.style.controls["em_mm"].setValue(7)
assert settings.close_button.text() == "取消"
settings.close_button.click()
assert not settings.isVisible() and window.workspace_views.mode == "source"
assert window.style.em_mm == 5.123456789 and not window.dirty

body = open_section("body")
body.style.controls["em_mm"].setValue(7)
paper = open_section("page")
assert paper.paper.currentText() == "自定义" and paper.direction.currentText() == "纵向"
assert [paper.controls[key].value() for key in ("top_mm", "right_mm", "bottom_mm", "left_mm")] == [11, 16, 19, 13]
assert open_section("body") is body and body.style.controls["em_mm"].value() == 7
settings.apply_button.click()
after = wait_layout(before)
assert after.pages and window.style.em_mm == 7 and window.dirty
assert window.flow.paragraph_gap_mm == 3.123456789
assert window.flow.template == custom_page
assert GlobalDefaultsStore().load()[0] == base
assert load_package(report).style.em_mm == 5.123456789
assert window.save_project()
assert load_package(report).style.em_mm == 7

paper = open_section("page")
paper.paper.setCurrentText("A5")
paper.direction.setCurrentIndex(1)
paper.controls["top_mm"].setValue(12)
settings.apply_button.click()
wait_layout(after)
assert (window.flow.template.width_mm, window.flow.template.height_mm) == (210, 148)
assert window.flow.template.margins_mm == (12, 16, 19, 13)
assert GlobalDefaultsStore().for_new_document()[0].flow.template.width_mm == 210
assert window.save_project()
window.load_project_path(report)
wait_layout()
assert window.flow.template.height_mm == 148 and window.style.em_mm == 7
assert settings.document_name.text().endswith(report.name)

visible_diff, pending = [], []
body = open_section("body")
body.style.controls["em_mm"].setValue(8)
confirm(False)
assert GlobalDefaultsStore().load()[0] == base and not window.dirty
confirm(True)
assert ("字高", "6 mm", "8 mm") in visible_diff[-1] and pending[-1]
assert settings.apply_button.isEnabled() and window.style.em_mm == 7 and not window.dirty
defaults = GlobalDefaultsStore().load()[0]
assert defaults.style.em_mm == 8 and defaults.flow.table == base.flow.table
assert defaults.flow.template == base.flow.template

paper = open_section("page")
paper.paper.setCurrentText("B5")
confirm(True)
assert ("纸张宽度", "210 mm", "250 mm") in visible_diff[-1] and pending[-1]
assert window.flow.template.height_mm == 148 and not window.dirty
assert GlobalDefaultsStore().load()[0] == defaults
window.new_document()
wait_layout()
assert settings.document_name.text().endswith("未命名文档")
assert (window.flow.template.width_mm, window.flow.template.height_mm) == (250, 176)
assert window.style.em_mm == 8
assert not settings.apply_button.isEnabled()
window.load_project_path(older)
wait_layout()
assert settings.document_name.text().endswith(older.name)
assert window.style == base.style and window.flow.template.height_mm == 297
assert load_package(report).flow.template.height_mm == 148
assert load_package(report).style.em_mm == 7
window.dirty = False
window.close()
"""


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_document_settings_apply_cancel_and_new_defaults(tmp_path, scale):
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path)],
        env={**os.environ, "QT_SCALE_FACTOR": scale,
             "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen"),
             "INKSTRUCT_LAYOUT_PREVIEW_HOME": str(tmp_path / "preview")},
        capture_output=True,
        encoding="utf-8",
        timeout=70,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
