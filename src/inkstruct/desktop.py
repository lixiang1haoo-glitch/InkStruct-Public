from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from .generation_workflow import METHODS, GenerationWorkflow, identity, resources


def _qt():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError as error:
        raise RuntimeError("desktop application requires inkstruct[desktop]") from error
    return QtCore, QtWidgets


def main(argv=None, *, create_only=False, workspace=None, database=None):
    QtCore, QtWidgets = _qt()
    root = Path(workspace) if workspace else resources()
    db = Path(database) if database else resources() / "artifacts/structures/characters.sqlite3"
    service = GenerationWorkflow(root, db)
    arguments = list(argv or sys.argv)

    class Signals(QtCore.QObject):
        finished = QtCore.Signal(object)
        failed = QtCore.Signal(str)

    class Worker(QtCore.QRunnable):
        def __init__(self, function):
            super().__init__()
            self.function, self.signals = function, Signals()

        @QtCore.Slot()
        def run(self):
            try:
                self.signals.finished.emit(self.function())
            except Exception as error:  # noqa: BLE001 - worker boundary, traceback only in diagnostic file
                folder = root / "generation" / "errors"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / (identity() + ".log")
                path.write_text(traceback.format_exc(), encoding='utf-8')
                message = str(error).splitlines()[0] or type(error).__name__
                self.signals.failed.emit(message + "\n诊断记录：" + str(path))

    class WorkflowWidget(QtWidgets.QWidget):
        generation_progress = QtCore.Signal(object)
        publish_requested = QtCore.Signal()

        def __init__(self):
            super().__init__()
            self.pool = QtCore.QThreadPool.globalInstance()
            self.cancel_event = threading.Event()
            self.busy = False
            self.last_generated_run = None
            self.last_generated_writer = None
            self.target_manifest = None
            self.current_document_provider = None
            layout = QtWidgets.QVBoxLayout(self)
            title = QtWidgets.QLabel("生成字形")
            title.setStyleSheet("font-size: 20px; font-weight: 600")
            layout.addWidget(title)
            source_group = QtWidgets.QGroupBox("1 · 准备作者样本")
            source_layout = QtWidgets.QVBoxLayout(source_group)
            form = QtWidgets.QFormLayout()
            source_layout.addLayout(form)
            layout.addWidget(source_group)
            self.writer = QtWidgets.QLineEdit("user_001")
            self.writer.setObjectName("writer")
            self.samples = QtWidgets.QLineEdit()
            self.samples.setObjectName("sample_directory")
            self.samples.setPlaceholderText("选择该作者的汉字采集目录")
            self.browse = QtWidgets.QPushButton("选择…")
            self.browse.clicked.connect(self.choose_samples)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.samples)
            row.addWidget(self.browse)
            self.method = QtWidgets.QComboBox()
            self.method.setObjectName("generation_method")
            for key, label in METHODS.items():
                self.method.addItem(label, key)
            info = QtWidgets.QLabel("ⓘ")
            info.setToolTip("v6.2 exp：增加竖弯钩、止部关键笔语义准入与不兼容来源重试，保留真实原笔迹。\n"
                "v6.1 exp：参考修正、完整部件、受限关键笔替换及作者单笔回退；保留完整来源轨迹与缺口。\n"
                "沿用跨字生成规则，排除同字供体；未通过来源筛选处保留参考替代并警告。\n"
                "v4 adaptive：固定自适应融合配置；没有可靠逐笔来源记录时按来源未知提示。\n"
                "建档会自动准备所选方法需要的档案。更换方法后若未建档，请先建档。\n"
                "每次操作创建新批次；采集目录有新增内容时请重新导入。")
            method_row = QtWidgets.QHBoxLayout()
            method_row.addWidget(self.method, 1)
            method_row.addWidget(info)
            self.text = QtWidgets.QLineEdit("中国书法")
            self.text.setObjectName("generation_text")
            self.text.setMaxLength(4_000_000)  # imported lists must never be silently truncated by QLineEdit
            self.generate_all = QtWidgets.QCheckBox("生成结构库全部汉字")
            self.generate_all.setToolTip("按本版结构库生成全部汉字。可能耗时较长；可取消，已完成字形仍保留。再次生成会创建新批次。")
            form.addRow("作者", self.writer)
            form.addRow("样本目录", row)
            form.addRow("生成方式", method_row)
            prepare_actions = QtWidgets.QHBoxLayout()
            source_layout.addLayout(prepare_actions)
            generation_group = QtWidgets.QGroupBox("2 · 生成汉字")
            generation_layout = QtWidgets.QVBoxLayout(generation_group)
            generation_form = QtWidgets.QFormLayout()
            generation_form.addRow("生成内容", self.text)
            target_actions = QtWidgets.QHBoxLayout()
            self.target_builtin_button = QtWidgets.QPushButton('内置简繁字表…')
            self.target_builtin_button.clicked.connect(self.choose_builtin_targets)
            self.target_file_button = QtWidgets.QPushButton('导入字表…')
            self.target_document_button = QtWidgets.QPushButton('从文档提取汉字…')
            self.target_current_button = QtWidgets.QPushButton('从当前排版提取')
            self.target_current_button.setEnabled(False)
            self.target_file_button.clicked.connect(self.choose_target_file)
            self.target_document_button.clicked.connect(self.choose_target_document)
            self.target_current_button.clicked.connect(self.choose_current_document)
            for button in (self.target_builtin_button, self.target_file_button, self.target_document_button, self.target_current_button):
                target_actions.addWidget(button)
            generation_form.addRow('', target_actions)
            generation_form.addRow("", self.generate_all)
            self.parallelism = QtWidgets.QComboBox()
            self.parallelism.setObjectName('generation_parallelism')
            for label, key in [('自动（小任务串行）', 'auto'), ('串行', 1), ('2 进程', 2), ('4 进程', 4)]:
                self.parallelism.addItem(label, key)
            self.parallelism.setToolTip('按汉字分配任务，每个进程复用完整档案。并发受 CPU 和可用内存限制；进程不可用时保留完成结果并串行恢复。v4 使用串行。')
            generation_form.addRow('计算方式', self.parallelism)
            self.target_summary = QtWidgets.QLabel('直接输入汉字，或导入 UTF-8 TXT / CSV 字表；保留首次出现顺序。')
            self.target_summary.setWordWrap(True)
            generation_form.addRow('', self.target_summary)
            generation_layout.addLayout(generation_form)
            layout.addWidget(generation_group)
            self.status = QtWidgets.QLabel()
            self.status.setWordWrap(True)
            generation_layout.addWidget(self.status)
            actions = QtWidgets.QHBoxLayout()
            self.buttons = []
            for name, attr, function in [("导入样本", "import_button", self.do_import),
                                         ("建立档案", "profile_button", self.do_profile),
                                         ("开始生成", "generate_button", self.do_generate)]:
                button = QtWidgets.QPushButton(name)
                button.setObjectName(attr)
                button.clicked.connect(function)
                setattr(self, attr, button)
                (actions if attr == "generate_button" else prepare_actions).addWidget(button)
                self.buttons.append(button)
            self.cancel_button = QtWidgets.QPushButton("取消生成")
            self.cancel_button.clicked.connect(self.cancel_generation)
            self.cancel_button.setEnabled(False)
            actions.addWidget(self.cancel_button)
            generation_layout.addLayout(actions)
            result_group = QtWidgets.QGroupBox("3 · 生成结果")
            result_layout = QtWidgets.QHBoxLayout(result_group)
            self.result_summary = QtWidgets.QLabel("尚无生成结果")
            self.result_summary.setWordWrap(True)
            result_layout.addWidget(self.result_summary, 1)
            self.publish_button = QtWidgets.QPushButton("制作字体…")
            self.publish_button.setObjectName("generation_to_font_library")
            self.publish_button.setToolTip("将最近完成的生成批次带入字体库，命名并制作字体包")
            self.publish_button.clicked.connect(self.publish_requested.emit)
            self.publish_button.setVisible(create_only)
            result_layout.addWidget(self.publish_button)
            layout.addWidget(result_group)
            details = QtWidgets.QToolButton()
            details.setText("运行记录")
            details.setCheckable(True)
            details.setArrowType(QtCore.Qt.ArrowType.RightArrow)
            details.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            layout.addWidget(details)
            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.document().setMaximumBlockCount(1000)
            layout.addWidget(self.log, 1)
            self.log.hide()
            details.toggled.connect(self.log.setVisible)
            details.toggled.connect(lambda checked: details.setArrowType(
                QtCore.Qt.ArrowType.DownArrow if checked else QtCore.Qt.ArrowType.RightArrow))
            layout.addStretch()
            self.generation_progress.connect(self.show_generation_progress)
            for field in (self.writer, self.samples, self.text):
                field.textChanged.connect(self.refresh)
            self.method.currentIndexChanged.connect(self.refresh)
            self.generate_all.toggled.connect(self.refresh)
            self.text.textEdited.connect(self.invalidate_targets)
            self.refresh()

        def values(self):
            return self.writer.text().strip(), self.samples.text().strip(), self.method.currentData()

        def refresh(self):
            self.publish_button.setEnabled(bool(self.last_generated_run) and not self.busy)
            ready = service.readiness(*self.values())
            self.status.setText("正在处理，请稍候…" if self.busy else ready["message"])
            for kind in ("import", "profile", "generate"):
                enabled = ready[kind] and not self.busy
                if kind == "generate":
                    enabled = enabled and (self.generate_all.isChecked() or bool(self.text.text().strip()))
                getattr(self, kind + "_button").setEnabled(enabled)
            for widget in (self.writer, self.samples, self.browse, self.method, self.generate_all):
                widget.setEnabled(not self.busy)
            self.text.setEnabled(not self.busy and not self.generate_all.isChecked())
            for widget in (self.target_builtin_button, self.target_file_button, self.target_document_button):
                widget.setEnabled(not self.busy and not self.generate_all.isChecked())
            self.target_current_button.setEnabled(bool(self.current_document_provider) and not self.busy and not self.generate_all.isChecked())
            self.parallelism.setEnabled(not self.busy and self.method.currentData() != 'v4')

        def invalidate_targets(self):
            self.target_manifest = None
            self.target_summary.setText('已编辑为自定义字表；开始前会检查全部目标，不支持字符不会静默跳过。')

        def load_targets(self, function):
            def run():
                from .structures import StructureRepository
                manifest = function(StructureRepository(db).characters())
                return {'message': f"已准备字表：{len(manifest['requested'])} 个去重目标。", 'target_manifest': manifest}
            self.submit(run)

        def choose_target_file(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '导入 UTF-8 自定义字表', '', '字表 (*.txt *.csv)')
            if path:
                def read(supported):
                    from .generation_targets import read_target_file, target_manifest
                    text, origin = read_target_file(path)
                    return target_manifest(text, supported, source=origin)
                self.load_targets(read)

        def choose_builtin_targets(self):
            # Resource/database errors use the same visible diagnostic boundary
            # as other target imports. Do not alter current targets on cancel.
            from .character_sets_ui import CharacterSetsDialog
            from .structures import StructureRepository
            try:
                dialog = CharacterSetsDialog(StructureRepository(db).characters(), self)
                if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                    self.completed({'message': '已确认内置字表及结构库缺口。',
                                    'target_manifest': dialog.result_manifest})
            except Exception as error:
                self.failed(str(error))

        def choose_target_document(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '从文档提取汉字（不改文档）', '', '文档 (*.md *.markdown *.inkdoc)')
            if path:
                from .generation_targets import extract_file
                self.load_targets(lambda supported: extract_file(path, supported))

        def choose_current_document(self):
            if self.current_document_provider:
                # Capture source and immutable flow on the GUI thread before background parsing.
                source, flow, identity = self.current_document_provider()
                from .generation_targets import extract_document
                self.load_targets(lambda supported: extract_document(source, supported, flow=flow, identity=identity))

        def choose_samples(self):
            selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择汉字采集样本目录")
            if selected:
                self.samples.setText(selected)

        def submit(self, function, *, cancellable=False):
            if self.busy:
                return
            self.busy = True
            self.refresh()
            self.cancel_button.setEnabled(cancellable)
            self.worker = Worker(function)
            self.worker.signals.finished.connect(self.completed)
            self.worker.signals.failed.connect(self.failed)
            self.pool.start(self.worker)

        def completed(self, value):
            self.busy = False
            self.log.appendPlainText(value["message"])
            if 'target_manifest' in value:
                manifest = value['target_manifest']
                self.target_manifest = manifest
                self.text.setText(''.join(manifest['requested']))
                unsupported = ('；不支持 ' + str(len(manifest['unsupported'])) + ' 项：' +
                               ' '.join(manifest['unsupported'][:40]) + ('…' if len(manifest['unsupported']) > 40 else '')) if manifest['unsupported'] else ''
                diagnostics = f"；原文档有 {len(manifest['diagnostics'])} 项解析/字段诊断，未修改原文" if manifest['diagnostics'] else ''
                self.target_summary.setText(f"去重目标 {len(manifest['requested'])} 字{unsupported}{diagnostics}。仅改变输出目标，仍使用完整作者供体池。")
                origin = manifest['source']
                if origin.get('kind') == 'builtin-character-sets':
                    missing = origin['unsupported_in_structure_library']
                    self.target_summary.setText('；'.join(e['title'] for e in origin['sets']) +
                        f"。实际目标 {len(manifest['requested'])} 字；已明确排除结构库不支持的 {len(missing)} 字，完整清单随任务保存。供体池保持完整。")
                self.target_summary.setToolTip(str(manifest['source']))
            if "output" in value:
                if value["completed_count"]:
                    self.last_generated_run = value["output"]
                    self.last_generated_writer = value["writer"]
                    self.result_summary.setText(value["message"])
                    self.result_summary.setToolTip("结果目录：" + value["output"])
                else:
                    self.result_summary.setText("本次没有完成的字形。" + (
                        "仍可制作上次成功结果的字体。" if self.last_generated_run else ""))
                self.log.appendPlainText("结果目录：" + value["output"])
                if value.get("status") == "cancelled":
                    self.log.appendPlainText("已取消；已完成字形保留，未完成部分未发布。")
                execution = value.get('execution', {})
                if execution:
                    self.log.appendPlainText(f"计算工作者：{execution['workers']}；目标与来源身份见结果 protocol.json。")
                    if execution.get('fallback'):
                        self.log.appendPlainText('已串行恢复；进程诊断：' + execution['fallback'])
                if value.get("warning_characters"):
                    self.log.appendPlainText("含参考替代：" + "".join(value["warning_characters"]) + "。可继续使用，在字体提示中查看具体缺口。")
                for item in value.get("failed", []):
                    self.log.appendPlainText(f"{item['character']}：{item['reason']}")
            for key in ("report", "profile"):
                if key in value:
                    self.log.appendPlainText("详细记录：" + value[key])
            self.cancel_button.setEnabled(False)
            self.refresh()

        def failed(self, message):
            self.busy = False
            self.log.appendPlainText("操作未完成：" + message)
            self.cancel_button.setEnabled(False)
            self.refresh()
            self.status.setText("操作未完成：" + message.splitlines()[0])

        def show_generation_progress(self, value):
            self.status.setText(f"生成进度：{value['completed_count']}/{value['requested_count']}；失败 {value['failed_count']}；当前 {value['character']}")

        def cancel_generation(self):
            self.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.log.appendPlainText("已请求取消；停止投递任务，保留已校验完成结果。串行计算将在当前字结束后停止。")

        def do_import(self):
            values = self.values()
            self.submit(lambda: service.import_samples(*values))

        def do_profile(self):
            values = self.values()
            self.submit(lambda: service.build_profile(*values))

        def do_generate(self):
            values, text, full = self.values(), self.text.text(), self.generate_all.isChecked()
            workers = self.parallelism.currentData()
            targets = self.target_manifest
            if targets and ''.join(targets['requested']) != text:
                targets = None
            self.cancel_event.clear()
            self.submit(lambda: service.generate(*values, text, all_supported=full,
                workers=workers, targets=targets,
                progress=self.generation_progress.emit, cancelled=self.cancel_event.is_set), cancellable=True)

    class GeneratorWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("InkStruct 墨构 · 字形生成")
            self.resize(900, 620)
            self.setCentralWidget(WorkflowWidget())

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(arguments)
    if create_only:
        return GeneratorWindow()
    app.setStyle("Fusion")
    app.setOrganizationName("InkStruct")
    app.setApplicationName("InkStruct Generator")
    window = GeneratorWindow()
    window.show()
    if "--smoke-test" in arguments:
        QtCore.QTimer.singleShot(300, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
