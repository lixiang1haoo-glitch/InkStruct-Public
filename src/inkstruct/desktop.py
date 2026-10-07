from __future__ import annotations

import json
import sys
import threading
import traceback
from pathlib import Path

from .cli import PROJECT_ROOT


def _qt():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError as error:
        raise RuntimeError("desktop application requires inkstruct[desktop]") from error
    return QtCore, QtWidgets


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv or sys.argv)
    smoke_test = "--smoke-test" in arguments
    QtCore, QtWidgets = _qt()
    QApplication = QtWidgets.QApplication
    QMainWindow = QtWidgets.QMainWindow
    QWidget = QtWidgets.QWidget
    QObject = QtCore.QObject
    QRunnable = QtCore.QRunnable
    Signal = QtCore.Signal
    Slot = QtCore.Slot

    class WorkerSignals(QObject):
        finished = Signal(object)
        failed = Signal(str)

    class Worker(QRunnable):
        def __init__(self, function):
            super().__init__()
            self.function = function
            self.signals = WorkerSignals()

        @Slot()
        def run(self):
            try:
                self.signals.finished.emit(self.function())
            except Exception:  # noqa: BLE001 - background boundary reports all failures
                self.signals.failed.emit(traceback.format_exc())

    class WorkflowWidget(QWidget):
        generation_progress = Signal(object)

        def __init__(self):
            super().__init__()
            self.pool = QtCore.QThreadPool.globalInstance()
            self.cancel_event = threading.Event()
            self.buttons = []
            layout = QtWidgets.QVBoxLayout(self)
            explanation = QtWidgets.QLabel(
                "风格生成流程：导入已采集的单字 JSON → 建立风格档案 → 生成个性化轨迹"
            )
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
            form = QtWidgets.QFormLayout()
            self.writer = QtWidgets.QLineEdit("user_001")
            self.samples = QtWidgets.QLineEdit()
            self.text = QtWidgets.QLineEdit("中国书法")
            self.generate_all = QtWidgets.QCheckBox("生成全部支持字符（可断点续跑）")
            self.component_mode = QtWidgets.QComboBox()
            self.component_mode.addItem("自适应融合（推荐）", "adaptive")
            self.component_mode.addItem("关闭部件层（A/B 基线）", "off")
            self.component_mode.addItem("仅部件笔画（诊断）", "stroke")
            self.component_mode.addItem("仅部件布局（诊断）", "layout")
            self.component_mode.addItem("完整部件替换（诊断）", "full")
            self.component_strength = QtWidgets.QDoubleSpinBox()
            self.component_strength.setRange(0.0, 1.5)
            self.component_strength.setSingleStep(0.1)
            self.component_strength.setValue(1.0)
            sample_row = QtWidgets.QHBoxLayout()
            sample_row.addWidget(self.samples)
            browse = QtWidgets.QPushButton("选择…")
            browse.clicked.connect(self.choose_samples)
            sample_row.addWidget(browse)
            form.addRow("用户 ID", self.writer)
            form.addRow("单字 JSON 目录", sample_row)
            form.addRow("生成内容", self.text)
            form.addRow("批量模式", self.generate_all)
            form.addRow("部件生成", self.component_mode)
            form.addRow("部件强度", self.component_strength)
            layout.addLayout(form)
            actions = QtWidgets.QHBoxLayout()
            for label, function in [
                ("1. 导入", self.do_import),
                ("2. 建档", self.do_profile),
                ("3. 生成", self.do_generate),
            ]:
                button = QtWidgets.QPushButton(label)
                button.clicked.connect(function)
                self.buttons.append(button)
                actions.addWidget(button)
            layout.addLayout(actions)
            self.cancel_button = QtWidgets.QPushButton("取消当前批量生成")
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self.cancel_generation)
            layout.addWidget(self.cancel_button)
            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            layout.addWidget(self.log, 1)
            self.generation_progress.connect(self.show_generation_progress)

            try:
                import torch

                gpu = (
                    torch.cuda.get_device_name(0)
                    if torch.cuda.is_available()
                    else "不可用；确定性生成可用，训练和神经生成不可用"
                )
            except (ImportError, RuntimeError):
                gpu = "PyTorch 未安装；确定性生成可用，训练和神经生成不可用"
            layout.addWidget(QtWidgets.QLabel(f"CUDA：{gpu}"))

        def choose_samples(self):
            selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择单字 JSON 目录")
            if selected:
                self.samples.setText(selected)

        def submit(self, function, *, cancellable=False):
            for button in self.buttons:
                button.setEnabled(False)
            self.cancel_button.setEnabled(cancellable)
            worker = Worker(function)
            worker.signals.finished.connect(self.completed)
            worker.signals.failed.connect(self.failed)
            self.pool.start(worker)

        def completed(self, value):
            self.log.appendPlainText(json.dumps(value, ensure_ascii=False, indent=2))
            self.cancel_button.setEnabled(False)
            for button in self.buttons:
                button.setEnabled(True)

        def failed(self, message):
            self.log.appendPlainText(message)
            self.cancel_button.setEnabled(False)
            for button in self.buttons:
                button.setEnabled(True)
            QtWidgets.QMessageBox.critical(self, "InkStruct 操作失败", message.splitlines()[-1])

        def cancel_generation(self):
            self.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.log.appendPlainText("已请求取消；当前字符写入完成后停止。")

        def show_generation_progress(self, value):
            self.log.appendPlainText(
                f"生成进度：{value['completed_count']}/{value['requested_count']}，"
                f"失败 {value['failed_count']}，当前 {value['character']}"
            )

        def do_import(self):
            from .samples import import_samples

            source, writer = Path(self.samples.text()), self.writer.text().strip()
            self.submit(
                lambda: import_samples(source, writer, PROJECT_ROOT / "artifacts" / "samples")
            )

        def do_profile(self):
            from .profile import build_profile
            from .structures import StructureRepository

            writer = self.writer.text().strip()

            def work():
                profile, path = build_profile(
                    writer,
                    PROJECT_ROOT / "artifacts" / "samples" / writer / "index.jsonl",
                    StructureRepository(
                        PROJECT_ROOT / "artifacts" / "structures" / "characters.sqlite3"
                    ),
                    PROJECT_ROOT / "profiles",
                )
                return {
                    "profile": str(path),
                    "samples": profile.sample_count,
                    "characters": profile.character_count,
                    "prototypes": len(profile.prototypes),
                    "component_layouts": len(profile.component_layouts),
                    "character_layouts": len(profile.character_layouts),
                    "component_strokes": len(profile.component_strokes),
                    "component_relations": len(profile.component_relations),
                    "component_trajectories": len(profile.component_trajectories),
                    "character_component_trajectories": len(
                        profile.character_component_trajectories
                    ),
                }

            self.submit(work)

        def do_generate(self):
            from .generate import generate_run
            from .structures import StructureRepository

            writer, text = self.writer.text().strip(), self.text.text()
            all_supported = self.generate_all.isChecked()
            component_mode = self.component_mode.currentData()
            component_strength = self.component_strength.value()
            self.cancel_event.clear()

            def work():
                repository = StructureRepository(
                    PROJECT_ROOT / "artifacts" / "structures" / "characters.sqlite3"
                )
                result, output = generate_run(
                    writer,
                    repository.characters() if all_supported else list(text),
                    repository,
                    PROJECT_ROOT / "profiles" / writer / "profile.json",
                    output_root=PROJECT_ROOT / "outputs",
                    component_conditioning=component_mode,
                    component_strength=component_strength,
                    progress_callback=self.generation_progress.emit,
                    cancelled=self.cancel_event.is_set,
                )
                return {**result, "output": str(output)}

            self.submit(work, cancellable=True)

    class GeneratorWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("InkStruct 墨构 · 个性化风格生成器")
            self.resize(1000, 720)
            self.setCentralWidget(WorkflowWidget())

    application = QApplication.instance() or QApplication(arguments)
    application.setStyle("Fusion")
    application.setOrganizationName("InkStruct")
    application.setApplicationName("InkStruct Generator")
    window = GeneratorWindow()
    window.show()
    if smoke_test:
        def finish_smoke_test():
            screenshot = next(
                (value.split("=", 1)[1] for value in arguments
                 if value.startswith("--smoke-screenshot=")), None,
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
