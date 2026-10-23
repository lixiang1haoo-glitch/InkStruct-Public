from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .capture_boundary import install_capture_boundary_guard
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


def main(argv: list[str] | None = None, *, create_only=False, workspace=None, database=None):
    workspace_root = Path(workspace) if workspace else PROJECT_ROOT
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
            self.layout().removeWidget(self.canvas)
            writing_row = QtWidgets.QHBoxLayout()
            writing_row.setSpacing(16)
            writing_row.addWidget(self.stroke_reference)
            writing_row.addWidget(self.canvas, 1)
            self.layout().insertLayout(canvas_index, writing_row, 1)
            self.stroke_count_label = QtWidgets.QLabel("笔画数量：等待书写")
            self.stroke_count_label.setObjectName("mutedLabel")
            self.layout().insertWidget(2, self.stroke_count_label)
            self.canvas.trajectory_changed.connect(self._sync_stroke_reference)
            self.boundary_guard = install_capture_boundary_guard(self, QtCore, QtGui, QtWidgets)
            self.refresh()

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
            check = self._stroke_check()
            if check is None:
                self.stroke_count_label.setText("笔画数量：等待任务")
                self.stroke_count_label.setStyleSheet("color: #475569;")
                return
            self.stroke_count_label.setText(check.message)
            has_trajectory = self.canvas.trajectory.point_count > 0
            if check.matches and has_trajectory:
                self.stroke_count_label.setStyleSheet("color: #15803D; font-weight: 600;")
            elif has_trajectory:
                self.stroke_count_label.setStyleSheet("color: #B91C1C; font-weight: 600;")
            else:
                self.stroke_count_label.setStyleSheet("color: #475569;")
            self.save_button.setEnabled(bool(check.matches and has_trajectory and not self.canvas.pen_down))

        def save_current(self) -> None:
            check = self._stroke_check()
            if check is None:
                return
            if not check.matches:
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
            if create_only:
                # Integrated workspaces do not inherit another collector's output folder.
                self._integrated_initial_choice = self.output_root is None
                self.settings = QtCore.QSettings("InkStruct", "Capture")
                default_workspace = Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation)) / 'InkStruct/workspace'
                key = 'output_root' if workspace_root == default_workspace else 'output_root/' + str(workspace_root.resolve())
                self._capture_root_key = key
                self.output_root = Path(self.settings.value(key, str(workspace_root / "capture"), str))
                self.output_root.mkdir(parents=True, exist_ok=True)
                self._update_status()
            # Keep legacy line data readable, but retire its page and global keys.
            app = QtWidgets.QApplication.instance()
            app.removeEventFilter(self.line_widget)
            self.tabs.removeTab(self.tabs.indexOf(self.line_widget))
            self.line_widget.hide()
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
            self.apply_ui_settings(self.ui_settings)
            self.setWindowTitle("InkStruct 墨构 · 轨迹采集器")

        def choose_output_root(self) -> Path | None:
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
                self.symbol_widget.canvas.set_render_settings(settings.stroke_width_scale, settings.grid_scale)

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(arguments)
    if create_only:
        return CollectorWindow()
    application.setOrganizationName("InkStruct")
    application.setApplicationName("InkStruct Collector")
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
