from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from .capture_boundary import install_capture_boundary_guard
from .capture_controls import canvas_slider_row, capture_display_controls
from .capture_workflow_ui import CaptureLifecycleMixin, install_capture_management
from .cli import PROJECT_ROOT
from .stroke_reference import create_stroke_reference_widget_class
from .structures import StructureRepository
from .symbol_capture_ui import install_symbol_tab


@dataclass(frozen=True, slots=True)
class StrokeCountCheck:
    character: str
    actual: int
    expected: int | None
    matches: bool
    message: str


def check_stroke_count(
    structures: StructureRepository, character: str, actual: int
) -> StrokeCountCheck:
    try:
        expected = len(structures.get(character).strokes)
    except KeyError:
        return StrokeCountCheck(
            character=character,
            actual=actual,
            expected=None,
            matches=False,
            message=f"“{character}”不在当前 InkStruct 结构库中，不能判定标准笔画数",
        )
    matches = actual == expected
    message = (
        f"笔画数量：{actual} / {expected}（正确）"
        if matches
        else f"笔画数量：{actual} / {expected}（需要 {expected - actual:+d} 笔）"
    )
    return StrokeCountCheck(character, actual, expected, matches, message)


def _collector_source() -> Path:
    configured = os.environ.get("INKSTRUCT_COLLECTOR_SOURCE")
    if configured:
        source = Path(configured).expanduser().resolve()
        if not (source / "handwriting_collector" / "ui.py").is_file():
            raise RuntimeError(f"INKSTRUCT_COLLECTOR_SOURCE 中找不到采集器内核：{source}")
        return source
    candidates = [
        Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "collector_kernel",
        PROJECT_ROOT / "artifacts" / "external" / "data_collection",
        PROJECT_ROOT / "legacy" / "data_collection",
        PROJECT_ROOT.parent / "data_collection",
    ]
    for candidate in candidates:
        if (candidate / "handwriting_collector" / "ui.py").is_file():
            return candidate
    searched = "\n".join(str(candidate) for candidate in candidates)
    raise RuntimeError(f"找不到采集器内核，已检查：\n{searched}")


def main(argv: list[str] | None = None, *, create_only=False, workspace=None, database=None,
         connected_capture=False):
    if connected_capture and workspace is None:
        raise ValueError("连笔采集需要独立工作区")
    workspace_root = Path(workspace) if workspace else PROJECT_ROOT
    settings_name = "CaptureV63" if connected_capture else "Capture"
    database_path = Path(database) if database else PROJECT_ROOT / "artifacts" / "structures" / "characters.sqlite3"
    arguments = list(argv or sys.argv)
    smoke_test = "--smoke-test" in arguments
    source = _collector_source()
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    try:
        from handwriting_collector import ui as collector_ui
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError as error:
        raise RuntimeError("采集器需要安装 inkstruct[desktop] 和 data_collection") from error

    repository = StructureRepository(
        database_path
    )
    StrokeReferenceWidget = create_stroke_reference_widget_class(QtCore, QtGui, QtWidgets)

    def reference_for(character: str):
        try:
            return [stroke.median for stroke in repository.get(character).strokes]
        except KeyError:
            return None

    class ValidatedSingleCharacterWidget(CaptureLifecycleMixin, collector_ui.SingleCharacterWidget):
        def __init__(self, output_root_provider, parent=None):
            self.structures = repository
            self.stroke_count_label = None
            self.stroke_reference = None
            super().__init__(output_root_provider, parent)
            self.stroke_reference = StrokeReferenceWidget(reference_for, self)
            canvas_index = self.layout().indexOf(self.canvas)
            status_row = self.layout().itemAt(canvas_index - 1).layout()
            self.display_controls = capture_display_controls(status_row, self.progress_bar)
            footer_actions = self.layout().itemAt(canvas_index + 1).layout()
            self.layout().removeWidget(self.canvas)
            action_column = QtWidgets.QWidget()
            actions = QtWidgets.QVBoxLayout(action_column)
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(8)
            for button, title, shortcut in (
                (self.undo_button, "撤销上一笔", "Ctrl+Z"),
                (self.clear_button, "重写当前字", "Delete"),
                (self.skip_button, "暂时跳过", "Shift+Enter"),
                (self.save_button, "保存并下一个", "Enter"),
            ):
                footer_actions.removeWidget(button)
                button.setText(f"{title}\n{shortcut}")
                button.setAccessibleName(title)
                button.setAccessibleDescription(shortcut)
                button.setMinimumSize(112, 48)
                actions.addWidget(button)
            self.layout().removeItem(footer_actions)
            footer_actions.deleteLater()
            skip_shortcut = QtGui.QShortcut(self)
            skip_shortcut.setKeys([QtGui.QKeySequence("Shift+Return"), QtGui.QKeySequence("Shift+Enter")])
            skip_shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
            skip_shortcut.setAutoRepeat(False)
            skip_shortcut.activated.connect(self.skip_button.click)
            size_row, self.canvas_size_slider, self.canvas_size_label = canvas_slider_row(
                "画布大小", "汉字画布大小", "先保存或重写当前笔迹，再调整画布大小"
            )
            self.display_controls.addLayout(size_row)
            self.canvas_size_slider.setObjectName("hanCanvasSizeSlider")
            self.canvas_size_slider.setRange(15, 30)  # 75%–150%, in 5% steps.
            self.canvas_size_slider.setPageStep(2)
            self.canvas_size_settings = QtCore.QSettings(
                QtCore.QSettings.defaultFormat(), QtCore.QSettings.Scope.UserScope,
                "InkStruct", settings_name,
            )
            try:
                step = int(self.canvas_size_settings.value("han_canvas_height_step", 20))
            except (TypeError, ValueError, OverflowError):
                step = 20
            self.canvas_size_slider.setValue(step if 15 <= step <= 30 else 20)
            self._apply_canvas_height(self.canvas_size_slider.value())
            self.canvas_size_slider.valueChanged.connect(self._change_canvas_height)
            writing_row = QtWidgets.QHBoxLayout()
            writing_row.setSpacing(16)
            writing_row.addWidget(self.stroke_reference)
            writing_row.addWidget(action_column, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            writing_row.addWidget(self.canvas, 1, QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.layout().insertLayout(canvas_index, writing_row, 1)
            self.stroke_count_label = QtWidgets.QLabel("笔画数量：等待书写")
            self.stroke_count_label.setObjectName("mutedLabel")
            self.connected_mode = QtWidgets.QCheckBox("允许汉字连笔（仅 v6.3 生成支持）")
            self.connected_mode.setObjectName("connectedCapture")
            self.connected_mode.setToolTip("开启后按实际落笔和抬笔保存。生成时请选择 v6.3，由建档校验笔位是否完整。")
            self.connected_mode.setChecked(connected_capture)
            self.layout().insertWidget(canvas_index, self.stroke_count_label)
            self.layout().insertWidget(canvas_index + 1, self.connected_mode)
            self.connected_mode.toggled.connect(self.refresh)
            self.canvas.trajectory_changed.connect(self._sync_stroke_reference)
            self.boundary_guard = install_capture_boundary_guard(self, QtCore, QtGui, QtWidgets)
            self.refresh()

        def _apply_canvas_height(self, step):
            self.canvas_height_step = step
            height = 13 * step  # Default 260 logical pixels.
            self.canvas.setFixedHeight(height)
            self.canvas_size_label.setText(f"{step * 5}% · {height} px")

        def _change_canvas_height(self, step):
            if self.canvas.pen_down or self.canvas.trajectory.point_count:
                with QtCore.QSignalBlocker(self.canvas_size_slider):
                    self.canvas_size_slider.setValue(self.canvas_height_step)
                return
            self._apply_canvas_height(step)
            self.canvas_size_settings.setValue("han_canvas_height_step", step)

        def _sync_stroke_reference(self) -> None:
            if self.stroke_reference is None:
                return
            item = self.task.current_item() if self.task else None
            self.stroke_reference.set_state(
                item.character if item else None,
                len(self.canvas.trajectory.strokes),
                self.canvas.pen_down,
            )

        def _stroke_check(self) -> StrokeCountCheck | None:
            item = self.task.current_item() if self.task else None
            if item is None:
                return None
            return check_stroke_count(
                self.structures, item.character, len(self.canvas.trajectory.strokes)
            )

        def refresh(self) -> None:
            super().refresh()
            self._sync_stroke_reference()
            if self.stroke_count_label is None:
                return
            self.canvas_size_slider.setEnabled(
                not self.canvas.pen_down and not self.canvas.trajectory.point_count
            )
            check = self._stroke_check()
            if check is None:
                self.stroke_count_label.setText("笔画数量：等待任务")
                self.stroke_count_label.setStyleSheet("color: #475569;")
                return
            has_trajectory = self.canvas.trajectory.point_count > 0
            connected = self.connected_mode.isChecked() and check.expected is not None
            allowed = check.matches or connected
            if connected:
                self.stroke_count_label.setText(
                    f"实录 {check.actual} 段 · 标准 {check.expected} 笔 · 原样保存，建档时校验"
                )
            else:
                self.stroke_count_label.setText(check.message)
            if allowed and has_trajectory:
                self.stroke_count_label.setStyleSheet("color: #15803D; font-weight: 600;")
            elif has_trajectory:
                self.stroke_count_label.setStyleSheet("color: #B91C1C; font-weight: 600;")
            else:
                self.stroke_count_label.setStyleSheet("color: #475569;")
            self.save_button.setEnabled(bool(allowed and has_trajectory and not self.canvas.pen_down))

        def save_current(self) -> None:
            check = self._stroke_check()
            if check is None or self.canvas.pen_down:
                return
            if not check.matches and (not self.connected_mode.isChecked() or check.expected is None):
                QtWidgets.QMessageBox.warning(
                    self,
                    "笔画数量不一致",
                    check.message + "\n\n请撤销、补写或重写当前字；本次轨迹尚未保存。",
                )
                return
            if self.boundary_guard.allow_save():
                super().save_current()

    class CollectorWindow(collector_ui.MainWindow):
        writer_selected = QtCore.Signal(str)

        def __init__(self):
            super().__init__(auto_resume=False)
            if connected_capture:
                from handwriting_collector.config import UiSettingsStore
                self.settings = QtCore.QSettings("InkStruct", settings_name)
                self.ui_settings_store = UiSettingsStore(workspace_root / "capture-v63-settings.json")
                self.ui_settings, _ = self.ui_settings_store.load()
                self.output_root = workspace_root / "capture-v63"
                self.output_root.mkdir(parents=True, exist_ok=True)
                self._update_status()
            elif create_only:
                # Integrated workspaces do not inherit another collector's output folder.
                self._integrated_initial_choice = self.output_root is None
                self.settings = QtCore.QSettings("InkStruct", "Capture")
                default_workspace = Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation)) / 'InkStruct/workspace'
                key = 'output_root' if workspace_root == default_workspace else 'output_root/' + str(workspace_root.resolve())
                self._capture_root_key = key
                self.output_root = Path(self.settings.value(key, str(workspace_root / "capture"), str))
                self.output_root.mkdir(parents=True, exist_ok=True)
                self._update_status()
            previous = self.single_widget
            index = self.tabs.indexOf(previous)
            self.tabs.removeTab(index)
            previous.setParent(None)
            previous.deleteLater()
            self.single_widget = ValidatedSingleCharacterWidget(self.ensure_output_root)
            self.tabs.insertTab(index, self.single_widget, "汉字样本")
            self.tabs.setCurrentIndex(index)
            install_symbol_tab(self, collector_ui, QtCore, QtGui, QtWidgets)
            if self.output_root is None:
                self.output_root = workspace_root / 'capture'
                self.output_root.mkdir(parents=True, exist_ok=True)
            install_capture_management(self, self.output_root)
            for widget, title in ((self.single_widget, "汉字"), (self.symbol_widget, "标点与扩展")):
                row, slider, widget.stroke_width_label = canvas_slider_row(
                    "笔迹粗细", f"{title}屏幕笔迹粗细", "仅调整屏幕显示，不改变已录笔迹"
                )
                widget.stroke_width_slider = slider
                slider.setRange(75, 400)
                slider.setSingleStep(5)
                slider.setPageStep(25)
                slider.setTracking(False)
                widget.display_controls.addLayout(row)
                slider.valueChanged.connect(lambda value, tab=widget: self.change_stroke_width(tab, value))
            self.apply_ui_settings(self.ui_settings)
            self.setWindowTitle("InkStruct 墨构 · 连笔采集实验" if connected_capture
                                else "InkStruct 墨构 · 轨迹采集器")

        def choose_output_root(self) -> Path | None:
            if connected_capture:
                return self.output_root
            if not smoke_test:
                if hasattr(self, 'symbol_widget'):
                    for widget in (self.single_widget, self.symbol_widget):
                        if not widget._can_switch():
                            return self.output_root
                selected = QtWidgets.QFileDialog.getExistingDirectory(self, '选择采集数据目录', str(self.output_root or workspace_root))
                if not selected:
                    return self.output_root
                if hasattr(self.single_widget, '_capture_catalog'):
                    for widget in (self.single_widget, self.symbol_widget):
                        if widget.task:
                            widget._capture_catalog.set_state(widget._capture_kind, widget.task.task_id, 'paused')
                        widget._close_task()
                self.output_root = Path(selected)
                self.output_root.mkdir(parents=True, exist_ok=True)
                self.settings.setValue(getattr(self, '_capture_root_key', 'output_root'), str(self.output_root))
                if hasattr(self.single_widget, '_capture_catalog'):
                    from .capture_management import CaptureCatalog
                    for widget in (self.single_widget, self.symbol_widget):
                        widget._capture_catalog = CaptureCatalog(self.output_root)
                        widget.writer_picker.catalog = widget._capture_catalog
                        widget.writer_picker.reload()
                        widget.writer_edit.clear()
                    self.capture_selected_writer = ''
                self._update_status()
                return self.output_root
            self.output_root = PROJECT_ROOT / "artifacts" / "collector_smoke"
            self.output_root.mkdir(parents=True, exist_ok=True)
            self._update_status()
            return self.output_root

        def apply_ui_settings(self, settings):
            super().apply_ui_settings(settings)
            if hasattr(self, 'symbol_widget'):
                self.symbol_widget.canvas.set_render_settings(settings.symbol_stroke_scale, settings.grid_scale)
                for tab, scale in ((self.single_widget, settings.stroke_width_scale),
                                   (self.symbol_widget, settings.symbol_stroke_scale)):
                    if hasattr(tab, "stroke_width_slider"):
                        with QtCore.QSignalBlocker(tab.stroke_width_slider):
                            tab.stroke_width_slider.setValue(round(scale * 100))
                        tab.stroke_width_label.setText(f"{round(scale * 100)}%")

        def change_stroke_width(self, widget, value):
            current = self.ui_settings
            if widget is self.single_widget:
                # A legacy shared value becomes the initial value for both tabs.
                selected = replace(current, stroke_width_scale=value / 100,
                                   symbol_stroke_width_scale=current.symbol_stroke_scale)
            else:
                selected = replace(current, symbol_stroke_width_scale=value / 100)
            try:
                self.ui_settings_store.save(selected)
            except (ValueError, OSError) as error:
                self.apply_ui_settings(current)
                QtWidgets.QMessageBox.warning(self, "无法保存笔迹粗细", str(error))
                return
            self.ui_settings = selected
            self.apply_ui_settings(selected)

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(arguments)
    if create_only:
        return CollectorWindow()
    application.setOrganizationName("InkStruct")
    application.setApplicationName("InkStruct Collector V63" if connected_capture else "InkStruct Collector")
    application.setStyle("Fusion")
    application.setPalette(collector_ui.light_palette())
    application.setStyleSheet(collector_ui.APP_STYLE)
    window = CollectorWindow()
    window.show()
    if smoke_test:
        window.single_widget.stroke_reference.set_state("永", 0, False)

        def finish_smoke_test() -> None:
            screenshot = next(
                (
                    value.split("=", 1)[1]
                    for value in arguments
                    if value.startswith("--smoke-screenshot=")
                ),
                None,
            )
            if screenshot:
                target = Path(screenshot)
                target.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(target))
            application.quit()

        QtCore.QTimer.singleShot(300, finish_smoke_test)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
