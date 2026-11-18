"""Task-focused capture views reusing the existing recording controls."""
from PySide6 import QtCore, QtWidgets

from .capture_management import prepare_managed_task


class CaptureWorkspace(QtCore.QObject):
    def __init__(self, widget, panel, create_writer, rename_writer, profiles, task_list, samples):
        super().__init__(widget)
        self.widget = widget
        self.recent_key = None
        self.opening = None
        self.context_revision = 0
        widget.canvas.trajectory_changed.connect(self._advance_context)
        widget.writer_edit.textChanged.connect(self._advance_context)
        widget._capture_window.tabs.currentChanged.connect(self._advance_context)
        root = widget.layout()
        root.removeWidget(panel)
        panel.hide()
        old_top = QtWidgets.QWidget(widget)
        original_header = root.takeAt(0).layout()
        original_header.setParent(None)
        old_top.setLayout(original_header)
        old_top.hide()
        recording = QtWidgets.QWidget(widget)
        body = QtWidgets.QVBoxLayout(recording)
        body.setContentsMargins(0, 0, 0, 0)
        while root.count():
            stretch = root.stretch(0)
            item = root.takeAt(0)
            if item.widget():
                body.addWidget(item.widget(), stretch, item.alignment())
            elif item.layout():
                layout = item.layout()
                layout.setParent(None)
                holder = QtWidgets.QWidget(recording)
                holder.setLayout(layout)
                if not stretch:
                    holder.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Maximum)
                body.addWidget(holder, stretch)
            else:
                body.addItem(item)
        root.setSpacing(12)

        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("采集样本")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)
        self.heading_title = title
        self.heading = heading
        heading.addWidget(title, 1)
        widget.new_task_button = QtWidgets.QPushButton("新建任务…")
        widget.new_task_button.setObjectName("capture_new_task")
        widget.new_task_button.setProperty("inkRole", "primary")
        widget.new_task_button.clicked.connect(widget.new_capture_task)
        heading.addWidget(widget.new_task_button)
        task_list.setText("任务管理…")
        heading.addWidget(task_list)
        task_list.show()
        root.addLayout(heading)
        author = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("书写者")
        label.setBuddy(widget.writer_picker)
        author.addWidget(label)
        author.addWidget(widget.writer_picker, 1)
        widget.writer_picker.setMaximumWidth(420)
        widget.writer_picker.show()
        author.addStretch()
        manage = QtWidgets.QPushButton("管理书写者…")
        manage.setObjectName("capture_manage_writers")
        menu = QtWidgets.QMenu(manage)
        menu.addAction("新建书写者…", create_writer)
        menu.addAction("修改显示名称…", rename_writer)
        menu.addSeparator()
        for action in profiles.menu().actions():
            menu.addAction(action)
        manage.setMenu(menu)
        author.addWidget(manage)
        root.addLayout(author)

        self.stack = QtWidgets.QStackedWidget()
        self.idle = QtWidgets.QWidget()
        idle_layout = QtWidgets.QVBoxLayout(self.idle)
        idle_layout.setContentsMargins(16, 20, 16, 16)
        self.idle_title = QtWidgets.QLabel("开始一份采集任务")
        font = self.idle_title.font()
        font.setPointSize(font.pointSize() + 3)
        self.idle_title.setFont(font)
        idle_layout.addWidget(self.idle_title)
        self.idle_hint = QtWidgets.QLabel()
        self.idle_hint.setWordWrap(True)
        idle_layout.addWidget(self.idle_hint)
        begin = self.begin = QtWidgets.QPushButton("新建任务…")
        begin.setProperty("inkRole", "primary")
        begin.setMaximumWidth(150)
        begin.clicked.connect(widget.new_capture_task)
        idle_layout.addWidget(begin)
        idle_layout.addSpacing(20)
        self.recent_label = QtWidgets.QLabel("最近未完成")
        idle_layout.addWidget(self.recent_label)
        self.recent = QtWidgets.QTreeWidget()
        self.recent.setObjectName("capture_recent_tasks")
        self.recent.setProperty("inkDataTable", True)
        self.recent.setHeaderLabels(["任务", "已保存 / 总份数", "操作"])
        self.recent.setRootIsDecorated(False)
        self.recent.setAlternatingRowColors(True)
        self.recent.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.recent.setMaximumWidth(715)
        self.recent.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        header = self.recent.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 116)
        self.recent.headerItem().setTextAlignment(1, QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.recent.itemActivated.connect(lambda item, _col: self.resume(item.data(0, QtCore.Qt.ItemDataRole.UserRole)))
        idle_layout.addWidget(self.recent)
        self.empty_recent = QtWidgets.QLabel("此书写者暂无未完成任务")
        idle_layout.addWidget(self.empty_recent)
        idle_layout.addStretch(1)
        self.stack.addWidget(self.idle)

        active = QtWidgets.QWidget()
        active_layout = QtWidgets.QVBoxLayout(active)
        active_layout.setContentsMargins(0, 0, 0, 0)
        task_bar = QtWidgets.QVBoxLayout()
        widget.task_name_label.setWordWrap(True)
        widget.task_name_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        task_bar.addWidget(widget.task_name_label)
        widget.task_name_label.show()
        progress = QtWidgets.QHBoxLayout()
        progress.addWidget(widget.progress_label, 1)
        widget.progress_label.show()
        widget.review_button.setText("查看 / 重录")
        widget.review_button.setToolTip("查看或重录当前任务的已保存样本")
        progress.addWidget(widget.review_button)
        widget.review_button.show()
        progress.addWidget(widget.pause_button)
        widget.pause_button.show()
        more = QtWidgets.QPushButton("更多…")
        more_menu = QtWidgets.QMenu(more)
        more_menu.addAction("取消任务…", widget.cancel_task)
        more_menu.addAction("样本库…", samples.click)
        more.setMenu(more_menu)
        progress.addWidget(more)
        task_bar.addLayout(progress)
        widget.progress_bar.setMaximumWidth(16777215)
        task_bar.addWidget(widget.progress_bar)
        widget.progress_bar.show()
        active_layout.addLayout(task_bar)
        self.complete = QtWidgets.QLabel("本次任务已录制完成")
        self.complete.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        active_layout.addWidget(self.complete, 1)
        active_layout.addWidget(recording, 1)
        self.recording = recording
        self.stack.addWidget(active)
        root.addWidget(self.stack, 1)
        root.addWidget(widget.task_help)
        widget.task_help.show()
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Type.Show:
            self.recent_key = None
            self.refresh()
        return super().eventFilter(watched, event)

    def refresh(self):
        widget = self.widget
        self.stack.setCurrentIndex(1 if widget.task else 0)
        has_item = bool(widget.task and widget.task.current_item())
        self.recording.setVisible(has_item)
        self.complete.setText("复用配置已保存" if widget.task and widget._capture_kind == "symbol"
                              and not widget.task.items else "本次任务已录制完成")
        self.complete.setVisible(bool(widget.task and not has_item))
        widget.task_help.setVisible(bool(widget.task_help.text()))
        widget.new_task_button.setEnabled(not widget.canvas.pen_down)
        self.begin.setEnabled(bool(widget.writer_edit.text()))
        key = (widget.writer_edit.text(), widget.task.task_id if widget.task else None,
               str(widget._capture_catalog.root))
        if key == self.recent_key:
            return
        self.recent_key = key
        self.recent.clear()
        try:
            catalog = widget._capture_catalog
            name = catalog.writers().get(key[0], {}).get("name", key[0])
            self.idle_hint.setText(f"为{name}创建任务，或继续已有任务。" if name else "请先选择或新建书写者。")
            tasks = [entry for entry in catalog.tasks() if entry["task"]
                     and entry["kind"] == widget._capture_kind and entry["task"].writer_id == key[0]
                     and entry["task"].items and not entry["task"].is_complete
                     and entry["state"] in ("active", "paused")]
            for entry in sorted(tasks, key=lambda item: item["task"].created_at, reverse=True)[:5]:
                task = entry["task"]
                item = QtWidgets.QTreeWidgetItem([task.name, f"{task.completed_count} / {len(task.items)}", ""])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, entry)
                item.setToolTip(0, task.name)
                item.setSizeHint(0, QtCore.QSize(0, 40))
                item.setTextAlignment(1, QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                self.recent.addTopLevelItem(item)
                action = QtWidgets.QWidget()
                action_layout = QtWidgets.QHBoxLayout(action)
                action_layout.setContentsMargins(8, 0, 8, 0)
                resume = QtWidgets.QPushButton("继续录制", action)
                resume.setAccessibleDescription(task.name)
                resume.clicked.connect(lambda _checked=False, value=entry: self.resume(value))
                action_layout.addWidget(resume)
                action_layout.addStretch()
                self.recent.setItemWidget(item, 2, action)
            self.recent.setFixedHeight(self.recent.header().sizeHint().height() + 2 * self.recent.frameWidth()
                                       + 40 * self.recent.topLevelItemCount())
            if tasks:
                self.recent.setCurrentItem(self.recent.topLevelItem(0))
            self.recent.setVisible(bool(tasks))
            self.recent_label.setVisible(bool(tasks))
            self.empty_recent.setText("此书写者暂无未完成任务")
            self.empty_recent.setVisible(not tasks)
            self._update_opening()
        except (OSError, ValueError) as error:
            self.empty_recent.setText("读取最近任务失败，" + str(error))
            self.empty_recent.show()

    def _advance_context(self, *_):
        self.context_revision += 1

    def _open_context(self, origin):
        widget = self.widget
        return (self.context_revision, origin.capture_workspace.context_revision,
                widget._capture_catalog, widget.task, widget._managed_stamp)

    def _update_opening(self):
        selected = self.opening[0]["path"] if self.opening else None
        for row in range(self.recent.topLevelItemCount()):
            item = self.recent.topLevelItem(row)
            button = self.recent.itemWidget(item, 2).findChild(QtWidgets.QPushButton)
            path = item.data(0, QtCore.Qt.ItemDataRole.UserRole)["path"]
            button.setText("正在打开…" if path == selected else "继续录制")
            button.setEnabled(selected is None)

    def resume(self, entry):
        from .fonts.ui import Job

        widget = self.widget
        window = widget._capture_window
        if getattr(window, "opening_capture_task", None) is not None or not widget._can_switch():
            return
        origin = window.tabs.currentWidget()
        catalog = widget._capture_catalog
        job = Job(lambda _: prepare_managed_task(entry, catalog))
        self.opening = entry, origin, self._open_context(origin), job
        window.opening_capture_task = self
        origin.task_help.setText("正在打开采集任务…")
        origin.task_help.show()
        self._update_opening()
        job.signals.completed.connect(self._opened, QtCore.Qt.ConnectionType.QueuedConnection)
        job.signals.failed.connect(self._open_failed, QtCore.Qt.ConnectionType.QueuedConnection)
        QtCore.QThreadPool.globalInstance().start(job)

    def _end_open(self):
        entry, origin, context, _job = self.opening
        self.opening = None
        self.widget._capture_window.opening_capture_task = None
        if origin.task_help.text() == "正在打开采集任务…":
            origin.task_help.clear()
            origin.task_help.hide()
        self._update_opening()
        return entry if context == self._open_context(origin) else None

    @QtCore.Slot(object)
    def _opened(self, prepared):
        entry = self._end_open()
        if entry is None:
            return
        try:
            self.widget.finish_managed_task(entry, prepared)
            self.widget._capture_window.tabs.setCurrentWidget(self.widget)
        except (OSError, ValueError) as error:
            self.widget._capture_error(error)

    @QtCore.Slot(str)
    def _open_failed(self, error):
        if self._end_open() is not None:
            self.widget._capture_error(error)
