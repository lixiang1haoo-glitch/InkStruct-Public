from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .cli import PROJECT_ROOT
from .stroke_reference import create_stroke_reference_widget_class
from .structures import StructureRepository


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
    candidates = [
        PROJECT_ROOT / "legacy" / "data_collection",
        PROJECT_ROOT.parent / "data_collection",
    ]
    for candidate in candidates:
        if (candidate / "handwriting_collector" / "ui.py").is_file():
            return candidate
    searched = "\n".join(str(candidate) for candidate in candidates)
    raise RuntimeError(f"找不到采集器内核，已检查：\n{searched}")


def main(argv: list[str] | None = None) -> int:
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
        PROJECT_ROOT / "artifacts" / "structures" / "characters.sqlite3"
    )
    StrokeReferenceWidget = create_stroke_reference_widget_class(QtCore, QtGui, QtWidgets)

    def reference_for(character: str):
        try:
            return [stroke.median for stroke in repository.get(character).strokes]
        except KeyError:
            return None

    class ValidatedSingleCharacterWidget(collector_ui.SingleCharacterWidget):
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
            self.save_button.setEnabled(bool(check.matches and has_trajectory))

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
            super().save_current()

    class CollectorWindow(collector_ui.MainWindow):
        def __init__(self):
            super().__init__()
            previous = self.single_widget
            index = self.tabs.indexOf(previous)
            self.tabs.removeTab(index)
            previous.setParent(None)
            previous.deleteLater()
            self.single_widget = ValidatedSingleCharacterWidget(self.ensure_output_root)
            self.tabs.insertTab(index, self.single_widget, "单字任务采集")
            self.tabs.setCurrentIndex(index)
            self.apply_ui_settings(self.ui_settings)
            self.setWindowTitle("InkStruct 墨构 · 轨迹采集器")
            if self.output_root is not None:
                QtCore.QTimer.singleShot(0, lambda: self.single_widget.resume_task(quiet=True))

        def choose_output_root(self) -> Path | None:
            if not smoke_test:
                return super().choose_output_root()
            self.output_root = PROJECT_ROOT / "artifacts" / "collector_smoke"
            self.output_root.mkdir(parents=True, exist_ok=True)
            self._update_status()
            return self.output_root

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(arguments)
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
