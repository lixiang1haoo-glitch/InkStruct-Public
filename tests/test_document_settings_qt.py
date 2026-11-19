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

from inkstruct.application import InkStructWindow
from inkstruct.document.flow_template import FlowTemplate
from inkstruct.document.package import load_package, save_package
from inkstruct.document.table_style import TableStyle
from inkstruct.global_defaults import GlobalDefaultsStore
from inkstruct.settings_dialog import SettingsDialog

root = Path(sys.argv[1])
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root / "settings"))
shell = InkStructWindow(workspace=root / "workspace")
shell.resize(1120, 720)
shell.show()
window = shell.editor
shell.tabs.setCurrentWidget(window)
views = window.workspace_views
window.replace_text("12.34\n\n|1|2|\n|---|---|\n|3|4|")
assert not any(window.findChild(QtWidgets.QToolButton, "document_settings_" + name)
               for name in ("body", "page", "more"))

def wait_layout(previous=None):
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        app.processEvents()
        if window.snapshot and window.snapshot is not previous and not window.timer.isActive() and not window.worker:
            window.recovery_timer.stop()
            if views.mode != "source":
                assert window.canvas.snapshot is window.snapshot
            return window.snapshot
        time.sleep(.01)
    raise AssertionError(window.status.text())

def open_settings(callback):
    errors = []
    invocations = []
    def inspect():
        dialog = app.activeModalWidget()
        invocations.append(dialog)
        try:
            assert isinstance(dialog, SettingsDialog)
            assert dialog.scope == "document" and dialog.current == "body"
            callback(dialog)
        except BaseException as error:
            errors.append(error)
        finally:
            dialog.done(QtWidgets.QDialog.DialogCode.Rejected)
    QtCore.QTimer.singleShot(0, inspect)
    shell.settings_button.click()
    assert len(invocations) == 1
    if errors:
        raise errors[0]

def workspace_state():
    return (views.mode, tuple(views.splitter.sizes()), tuple(views.split_sizes),
            views.source_pane.isVisible(), views.preview_pane.isVisible(),
            window.source_session.source, window.source_session.atom_ids, window.dirty)

store = GlobalDefaultsStore()
base = store.load()[0]
custom_page = FlowTemplate(name="实验用纸", mode="blank", width_mm=170, height_mm=240,
                           margins_mm=(11, 16, 19, 13))
older = root / "older.inkdoc"
report = root / "report.inkdoc"
save_package(older, window.source_session, window.resolver, window.page, base.style, flow=window.flow)
table = next(node for node in window.parse_current_source().nodes if node.kind == "table")
override = TableStyle(width_mm=124)
report_flow = replace(window.flow, template=custom_page, paragraph_align="left",
                      paragraph_gap_mm=3.123456789, table_overrides=((table.node_id, override),))
save_package(report, window.source_session, window.resolver, window.page,
             replace(base.style, em_mm=5.123456789), flow=report_flow)
window.load_project_path(report)
wait_layout()

views.set_mode("split", persist=False)
views.splitter.moveSplitter(330, 1)
views.remember_sizes()

for mode in ("source", "split", "preview"):
    views.set_mode(mode, persist=False)
    window.replace_text(window.source_session.source + "\n\n56.78")
    wait_layout()
    original = workspace_state()
    def cancel_drafts(dialog):
        assert workspace_state() == original
        assert dialog.scope_info.text() == "当前文档 · report.inkdoc"
        body = dialog.pages["body"]
        assert body.style.controls["em_mm"].value() == 5.123457
        assert body.flow.controls["paragraph_gap_mm"].value() == 3.123457
        assert body.paragraph_align.currentData() == "left"
        assert not dialog.save_button.isEnabled()
        body.style.controls["em_mm"].setValue(7)
        assert dialog.close_button.text() == "取消"
        assert window.style.em_mm == 5.123456789 and workspace_state() == original
    open_settings(cancel_drafts)
    assert workspace_state() == original

views.set_mode("split", persist=False)
before = wait_layout()
config = GlobalDefaultsStore.make_settings()

def apply_scopes(dialog):
    body = dialog.pages["body"]
    body.style.controls["em_mm"].setValue(7)
    dialog.select("page")
    paper = dialog.pages["page"]
    assert paper.paper.currentText() == "自定义" and paper.direction.currentText() == "纵向"
    assert [paper.controls[key].value() for key in ("top_mm", "right_mm", "bottom_mm", "left_mm")] == [11, 16, 19, 13]
    paper.paper.setCurrentText("A5")
    paper.direction.setCurrentIndex(1)
    paper.controls["top_mm"].setValue(12)
    dialog.select("table")
    dialog.pages["table"].editors[None].controls["width_mm"].setValue(140)

    dialog.select("body", scope="defaults")
    dialog.pages["body"].style.controls["em_mm"].setValue(8)
    dialog.select("preview")
    dialog.pages["preview"].acceleration.setChecked(False)
    dialog.select("body", scope="document")
    assert window.canvas.render_acceleration
    assert dialog.save_button.text() == "应用到当前文档"
    dialog.save_button.click()
    assert not dialog.save_button.isEnabled()
    wait_layout(before)
    assert window.style.em_mm == 7 and window.dirty
    assert window.flow.paragraph_gap_mm == 3.123456789
    assert (window.flow.template.width_mm, window.flow.template.height_mm) == (210, 148)
    assert window.flow.template.margins_mm == (12, 16, 19, 13)
    assert dict(window.flow.table_overrides) == {table.node_id: override}
    assert window.flow.table.width_mm == 140
    assert GlobalDefaultsStore().load()[0] == base
    assert not config.contains(GlobalDefaultsStore.PREVIEW_ACCELERATION_KEY)
    assert load_package(report).style.em_mm == 5.123456789

    dialog.select("body", scope="defaults")
    assert dialog.pages["body"].style.controls["em_mm"].value() == 8
    assert dialog.save_button.text() == "保存新建默认"
    dialog.save_button.click()
    defaults = GlobalDefaultsStore().load()[0]
    assert defaults.style.em_mm == 8 and defaults.flow.table == base.flow.table
    assert window.style.em_mm == 7 and not config.contains(GlobalDefaultsStore.PREVIEW_ACCELERATION_KEY)

    dialog.select("preview")
    assert dialog.save_button.text() == "保存应用偏好"
    dialog.save_button.click()
    assert not window.canvas.render_acceleration and not GlobalDefaultsStore.preview_acceleration_enabled()
    assert GlobalDefaultsStore().load()[0] == defaults and window.style.em_mm == 7

    dialog.select("body")
    dialog.pages["body"].style.controls["em_mm"].setValue(9)
    dialog.copy_button.click()
    assert dialog.views.currentWidget() is dialog.confirm_page
    assert "文档修改仍待应用" in dialog.confirm_scope.text()
    assert any(tuple(dialog.diff.topLevelItem(i).text(c) for c in range(3)) ==
               ("字高", "8 mm", "9 mm") for i in range(dialog.diff.topLevelItemCount()))
    dialog.reject()
    assert dialog.isVisible() and dialog.views.currentWidget() is dialog.edit
    assert GlobalDefaultsStore().load()[0].style.em_mm == 8
    dialog.copy_button.click()
    dialog.confirm_button.click()
    assert dialog.save_button.isEnabled() and window.style.em_mm == 7
    assert GlobalDefaultsStore().load()[0].style.em_mm == 9
    assert GlobalDefaultsStore().load()[0].flow.table == base.flow.table

    dialog.select("page", scope="defaults")
    default_paper = dialog.pages["page"]
    default_paper.paper.setCurrentText("B5")
    default_paper.direction.setCurrentIndex(1)
    dialog.save_button.click()
    assert GlobalDefaultsStore().for_new_document()[0].flow.template.width_mm == 250
    assert window.flow.template.height_mm == 148

open_settings(apply_scopes)
assert window.style.em_mm == 7 and window.save_project()
assert load_package(report).style.em_mm == 7
assert dict(load_package(report).flow.table_overrides) == {table.node_id: override}
window.load_project_path(report)
wait_layout()
assert window.flow.template.height_mm == 148 and window.style.em_mm == 7
window.new_document()
wait_layout()
assert (window.flow.template.width_mm, window.flow.template.height_mm) == (250, 176)
assert window.style.em_mm == 9
window.load_project_path(older)
wait_layout()
assert window.style == base.style and window.flow.template.height_mm == 297
window.dirty = False
shell.close()
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
