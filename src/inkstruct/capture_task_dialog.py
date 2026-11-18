"""One task creation flow, backed by the existing Han and symbol protocols."""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6 import QtCore, QtGui, QtWidgets

from .capture_management import check_capture_paths, preview_han_file
from .capture_workflow_ui import WriterPicker, new_writer
from .punctuation import capture_character
from .recommended_capture import recording_stages, remaining_entries
from .symbol_capture import parse_symbol_file
from .symbol_reuse import capture_inventory
from .symbol_task_dialog import SymbolTaskDialog
from .symbol_tasks import TASK_GROUPS


class CaptureTaskDialog(QtWidgets.QDialog):
    def __init__(self, widget, *, path=None, stage_key="add68"):
        super().__init__(widget)
        self.owner = widget
        self.catalog = widget._capture_catalog
        self.kind = widget._capture_kind
        self.writer = widget.writer_edit.text().strip()
        self.stages = recording_stages() if self.kind == "han" else {}
        self.stage = self.stages[stage_key] if self.stages else None
        self.entries = ()
        self.source = ""
        self.file_path = Path(path) if path else None
        self.missing = None
        self.symbol_inventory = None
        self.import_selection = None
        self.scan_error = ""
        self.job = None
        self.writers_job = None
        self.created_writers = {}
        self.writers_error = ""
        self.cancel_scan = Event()
        self.disposing = False
        self.show_all = False
        self._painted = False
        self.setObjectName("capture_task_dialog")
        title = "汉字" if self.kind == "han" else "标点与扩展"
        self.setWindowTitle(f"新建{title}采集任务")
        self.resize(780, 720)
        self.setMinimumSize(480, 440)
        root = QtWidgets.QVBoxLayout(self)
        picker = getattr(widget, "writer_picker", None)
        snapshot = dict(picker.writers_snapshot) if picker is not None else {}
        if self.writer:
            snapshot.setdefault(self.writer, {"name": self.writer})
        self.writer_picker = WriterPicker(self.catalog, self.writer, self, snapshot=snapshot)
        self.writer_picker.setAccessibleName("书写者")
        author = QtWidgets.QLabel("书写者")
        author.setBuddy(self.writer_picker)
        author_row = QtWidgets.QHBoxLayout()
        author_row.addWidget(author)
        author_row.addWidget(self.writer_picker, 1)
        self.add_writer_button = QtWidgets.QPushButton("新建书写者…")
        self.add_writer_button.clicked.connect(self.create_writer)
        author_row.addWidget(self.add_writer_button)
        root.addLayout(author_row)

        body = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        self.sources = QtWidgets.QTabWidget()
        self.sources.setObjectName("capture_task_sources")
        first = QtWidgets.QWidget()
        first_layout = QtWidgets.QVBoxLayout(first)
        self.stage_buttons = {}
        if self.kind == "han":
            choices = QtWidgets.QHBoxLayout()
            for key, stage in self.stages.items():
                button = QtWidgets.QPushButton(stage.title)
                button.setObjectName("capture_recommended_" + key)
                button.setCheckable(True)
                button.setMinimumHeight(70)
                button.clicked.connect(lambda _checked=False, value=key: self.select_stage(value))
                self.stage_buttons[key] = button
                choices.addWidget(button, 1)
            first_layout.addLayout(choices)
            first_layout.addWidget(QtWidgets.QLabel("按累计目标补缺，每字 1 份。"))
            self.sources.addTab(first, "推荐字表")
        else:
            self.selection = SymbolTaskDialog(
                self.writer, self, collection_root=self.catalog.task_root("symbol"), embedded=True
            )
            self.selection.setMinimumHeight(220)
            first_layout.addWidget(self.selection)
            self.sources.addTab(first, "按类别选字")
            self.selection.plan_changed.connect(self.update_plan)

        imported = QtWidgets.QWidget()
        import_layout = self.import_layout = QtWidgets.QVBoxLayout(imported)
        file_row = QtWidgets.QHBoxLayout()
        self.file_label = QtWidgets.QLineEdit()
        self.file_label.setReadOnly(True)
        self.file_label.setPlaceholderText("选择 TXT 或 CSV 字表")
        self.file_label.setAccessibleName("字表文件")
        choose = QtWidgets.QPushButton("选择文件…")
        choose.clicked.connect(self.choose_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(choose)
        import_layout.addLayout(file_row)
        form = QtWidgets.QFormLayout()
        self.repeats = QtWidgets.QSpinBox()
        self.repeats.setRange(1, 100)
        self.repeats.setValue(5)
        self.repeats.setSuffix(" 份")
        form.addRow("TXT / CSV 空份数", self.repeats)
        import_layout.addLayout(form)
        self.sources.addTab(imported, "导入 TXT/CSV")
        column.addWidget(self.sources)

        preview_row = QtWidgets.QHBoxLayout()
        self.missing_button = QtWidgets.QPushButton("待录")
        self.all_button = QtWidgets.QPushButton("全部")
        for button, all_entries in ((self.missing_button, False), (self.all_button, True)):
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=all_entries: self.select_preview(value))
            preview_row.addWidget(button)
        preview_row.addStretch()
        column.addLayout(preview_row)
        self.plan_row = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.Direction.LeftToRight)
        self.preview = QtWidgets.QListWidget()
        self.preview.setObjectName("capture_task_preview")
        self.preview.setAccessibleName("任务字表预览")
        self.preview.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.preview.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.preview.setMovement(QtWidgets.QListView.Movement.Static)
        self.preview.setGridSize(QtCore.QSize(62, 62))
        self.preview.setSpacing(4)
        self.preview.setMinimumHeight(150)
        self.plan_row.addWidget(self.preview, 1)
        self.summary = QtWidgets.QGroupBox("任务摘要")
        summary = QtWidgets.QFormLayout(self.summary)
        self.counts = {}
        for key, text in (("target", "目标字符"), ("existing", "已有合格"), ("remaining", "本次待录"),
                          ("copies", "合计录制")):
            value = QtWidgets.QLabel("—")
            value.setObjectName("capture_summary_" + key)
            self.counts[key] = value
            summary.addRow(text, value)
        self.plan_row.addWidget(self.summary)
        column.addLayout(self.plan_row, 1)
        name_row = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(self.default_name())
        self.name.setMaxLength(120)
        name_row.addRow("任务名称", self.name)
        column.addLayout(name_row)
        scroll = QtWidgets.QScrollArea()
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("inkTone", "danger")
        root.addWidget(self.error)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.start = self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.start.setText("创建并开始采集")
        self.start.setProperty("inkRole", "primary")
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.sources.currentChanged.connect(self.source_changed)
        self.repeats.valueChanged.connect(self.read_file)
        self.name.textChanged.connect(self.update_plan)
        self.writer_picker.textChanged.connect(self.writer_changed)
        if self.file_path:
            self.sources.setCurrentIndex(1)
            self.read_file()
        self.scan()
        self.update_plan()

    def default_name(self):
        if self.sources.currentIndex() == 1:
            return self.file_path.stem if self.file_path else "导入字表采集"
        return f"推荐汉字采集 · {len(self.stage.entries)} 字目标" if self.kind == "han" else "标点与扩展采集"

    def source_changed(self):
        if self.kind == "symbol" and self.sources.currentIndex() == 1:
            self.ensure_import_selection()
        if not self.name.isModified():
            self.name.setText(self.default_name())
        self.update_plan()

    def ensure_import_selection(self):
        if self.import_selection is None:
            self.import_selection = SymbolTaskDialog(
                self.writer, self, imported=[], collection_root=self.catalog.task_root("symbol"), embedded=True
            )
            self.import_selection.setMinimumHeight(220)
            self.import_layout.addWidget(self.import_selection)
            if self.symbol_inventory is not None:
                self.import_selection.apply_inventory(self.symbol_inventory)
            self.import_selection.plan_changed.connect(self.update_plan)
        return self.import_selection

    def create_writer(self):
        key = new_writer(self.catalog, self.writer_picker, self)
        if key:
            self.created_writers[key] = self.writer_picker.writers_snapshot[key]
            self.writer_changed(key)

    def writer_changed(self, writer):
        self.writer = writer
        self.cancel_scan.set()
        self.missing = self.symbol_inventory = None
        self.scan_error = ""
        if self.kind == "symbol":
            for selector in (self.selection, self.import_selection):
                if selector is not None:
                    with QtCore.QSignalBlocker(selector):
                        selector.writer.setText(writer)
        self.scan()
        self.update_plan()

    def select_stage(self, key):
        self.stage = self.stages[key]
        if not self.name.isModified():
            self.name.setText(self.default_name())
        self.update_plan()

    def select_preview(self, all_entries):
        self.show_all = all_entries
        self.update_plan()

    def choose_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择采集字表", "", "字表 (*.txt *.csv)")
        if path:
            self.file_path = Path(path)
            self.read_file()
            if not self.name.isModified():
                self.name.setText(self.default_name())

    def read_file(self):
        self.file_entries = None
        self.file_error = ""
        try:
            if self.file_path is None:
                raise ValueError("请选择字表文件")
            self.file_label.setText(str(self.file_path))
            if self.kind == "han":
                self.file_entries, _duplicates = preview_han_file(self.file_path, self.repeats.value())
            else:
                if self.file_path.stat().st_size > 2_000_000:
                    raise ValueError("字表超过 2 MB，请拆分后导入")
                self.file_entries = parse_symbol_file(self.file_path, self.repeats.value())
                if sum(count for _, count, _ in self.file_entries) > 50_000:
                    raise ValueError("任务超过 50,000 份，请拆分字表")
                selector = self.ensure_import_selection()
                with QtCore.QSignalBlocker(selector):
                    selector.set_imported(self.file_entries)
        except (OSError, ValueError, TypeError) as error:
            self.file_error = str(error)
        self.update_plan()

    def scan(self):
        if (not self.writer or self.job is not None or self.disposing or self.scan_error
                or self.missing is not None or self.symbol_inventory is not None
                or (self.kind == "symbol" and not self._painted)):
            return
        from .fonts.ui import Job

        self.cancel_scan = Event()
        catalog, writer, kind = self.catalog, self.writer, self.kind
        stage = self.stages.get("add300")
        structures = self.owner.structures if kind == "han" else None
        cancelled = self.cancel_scan.is_set

        def check_samples(_):
            root = catalog.task_root(kind)
            check_capture_paths(root, writer)
            if kind == "han":
                return remaining_entries(catalog, writer, stage, structures, cancelled)
            return capture_inventory(root, writer, cancelled)

        self.job = Job(check_samples)
        self.job.signals.completed.connect(self.scanned, QtCore.Qt.ConnectionType.QueuedConnection)
        self.job.signals.failed.connect(self.scan_failed, QtCore.Qt.ConnectionType.QueuedConnection)
        QtCore.QThreadPool.globalInstance().start(self.job)

    @QtCore.Slot(object)
    def scanned(self, result):
        if not self.finish_scan():
            return
        if self.kind == "han":
            self.missing = {char for char, _, _ in result}
        else:
            self.symbol_inventory = result
            for selector in (self.selection, self.import_selection):
                if selector is not None:
                    selector.apply_inventory(result)
        self.update_plan()

    @QtCore.Slot(str)
    def scan_failed(self, error):
        if self.finish_scan():
            self.scan_error = "读取样本失败，" + error
            self.update_plan()

    def finish_scan(self):
        self.job = None
        if self.disposing:
            self.deleteLater()
        elif self.cancel_scan.is_set():
            self.scan()
        else:
            return True
        return False

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._painted:
            self._painted = True
            QtCore.QTimer.singleShot(0, self, self.after_first_paint)

    def after_first_paint(self):
        if self.disposing or not self.isVisible():
            return
        from .fonts.ui import Job

        catalog = self.catalog
        self.writers_job = Job(lambda _: catalog.writers())
        self.writers_job.signals.completed.connect(self.writers_loaded, QtCore.Qt.ConnectionType.QueuedConnection)
        self.writers_job.signals.failed.connect(self.writers_failed, QtCore.Qt.ConnectionType.QueuedConnection)
        QtCore.QThreadPool.globalInstance().start(self.writers_job)
        self.scan()

    @QtCore.Slot(object)
    def writers_loaded(self, writers):
        self.writers_job = None
        if self.disposing:
            return
        writers.update(self.created_writers)
        if self.writer:
            known = self.writer_picker.writers_snapshot.get(self.writer, {"name": self.writer})
            writers.setdefault(self.writer, known)
        self.writer_picker.set_snapshot(writers, self.writer)

    @QtCore.Slot(str)
    def writers_failed(self, error):
        self.writers_job = None
        if not self.disposing:
            self.writers_error = "读取书写者失败，" + error
            self.update_plan()

    def dispose(self):
        self.disposing = True
        self.cancel_scan.set()
        if self.job is None:
            self.deleteLater()

    def update_plan(self):
        self.entries = ()
        all_entries, existing, problem, status = (), 0, "", ""
        imported = self.sources.currentIndex() == 1
        ready = False
        try:
            if imported and not getattr(self, "file_entries", None):
                raise ValueError(getattr(self, "file_error", "") or "请选择字表文件")
            if self.kind == "symbol":
                selector = self.import_selection if imported else self.selection
                groups, selected = selector.selection_entries()
                all_entries = (*selected, *((char, 0, groups.index(group)) for group, char in selector.reuse))
                ready = self.symbol_inventory is not None
            elif imported:
                all_entries = tuple(self.file_entries)
                ready = bool(self.writer)
            else:
                all_entries = self.stage.entries
                ready = self.missing is not None
            if not self.writer:
                raise ValueError("请先选择或新建书写者")
            if not ready:
                if self.scan_error:
                    raise ValueError(self.scan_error)
                status = "正在核对已有样本…"
            elif self.kind == "symbol":
                existing = sum(len(selector.available.get(
                    (capture_character(char), TASK_GROUPS[groups[index]][2]), {}
                )) >= count for char, count, index in all_entries)
                self.source, self.entries = selector.plan((groups, selected))
            elif imported:
                check_capture_paths(self.catalog.task_root(self.kind), self.writer)
                self.entries = all_entries
                self.source = self.file_path.name
            else:
                self.entries = tuple(entry for entry in all_entries if entry[0] in self.missing)
                self.source = self.stage.source
                existing = len(all_entries) - len(self.entries)
            if not self.name.text().strip():
                raise ValueError("请填写任务名称")
            if ready and not self.entries and self.kind == "han":
                raise ValueError("此目标均已有合格样本，无需新建任务。")
        except (OSError, ValueError) as error:
            problem = (self.writers_error or "请先选择或新建书写者") if not self.writer else str(error)
        if self.writer and not self.scan_error and not (self.kind == "han" and imported):
            waiting = self.missing is None if self.kind == "han" else self.symbol_inventory is None
            if waiting:
                status = "正在核对已有样本…"
        self.start.setEnabled(ready and not problem)
        self.status.setText(status)
        self.status.setVisible(bool(status))
        self.error.setText(problem)
        self.error.setVisible(bool(problem))
        self.counts["target"].setText(f"{len(all_entries)} 字" if self.kind == "han" else f"{len(all_entries)} 字／写法")
        self.counts["existing"].setText(f"{existing} 字" if ready else "—")
        self.counts["remaining"].setText(f"{len(self.entries)} 字" if ready else "—")
        self.counts["copies"].setText(f"{sum(count for _, count, _ in self.entries)} 份" if ready else "—")
        self.missing_button.setText(f"待录 {len(self.entries)} 字" if ready else "待录")
        self.all_button.setText(f"全部 {len(all_entries)} 字")
        show_all = self.show_all or not ready
        self.missing_button.setEnabled(ready)
        self.missing_button.setChecked(not show_all)
        self.all_button.setChecked(show_all)
        for key, button in self.stage_buttons.items():
            stage = self.stages[key]
            text = stage.title
            if self.missing is not None:
                text += f"\n待录 {sum(char in self.missing for char, _, _ in stage.entries)} 字"
            button.setText(text)
            button.setChecked(key == self.stage.key)
        self.refresh_preview(all_entries if show_all else self.entries, ready)

    def refresh_preview(self, displayed, ready):
        remaining = frozenset((char, index) for char, _, index in self.entries)
        key = tuple(displayed), ready, remaining
        if key == getattr(self, "_preview_key", None):
            return
        self._preview_key = key
        self.preview.clear()
        for char, count, index in displayed:
            label = char if count == 1 else f"{char}\n{count} 份"
            if count == 0:
                label = f"{char}\n复用"
            item = QtWidgets.QListWidgetItem(label)
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            font = item.font()
            font.setPointSize(15)
            item.setFont(font)
            if ready and (char, index) not in remaining:
                item.setForeground(self.palette().brush(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text))
                item.setToolTip("已有合格样本")
            self.preview.addItem(item)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "plan_row"):
            direction = QtWidgets.QBoxLayout.Direction.TopToBottom if self.width() < 630 else (
                QtWidgets.QBoxLayout.Direction.LeftToRight
            )
            self.plan_row.setDirection(direction)

    def accept(self):
        self.update_plan()
        if self.start.isEnabled():
            super().accept()
