from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from handwriting_collector import ui as collector_ui
from handwriting_collector.models import Trajectory, TrajectoryPoint
from handwriting_collector.storage import SampleStorage
from handwriting_collector.tasks import CollectionTask
from PySide6 import QtCore, QtGui, QtWidgets

from inkstruct.capture_boundary import install_capture_boundary_guard
from inkstruct.stroke_reference import (
    create_stroke_reference_widget_class,
    load_reference_bundle,
)
from inkstruct.symbol_capture import CHARACTERS, SymbolStorage
from inkstruct.symbol_capture_ui import install_symbol_tab


def resource_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / name


@dataclass(frozen=True, slots=True)
class StrokeCountCheck:
    actual: int
    expected: int | None
    matches: bool
    message: str


STROKE_REFERENCES = load_reference_bundle(resource_path("stroke_references.json.gz"))
STROKE_COUNTS = {character: len(strokes) for character, strokes in STROKE_REFERENCES.items()}
StrokeReferenceWidget = create_stroke_reference_widget_class(QtCore, QtGui, QtWidgets)


def check_stroke_count(character: str, actual: int) -> StrokeCountCheck:
    expected = STROKE_COUNTS.get(character)
    if expected is None:
        return StrokeCountCheck(
            actual,
            None,
            False,
            f"“{character}”不在当前标准结构库中，不能判定笔画数量",
        )
    matches = actual == expected
    if matches:
        message = f"笔画数量：{actual} / {expected}（正确）"
    else:
        delta = expected - actual
        action = f"还需 {delta} 笔" if delta > 0 else f"多出 {-delta} 笔"
        message = f"笔画数量：{actual} / {expected}（{action}）"
    return StrokeCountCheck(actual, expected, matches, message)


class ValidatedSingleCharacterWidget(collector_ui.SingleCharacterWidget):
    def __init__(self, output_root_provider, parent=None):
        self.stroke_count_label = None
        self.stroke_reference = None
        super().__init__(output_root_provider, parent)
        self.stroke_reference = StrokeReferenceWidget(STROKE_REFERENCES.get, self)
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
        return check_stroke_count(item.character, len(self.canvas.trajectory.strokes))

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
        if self.boundary_guard.allow_save():
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
        line_index = self.tabs.indexOf(self.line_widget)
        if line_index >= 0:
            self.tabs.removeTab(line_index)
        self.tabs.setCurrentWidget(self.single_widget)
        install_symbol_tab(self, collector_ui, QtCore, QtGui, QtWidgets)
        self.apply_ui_settings(self.ui_settings)
        self.setWindowTitle("InkStruct 墨构 · 轻量轨迹采集器")
        if self.output_root is not None:
            QtCore.QTimer.singleShot(0, lambda: self.single_widget.resume_task(quiet=True))


def run_self_test(output_path: Path) -> int:
    report: dict[str, object]
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = CollectionTask.create(
                "portable-self-test", "builtin", "selftest", [("十", 1, 0)]
            )
            item = task.current_item()
            if item is None:
                raise RuntimeError("self-test task has no current item")
            trajectory = Trajectory()
            trajectory.start_stroke(TrajectoryPoint(20, 50, 0.5, 0))
            trajectory.append_point(TrajectoryPoint(80, 50, 0.5, 10))
            trajectory.start_stroke(TrajectoryPoint(50, 20, 0.5, 20))
            trajectory.append_point(TrajectoryPoint(50, 80, 0.5, 30))
            _, sample_path = SampleStorage(root).save_single(
                writer_id="selftest",
                task=task,
                item=item,
                trajectory=trajectory,
                canvas_width=100,
                canvas_height=100,
                device_pixel_ratio=1.0,
            )
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
            symbol_task = CollectionTask.create(
                "symbol-self-test", "builtin:symbols", "selftest", [("α", 5, 0)]
            )
            symbol_storage = SymbolStorage(root / "symbol_collection")
            _, symbol_path = symbol_storage.save_single(
                writer_id="selftest", task=symbol_task, item=symbol_task.current_item(),
                trajectory=trajectory, canvas_width=560, canvas_height=320,
                device_pixel_ratio=1.0,
            )
            symbol_sample = json.loads(symbol_path.read_text(encoding="utf-8"))
            recovered = symbol_storage.reconcile_task(symbol_task)
            checks = {
                "symbol_character_count": len(CHARACTERS),
                "symbol_schema": symbol_sample["schema_version"],
                "symbol_variable_strokes": symbol_sample["stats"]["stroke_count"] == 2,
                "symbol_recovered": recovered == 1,
                "mapping_character_count": len(STROKE_COUNTS),
                "reference_character_count": len(STROKE_REFERENCES),
                "ten_expected_strokes": STROKE_COUNTS.get("十"),
                "ten_reference_strokes": len(STROKE_REFERENCES.get("十", [])),
                "chicken_expected_strokes": STROKE_COUNTS.get("鸡"),
                "sample_schema": sample.get("schema_version"),
                "sample_stroke_count": len(sample.get("strokes", [])),
                "legacy_npy_created": any(root.rglob("*.npy")),
            }
            passed = checks == {
                "symbol_character_count": 188,
                "symbol_schema": "inkstruct_symbol_sample_v1",
                "symbol_variable_strokes": True,
                "symbol_recovered": True,
                "mapping_character_count": 9574,
                "reference_character_count": 9574,
                "ten_expected_strokes": 2,
                "ten_reference_strokes": 2,
                "chicken_expected_strokes": 7,
                "sample_schema": "handwriting_single_v1",
                "sample_stroke_count": 2,
                "legacy_npy_created": True,
            }
            report = {"status": "passed" if passed else "failed", "checks": checks}
    except Exception as error:  # noqa: BLE001 - packaged self-test must report startup failures
        report = {"status": "error", "error": repr(error)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    self_test = next(
        (argument.split("=", 1)[1] for argument in sys.argv if argument.startswith("--self-test=")),
        None,
    )
    if self_test:
        return run_self_test(Path(self_test))
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    application.setOrganizationName("InkStruct")
    application.setApplicationName("InkStruct Portable Collector")
    application.setStyle("Fusion")
    application.setPalette(collector_ui.light_palette())
    application.setStyleSheet(collector_ui.APP_STYLE)
    window = CollectorWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        window.single_widget.stroke_reference.set_state("永", 0, False)

        def finish_smoke_test() -> None:
            screenshot = next(
                (
                    argument.split("=", 1)[1]
                    for argument in sys.argv
                    if argument.startswith("--smoke-screenshot=")
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
