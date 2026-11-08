from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
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
    from .generation_progress_ui import GenerationProgress

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
            from .generation_variants import DEFAULT_CANDIDATES, MAX_CANDIDATES

            self.pool = QtCore.QThreadPool.globalInstance()
            self.cancel_event = threading.Event()
            self.busy = False
            self.last_generated_run = None
            self.last_generated_writer = None
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
            info.setToolTip("v6.2 exp：增加竖弯钩、止部关键笔语义准入与不兼容来源重试，保留真实原笔迹。\n"
                "作者来源完整的字可按所选上限保留多份真实供体候选，制作字体后按出现位置稳定选样。\n"
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
            form.addRow("样本与档案", self.sample_summary)
            form.addRow("", self.sample_notice)
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
            self.candidate_preferences = QtCore.QSettings("InkStruct", "Generation")
            self.candidate_default = DEFAULT_CANDIDATES
            self.candidate_limit = QtWidgets.QSpinBox()
            self.candidate_limit.setObjectName("generation_candidate_limit")
            self.candidate_limit.setAccessibleName("每字成品上限")
            self.candidate_limit.setRange(1, MAX_CANDIDATES)
            self.candidate_limit.setSuffix(" 份")
            self.candidate_limit.setValue(self.preferred_candidate_limit())
            self.candidate_limit.setToolTip(
                "仅用于 v6.2 exp，数量包含原主字形。实际份数取决于真实来源和完整检查；"
                "增加上限会增加尝试次数、生成时间和包体。"
            )
            generation_form.addRow("每字成品上限", self.candidate_limit)
            self.candidate_hint = QtWidgets.QLabel()
            self.candidate_hint.setWordWrap(True)
            generation_form.addRow("", self.candidate_hint)
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
            for name, attr, function in [("更新样本并建档", "update_button", self.do_update),
                                         ("导入样本", "import_button", self.do_import),
                                         ("建立档案", "profile_button", self.do_profile),
                                         ("开始生成", "generate_button", self.do_generate)]:
                button = QtWidgets.QPushButton(name)
                button.setObjectName(attr)
                if attr in ("generate_button", "update_button"):
                    button.setProperty("inkRole", "primary")
                button.clicked.connect(function)
                setattr(self, attr, button)
                (actions if attr == "generate_button" else prepare_actions).addWidget(button)
                self.buttons.append(button)
            self.cancel_button = QtWidgets.QPushButton("取消生成")
            self.cancel_button.clicked.connect(self.cancel_generation)
            self.cancel_button.setEnabled(False)
            actions.addWidget(self.cancel_button)
            generation_layout.addLayout(actions)
            self.progress_panel = GenerationProgress(self)
            generation_layout.addWidget(self.progress_panel)
            result_group = QtWidgets.QGroupBox("3 · 生成结果")
            result_layout = QtWidgets.QHBoxLayout(result_group)
            self.result_summary = QtWidgets.QLabel("尚无生成结果")
            self.result_summary.setWordWrap(True)
            result_layout.addWidget(self.result_summary, 1)
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
            self.writer.textChanged.connect(self.writer_changed)
            self.samples.textChanged.connect(self.manual_sample_source)
            self.text.textChanged.connect(self.refresh)
            self.method.currentIndexChanged.connect(self.refresh_sample_source)
            self.candidate_limit.valueChanged.connect(self.remember_candidate_limit)
            self.generate_all.toggled.connect(self.refresh)
            self.text.textEdited.connect(self.invalidate_targets)
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
                self.writer.setText(writer)

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
                if status["foreign"]:
                    notices.append("作者归属不符：目录包含 " + "、".join(status["foreign"]))
                if status["changed"]:
                    notices.append("有样本变化尚未纳入当前档案。使用「更新样本并建档」纳入变化。")
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
            if self.method.currentData() == "v62":
                self.candidate_preferences.setValue("candidate_limit", value)
            self.update_candidate_hint()

        def update_candidate_hint(self):
            from .generation_variants import candidate_attempt_limit

            if self.method.currentData() != "v62":
                self.candidate_hint.setText("当前生成方式只保留 1 份主字形；多份成品上限仅用于 v6.2 exp。")
            elif self.candidate_limit.value() == 1:
                self.candidate_hint.setText("数量包含原主字形；选择 1 份时不尝试额外成品。")
            else:
                attempts = candidate_attempt_limit(self.candidate_limit.value())
                self.candidate_hint.setText(
                    f"数量包含原主字形；每字最多 {attempts} 次方案尝试，不足时保留实际合格份数。"
                )

        def refresh(self):
            self.publish_button.setEnabled(bool(self.last_generated_run) and not self.busy)
            ready = service.readiness(*self.values())
            self.refresh_sample_summary()
            checked = self.sample_status and not (self.sample_status.get("foreign") or self.sample_status.get("error"))
            self.update_button.setEnabled(bool(checked and ready["import"] and not self.busy))
            self.status.setText("正在处理，请稍候…" if self.busy else ready["message"])
            for kind in ("import", "profile", "generate"):
                enabled = ready[kind] and not self.busy
                if kind == "import":
                    enabled = enabled and checked
                if kind == "generate":
                    enabled = enabled and (self.generate_all.isChecked() or bool(self.text.text().strip()))
                getattr(self, kind + "_button").setEnabled(bool(enabled))
            for widget in (self.writer, self.samples, self.browse, self.follow_samples, self.method, self.generate_all):
                widget.setEnabled(not self.busy)
            self.text.setEnabled(not self.busy and not self.generate_all.isChecked())
            for widget in (self.target_builtin_button, self.target_file_button, self.target_document_button):
                widget.setEnabled(not self.busy and not self.generate_all.isChecked())
            self.target_current_button.setEnabled(bool(self.current_document_provider) and not self.busy and not self.generate_all.isChecked())
            self.parallelism.setEnabled(not self.busy and self.method.currentData() != 'v4')
            multiple = self.method.currentData() == "v62"
            with QtCore.QSignalBlocker(self.candidate_limit):
                self.candidate_limit.setValue(self.preferred_candidate_limit() if multiple else 1)
            self.candidate_limit.setEnabled(multiple and not self.busy)
            self.update_candidate_hint()

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
            if "output" in value:
                self.progress_panel.finish(result=value)
                self.status.show()
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
            if "report" in value or "profile" in value:
                self.sample_status = None
            self.resume_sample_status()

        def failed(self, message):
            self.busy = False
            self.progress_panel.finish()
            self.status.show()
            self.log.appendPlainText("操作未完成：" + message)
            self.cancel_button.setEnabled(False)
            self.resume_sample_status()
            self.status.setText("操作未完成：" + message.splitlines()[0])

        def show_generation_progress(self, value):
            self.progress_panel.record(value)

        def cancel_generation(self):
            self.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.progress_panel.cancelling()
            self.log.appendPlainText("已请求取消；停止投递任务，保留已校验完成结果。串行计算将在当前字结束后停止。")

        def do_import(self):
            values = self.values()
            self.submit(lambda: service.import_samples(*values))

        def do_update(self):
            values = self.values()
            self.submit(lambda: service.update_samples(*values))

        def do_profile(self):
            values = self.values()
            self.submit(lambda: service.build_profile(*values))

        def do_generate(self):
            if self.busy:
                return
            values, text, full = self.values(), self.text.text(), self.generate_all.isChecked()
            workers = self.parallelism.currentData()
            candidate_limit = self.candidate_limit.value() if values[2] == "v62" else 1
            targets = self.target_manifest
            if targets and ''.join(targets['requested']) != text:
                targets = None
            self.cancel_event.clear()
            self.progress_panel.start()
            self.status.hide()
            self.submit(lambda: service.generate(*values, text, all_supported=full,
                workers=workers, targets=targets, candidate_limit=candidate_limit,
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
