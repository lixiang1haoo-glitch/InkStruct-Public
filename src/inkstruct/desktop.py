from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path

from .generation_workflow import METHODS, MULTI_CANDIDATE_METHODS, GenerationWorkflow, identity, resources


def _qt():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError as error:
        raise RuntimeError("desktop application requires inkstruct[desktop]") from error
    return QtCore, QtWidgets


def main(argv=None, *, create_only=False, workspace=None, database=None):
    QtCore, QtWidgets = _qt()
    from .generation_progress_ui import GenerationProgress
    from .theme import set_tone
    from .ui_behavior import AdaptiveActions, compact_field

    if find_spec("handwriting_collector") is None:
        from .collector import _collector_source

        try:
            source = _collector_source()
        except RuntimeError:
            pass  # The editable author picker still accepts an external ID.
        else:
            sys.path.insert(0, str(source))

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
        generation_preparation = QtCore.Signal(str, str)
        publish_requested = QtCore.Signal()

        def __init__(self):
            super().__init__()
            from .generation_variants import DEFAULT_CANDIDATES, MAX_CANDIDATES

            self.pool = QtCore.QThreadPool.globalInstance()
            self.cancel_event = threading.Event()
            self.busy = False
            self.last_generated_run = None
            self.last_generated_writer = None
            self.last_generated_batch = None
            self.generation_active = False
            self.generation_error = ""
            self.generation_stage = ""
            self.target_manifest = None
            self.current_document_provider = None
            self.capture_root_provider = None
            self.manual_samples = False
            self.sample_scan = None
            self.sample_status = None
            self.sample_request = None
            self.sample_revision = 0
            self.pending_capture_writer = None
            layout = QtWidgets.QVBoxLayout(self)
            title = QtWidgets.QLabel("生成字形")
            title.setProperty("inkRole", "title")
            layout.addWidget(title)
            source_group = QtWidgets.QGroupBox("1 · 准备作者样本")
            source_layout = QtWidgets.QVBoxLayout(source_group)
            form = QtWidgets.QFormLayout()
            source_layout.addLayout(form)
            layout.addWidget(source_group)
            from .capture_management import CaptureCatalog
            from .capture_workflow_ui import WriterPicker

            self.writer = WriterPicker(lambda: CaptureCatalog(self.capture_root_provider()
                if self.capture_root_provider else root / "capture"), "demo_writer", allow_external=True)
            self.writer.setObjectName("writer")
            self.samples = QtWidgets.QLineEdit()
            self.samples.setObjectName("sample_directory")
            self.samples.setPlaceholderText("选择该作者的汉字采集目录")
            self.browse = QtWidgets.QPushButton("选择…")
            self.browse.clicked.connect(self.choose_samples)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.samples)
            row.addWidget(self.browse)
            self.follow_samples = QtWidgets.QPushButton("跟随采集目录")
            self.follow_samples.clicked.connect(self.use_capture_samples)
            row.addWidget(self.follow_samples)
            self.sample_summary = QtWidgets.QLabel()
            self.sample_summary.setWordWrap(True)
            self.sample_summary.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            self.sample_summary.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            self.sample_notice = QtWidgets.QLabel()
            self.sample_notice.setWordWrap(True)
            self.sample_notice.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            self.sample_notice.setStyleSheet("font-weight: bold;")
            self.sample_notice.hide()
            self.method = QtWidgets.QComboBox()
            self.method.setObjectName("generation_method")
            for key, label in METHODS.items():
                self.method.addItem(label, key)
            info = QtWidgets.QLabel("ⓘ")
            info.setToolTip("v6.3 exp：在 v6.2 的分笔规则上增加连笔供体。\n"
                "v6.2 exp：增加竖弯钩、止部关键笔语义准入与不兼容来源重试，保留真实原笔迹。\n"
                "作者来源完整的字可按所选上限保留多份真实供体候选，制作字体后按出现位置稳定选样。\n"
                "v6.1 exp：参考修正、完整部件、受限关键笔替换及作者单笔回退；保留完整来源轨迹与缺口。\n"
                "沿用跨字生成规则，排除同字供体；未通过来源筛选处保留参考替代并警告。\n"
                "v4 adaptive：固定自适应融合配置；没有可靠逐笔来源记录时按来源未知提示。\n"
                "开始生成时自动检查样本，并为所选方法准备档案。每次生成创建新批次。")
            method_row = QtWidgets.QHBoxLayout()
            method_row.addWidget(compact_field(self.method))
            method_row.addWidget(info)
            method_row.addStretch()
            form.addRow("作者", compact_field(self.writer, maximum=340))
            form.addRow("样本目录", row)
            form.addRow("样本与档案", self.sample_summary)
            form.addRow("", self.sample_notice)
            form.addRow("生成方式", method_row)
            connected_hint = QtWidgets.QLabel("当前仅 v6.3 支持连笔。请在采集页开启「允许汉字连笔」。")
            connected_hint.setWordWrap(True)
            form.addRow("", connected_hint)
            self.same_character = QtWidgets.QCheckBox("允许回放同字的完整连笔样本")
            self.same_character.setObjectName("sameCharacterConnected")
            self.same_character.setToolTip("仅限已通过整字校验的同作者连笔样本。默认使用跨字部件复用。")
            form.addRow("", self.same_character)
            generation_group = QtWidgets.QGroupBox("2 · 生成汉字")
            generation_layout = QtWidgets.QVBoxLayout(generation_group)
            generation_form = QtWidgets.QFormLayout()
            target_area = QtWidgets.QWidget()
            target_layout = QtWidgets.QVBoxLayout(target_area)
            target_layout.setContentsMargins(0, 0, 0, 0)
            target_layout.setSpacing(6)
            target_layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
            self.target_builtin_button = QtWidgets.QPushButton('内置字表…')
            self.target_builtin_button.clicked.connect(self.choose_builtin_targets)
            self.target_file_button = QtWidgets.QPushButton('导入字表…')
            self.target_document_button = QtWidgets.QPushButton('从文档提取汉字…')
            self.target_current_button = QtWidgets.QPushButton('从当前排版提取')
            self.target_current_button.setEnabled(False)
            self.target_file_button.clicked.connect(self.choose_target_file)
            self.target_document_button.clicked.connect(self.choose_target_document)
            self.target_current_button.clicked.connect(self.choose_current_document)
            self.target_actions = AdaptiveActions((self.target_builtin_button, self.target_file_button,
                                                   self.target_document_button, self.target_current_button))
            target_layout.addWidget(self.target_actions)
            self.target_summary = QtWidgets.QLabel('尚未选择生成内容。自定义字表可导入 UTF-8 TXT 或 CSV。')
            self.target_summary.setWordWrap(True)
            self.target_summary.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            summary_row = QtWidgets.QHBoxLayout()
            summary_row.addWidget(self.target_summary, 1)
            self.target_details_button = QtWidgets.QPushButton("查看清单…")
            self.target_details_button.clicked.connect(self.show_target_details)
            summary_row.addWidget(self.target_details_button)
            target_layout.addLayout(summary_row)
            target_label = QtWidgets.QLabel('生成内容')
            target_label.setBuddy(self.target_builtin_button)
            target_container = QtWidgets.QWidget()
            target_row = QtWidgets.QHBoxLayout(target_container)
            target_row.setContentsMargins(0, 0, 0, 0)
            target_row.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
            target_row.addWidget(target_label, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            target_row.addWidget(target_area, 1)
            generation_layout.addWidget(target_container)
            self.parallelism = QtWidgets.QComboBox()
            self.parallelism.setObjectName('generation_parallelism')
            for label, key in [('自动（小任务串行）', 'auto'), ('串行', 1), ('2 进程', 2), ('4 进程', 4)]:
                self.parallelism.addItem(label, key)
            self.parallelism.setToolTip('按汉字分配任务，每个进程复用完整档案。并发受 CPU 和可用内存限制；进程不可用时保留完成结果并串行恢复。v4 使用串行。')
            generation_form.addRow('计算方式', compact_field(self.parallelism))
            self.candidate_preferences = QtCore.QSettings("InkStruct", "Generation")
            self.candidate_default = DEFAULT_CANDIDATES
            self.candidate_limit = QtWidgets.QSpinBox()
            self.candidate_limit.setObjectName("generation_candidate_limit")
            self.candidate_limit.setAccessibleName("每字成品上限")
            self.candidate_limit.setRange(1, MAX_CANDIDATES)
            self.candidate_limit.setSuffix(" 份")
            self.candidate_limit.setValue(self.preferred_candidate_limit())
            self.candidate_limit.setToolTip(
                "v6.2 和 v6.3 支持多候选。实际份数取决于真实来源和完整检查；"
                "增加上限会增加尝试次数、生成时间和包体。"
            )
            generation_form.addRow("每字成品上限", compact_field(self.candidate_limit))
            target_label.setMinimumWidth(generation_form.labelForField(self.candidate_limit).sizeHint().width())
            self.candidate_hint = QtWidgets.QLabel()
            self.candidate_hint.setWordWrap(True)
            generation_form.addRow("", self.candidate_hint)
            generation_layout.addLayout(generation_form)
            layout.addWidget(generation_group)
            self.status = QtWidgets.QLabel()
            self.status.setWordWrap(True)
            self.status.setProperty("inkRole", "status")
            generation_layout.addWidget(self.status)
            actions = QtWidgets.QHBoxLayout()
            self.generate_button = QtWidgets.QPushButton("开始生成")
            self.generate_button.setObjectName("generate_button")
            self.generate_button.setProperty("inkRole", "primary")
            self.generate_button.clicked.connect(self.do_generate)
            actions.addWidget(self.generate_button)
            self.cancel_button = QtWidgets.QPushButton("取消生成")
            self.cancel_button.clicked.connect(self.cancel_generation)
            self.cancel_button.setEnabled(False)
            actions.addWidget(self.cancel_button)
            actions.addStretch()
            generation_layout.addLayout(actions)
            self.progress_panel = GenerationProgress(self)
            generation_layout.addWidget(self.progress_panel)
            result_group = QtWidgets.QGroupBox("3 · 生成结果")
            result_layout = QtWidgets.QHBoxLayout(result_group)
            self.result_summary = QtWidgets.QLabel("尚无生成结果")
            self.result_summary.setWordWrap(True)
            summary_layout = QtWidgets.QVBoxLayout()
            summary_layout.addWidget(self.result_summary)
            self.publish_batch_summary = QtWidgets.QLabel()
            self.publish_batch_summary.setWordWrap(True)
            self.publish_batch_summary.hide()
            summary_layout.addWidget(self.publish_batch_summary)
            result_layout.addLayout(summary_layout, 1)
            self.publish_button = QtWidgets.QPushButton("制作字体…")
            self.publish_button.setObjectName("generation_to_font_library")
            self.publish_button.setProperty("inkRole", "primary")
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
            self.generation_preparation.connect(self.show_generation_preparation)
            self.writer.textChanged.connect(self.writer_changed)
            self.samples.textChanged.connect(self.manual_sample_source)
            self.method.currentIndexChanged.connect(self.refresh_sample_source)
            self.candidate_limit.valueChanged.connect(self.remember_candidate_limit)
            self.sample_timer = QtCore.QTimer(self, interval=3500)
            self.sample_timer.timeout.connect(self.poll_samples)
            self.sample_timer.start()
            self.refresh()

        def use_capture_samples(self):
            self.manual_samples = False
            self.refresh_sample_source()

        def manual_sample_source(self):
            self.manual_samples = bool(self.samples.text().strip())
            self.refresh_sample_source()

        def capture_writer_chosen(self, writer):
            if self.busy:
                self.pending_capture_writer = writer
            else:
                self.writer.reload(writer)
                self.writer_changed()

        def writer_changed(self):
            if self.manual_samples and self.capture_root_provider and not Path(self.samples.text().strip()).is_dir():
                self.manual_samples = False
            self.refresh_sample_source()

        def refresh_sample_source(self, *_):
            from .capture_management import valid_writer

            if not self.manual_samples and self.capture_root_provider:
                writer = self.writer.text().strip()
                target = Path(self.capture_root_provider()) / "samples" / writer
                with QtCore.QSignalBlocker(self.samples):
                    self.samples.setText(str(target.resolve()) if valid_writer(writer) else "")
            values = self.values()
            if values != self.sample_request:
                self.sample_request = values
                self.sample_status = None
                self.sample_revision += 1
                self.generation_error = ""
            self.refresh()
            self.scan_sample_source()

        def poll_samples(self):
            if self.isVisible() and not self.busy:
                self.refresh_sample_source()

        def showEvent(self, event):
            super().showEvent(event)
            self.refresh_sample_source()

        def scan_sample_source(self):
            if self.sample_scan or self.busy or not self.sample_request:
                return
            writer, source, method = values = self.sample_request
            if not writer or not source or not Path(source).is_dir():
                return
            previous = self.sample_status
            revision = self.sample_revision

            def scan():
                try:
                    return revision, service.sample_status(writer, source, method, previous)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    return revision, {"error": str(error)}

            self.sample_scan = Worker(scan)
            self.sample_scan.signals.finished.connect(self.samples_scanned)
            self.sample_scan.signals.failed.connect(self.sample_scan_failed)
            self.pool.start(self.sample_scan)

        def samples_scanned(self, response):
            self.sample_scan = None
            revision, result = response
            if revision == self.sample_revision and not self.busy:
                self.sample_status = result
                self.refresh()
            elif not self.busy:
                self.scan_sample_source()

        def sample_scan_failed(self, message):
            self.sample_scan = None
            self.log.appendPlainText(message)

        def refresh_sample_summary(self):
            writer, source, _ = self.values()
            origin = "手选目录" if self.manual_samples else "自动跟随采集目录"
            status = self.sample_status or {}
            path = status.get("path") or (str(Path(source).resolve()) if source else "未选择")
            line = f"书写者 {writer or '未选择'} · {origin} · {path}"
            notices = []
            if "error" in status:
                line += "\n核对失败：" + status["error"]
            elif status:
                at = status["imported_at"]
                at = datetime.fromisoformat(at).astimezone().strftime("%Y-%m-%d %H:%M:%S") if at else "尚未导入"
                donors = status["donors"]
                line += f"\n上次导入 {at} · 成功导入 {status['imported']} 份 · 有效供体 {donors if donors is not None else '—'}"
                if status.get("connected"):
                    groups = status["connected"]
                    line += f" · 连笔整字 {groups['whole']} 个、部件 {groups['parts']} 个"
                if status["foreign"]:
                    notices.append("作者归属不符：目录包含 " + "、".join(status["foreign"]))
                if status["changed"]:
                    notices.append("有样本变化尚未纳入当前档案。下次开始生成时会自动更新。")
            elif source:
                line += "\n" + ("正在核对样本归属与导入记录…" if Path(source).is_dir() else "样本目录不存在")
            self.sample_summary.setText(line)
            self.sample_summary.setToolTip("\n".join(status.get("records", ())))
            self.sample_notice.setText("\n".join(notices))
            self.sample_notice.setVisible(bool(notices))

        def resume_sample_status(self):
            writer, self.pending_capture_writer = self.pending_capture_writer, None
            if writer is not None:
                self.writer.setText(writer)
            self.refresh_sample_source()

        def values(self):
            return self.writer.text().strip(), self.samples.text().strip(), self.method.currentData()

        def preferred_candidate_limit(self):
            try:
                value = int(self.candidate_preferences.value("candidate_limit", self.candidate_default))
            except (TypeError, ValueError, OverflowError):
                return self.candidate_default
            if not self.candidate_limit.minimum() <= value <= self.candidate_limit.maximum():
                return self.candidate_default
            return value

        def remember_candidate_limit(self, value):
            if self.method.currentData() in MULTI_CANDIDATE_METHODS:
                self.candidate_preferences.setValue("candidate_limit", value)
            self.update_candidate_hint()

        def update_candidate_hint(self):
            from .generation_variants import candidate_attempt_limit

            method = self.method.currentData()
            if method not in MULTI_CANDIDATE_METHODS:
                self.candidate_hint.setText("当前生成方式只保留 1 份主字形。v6.2 和 v6.3 支持多候选。")
            elif self.candidate_limit.value() == 1:
                self.candidate_hint.setText("每字只保留 1 份。" + ("有合格连笔时优先使用。" if method == "v63" else ""))
            else:
                attempts = candidate_attempt_limit(self.candidate_limit.value())
                self.candidate_hint.setText(
                    f"数量包含原主字形；每字最多 {attempts} 次方案尝试，不足时保留实际合格份数。"
                )

        def refresh(self):
            self.publish_button.setEnabled(bool(self.last_generated_run) and not self.busy)
            ready = service.readiness(*self.values())
            self.refresh_sample_summary()
            foreign = self.sample_status and self.sample_status.get("foreign")
            status = ("请选择书写者。" if not self.writer.text().strip() else
                      "请选择属于当前书写者的样本目录。" if foreign else ready["message"])
            if ready["start"] and self.sample_status and self.sample_status.get("changed") and not foreign:
                status = "开始生成时会先更新样本并建档。"
            self.status.setText("正在处理，请稍候…" if self.busy else self.generation_error or status)
            set_tone(self.status, "danger" if self.generation_error and not self.busy else "")
            targets = self.target_manifest or {}
            self.generate_button.setEnabled(ready["start"] and not foreign and not self.busy
                and bool(targets.get("requested")) and not targets["unsupported"])
            self.target_details_button.setEnabled(bool(targets) and not self.busy)
            for widget in (self.writer, self.samples, self.browse, self.follow_samples, self.method):
                widget.setEnabled(not self.busy)
            for widget in (self.target_builtin_button, self.target_file_button, self.target_document_button):
                widget.setEnabled(not self.busy)
            self.target_actions.setEnabled(not self.busy)
            self.target_current_button.setEnabled(bool(self.current_document_provider) and not self.busy)
            self.parallelism.setEnabled(not self.busy and self.method.currentData() != 'v4')
            self.same_character.setVisible(self.method.currentData() == "v63")
            self.same_character.setEnabled(not self.busy)
            multiple = self.method.currentData() in MULTI_CANDIDATE_METHODS
            with QtCore.QSignalBlocker(self.candidate_limit):
                self.candidate_limit.setValue(self.preferred_candidate_limit() if multiple else 1)
            self.candidate_limit.setEnabled(multiple and not self.busy)
            self.update_candidate_hint()

        def show_target_details(self):
            manifest = self.target_manifest
            if manifest is None:
                return
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("生成目标清单")
            dialog.resize(760, 500)
            layout = QtWidgets.QVBoxLayout(dialog)
            summary = QtWidgets.QLabel(self.target_summary.text())
            summary.setWordWrap(True)
            summary.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            layout.addWidget(summary)
            details = QtWidgets.QPlainTextEdit()
            details.setReadOnly(True)
            origin = manifest["source"]
            missing = origin.get("unsupported_in_structure_library", manifest["unsupported"])
            requested = origin.get("complete_requested", manifest["requested"])
            details.setPlainText("实际目标\n" + "".join(manifest["requested"])
                + ("\n\n结构库不支持\n" + " ".join(f"{c} (U+{ord(c):04X})" if len(c) == 1 else c for c in missing) if missing else "")
                + ("\n\n原字表完整范围\n" + "".join(requested) if requested != manifest["requested"] else ""))
            layout.addWidget(details)
            close = QtWidgets.QPushButton("关闭")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec()

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
            from .capture_management import valid_writer

            value = self.samples.text().strip()
            initial = Path(value) if value and Path(value).is_dir() else None
            if initial is None and self.capture_root_provider:
                capture = Path(self.capture_root_provider())
                samples = capture / "samples"
                writer = self.writer.text().strip()
                if valid_writer(writer) and (samples / writer).is_dir():
                    initial = samples / writer
                else:
                    initial = samples if samples.is_dir() else capture
            selected = QtWidgets.QFileDialog.getExistingDirectory(
                self, "选择汉字采集样本目录", str(initial) if initial else ""
            )
            if selected:
                self.samples.setText(selected)

        def submit(self, function, *, cancellable=False):
            if self.busy:
                return
            self.busy = True
            self.sample_revision += 1
            self.refresh()
            self.cancel_button.setEnabled(cancellable)
            self.worker = Worker(function)
            self.worker.signals.finished.connect(self.completed)
            self.worker.signals.failed.connect(self.failed)
            self.pool.start(self.worker)

        def completed(self, value):
            self.busy = False
            if self.generation_active or "output" in value:
                self.generation_active = False
                self.progress_panel.finish(result=value)
                self.status.show()
                self.sample_status = None
            self.log.appendPlainText(value["message"])
            if 'target_manifest' in value:
                self.generation_error = ""
                manifest = value['target_manifest']
                self.target_manifest = manifest
                origin = manifest["source"]
                kind = origin["kind"]
                identity = origin.get("identity") or {}
                title = {"all-supported": "结构库全部汉字",
                         "custom-file": Path(origin.get("path", "")).name or "导入字表",
                         "document": Path(identity["path"]).name if identity.get("path") else "从当前排版提取"}.get(kind, "所选字表")
                missing = manifest["unsupported"]
                if kind == "builtin-character-sets":
                    title = "、".join(e["title"] for e in origin["sets"])
                    missing = origin["unsupported_in_structure_library"]
                note = ""
                if missing:
                    note = (f" · {len(missing)} 项不受支持，不能生成" if manifest["unsupported"]
                            else f" · 已确认排除 {len(missing)} 项")
                self.target_summary.setText(f"{title} · 目标 {len(manifest['requested'])} 字{note}")
                self.target_summary.setToolTip(str(origin.get("path") or identity.get("path") or ""))
            if "output" in value:
                if value["completed_count"]:
                    self.last_generated_run = value["output"]
                    self.last_generated_writer = value["writer"]
                    self.result_summary.setText(value["message"])
                    self.result_summary.setToolTip("结果目录：" + value["output"])
                    self.publish_button.setText("制作字体…")
                    when = (datetime.fromisoformat(value["started_at"]).astimezone()
                            if "started_at" in value else datetime.now())
                    when = when.strftime("%Y-%m-%d %H:%M")
                    self.last_generated_batch = f"{value['writer']} · {when} · 完成 {value['completed_count']} 字"
                    preview = value.get("completed_preview", "")
                    partial = value["completed_count"] < value["requested_count"]
                    if partial and preview:
                        self.last_generated_batch += f" · 已完成范围 {' '.join(preview)}"
                        if value["completed_count"] > len(preview):
                            self.last_generated_batch += " …"
                    self.publish_batch_summary.setText(self.last_generated_batch)
                    self.publish_batch_summary.show()
                else:
                    self.show_previous_batch("本次没有完成的字形。")
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
            elif value.get("status") == "cancelled":
                self.show_previous_batch(value["message"])
            for key in ("report", "profile"):
                if key in value:
                    self.log.appendPlainText("详细记录：" + value[key])
            self.cancel_button.setEnabled(False)
            if "report" in value or "profile" in value:
                self.sample_status = None
            self.resume_sample_status()

        def failed(self, message):
            self.busy = False
            prefix = "操作未完成"
            if self.generation_active:
                self.generation_active = False
                self.show_previous_batch("本次生成未完成。")
                self.sample_status = None
                prefix = self.generation_stage + "失败"
            self.generation_error = prefix + "：" + message.splitlines()[0]
            self.progress_panel.finish()
            self.status.show()
            self.log.appendPlainText(prefix + "：" + message)
            self.cancel_button.setEnabled(False)
            self.resume_sample_status()

        def show_previous_batch(self, message):
            self.result_summary.setText(message)
            self.result_summary.setToolTip("")
            if self.last_generated_batch:
                self.publish_button.setText("制作上次批次…")
                self.publish_batch_summary.setText("上次批次 · " + self.last_generated_batch)
                self.publish_batch_summary.show()

        def show_generation_progress(self, value):
            self.progress_panel.record(value)

        def show_generation_preparation(self, stage, detail):
            self.generation_stage = stage
            self.progress_panel.preparation(stage, detail)
            self.log.appendPlainText(f"{stage} · {detail}")

        def cancel_generation(self):
            self.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.progress_panel.cancelling()
            self.log.appendPlainText("已请求取消；停止投递任务，保留已校验完成结果。串行计算将在当前字结束后停止。")

        def do_generate(self):
            if self.busy:
                return
            targets = self.target_manifest
            if not targets or not targets["requested"] or targets["unsupported"]:
                return
            values, text = self.values(), "".join(targets["requested"])
            workers = self.parallelism.currentData()
            candidate_limit = self.candidate_limit.value() if values[2] in MULTI_CANDIDATE_METHODS else 1
            same_character = values[2] == "v63" and self.same_character.isChecked()
            self.cancel_event.clear()
            self.generation_active = True
            self.generation_error = ""
            self.generation_stage = "核对目标"
            self.progress_panel.start()
            self.status.hide()
            self.submit(lambda: service.generate(*values, text,
                workers=workers, targets=targets, candidate_limit=candidate_limit, same_character=same_character,
                progress=self.generation_progress.emit, preparation=self.generation_preparation.emit,
                cancelled=self.cancel_event.is_set), cancellable=True)

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
