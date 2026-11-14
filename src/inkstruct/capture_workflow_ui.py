"""Shared capture lifecycle for Han and extension tabs; raw records stay compatible."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .ui_behavior import compact_field
from .capture_management import (
    CaptureCatalog,
    ManagedRepository,
    check_capture_paths,
    preview_han_file,
    task_hash,
)


class WriterPicker(QtWidgets.QComboBox):
    textChanged = QtCore.Signal(str)

    def __init__(self, catalog, selected='', parent=None, *, allow_external=False):
        super().__init__(parent)
        self.catalog = catalog
        self.allow_external = allow_external
        self.setObjectName('capture_writer_picker')
        self.setMinimumContentsLength(16)
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        if allow_external:
            self.setEditable(True)
            self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
            self.setCompleter(None)
            self.lineEdit().setPlaceholderText('请选择书写者，或输入外部作者 ID')
        self.reload(selected)
        signal = self.currentTextChanged if allow_external else self.currentIndexChanged
        signal.connect(lambda _: self.textChanged.emit(self.text()))

    def text(self):
        if self.allow_external and (self.currentIndex() < 0 or self.currentText() != self.itemText(self.currentIndex())):
            return self.currentText()
        return self.currentData() or ''

    def showPopup(self):
        self.reload(self.text())
        super().showPopup()

    def setText(self, value):
        index = self.findData(value)
        if self.allow_external and (index < 0 or not value):
            with QtCore.QSignalBlocker(self):
                self.setCurrentIndex(-1)
                self.setEditText(value)
            self.textChanged.emit(value)
        else:
            self.setCurrentIndex(max(0, index))

    def reload(self, selected=''):
        with QtCore.QSignalBlocker(self):
            self.clear()
            catalog = self.catalog() if callable(self.catalog) else self.catalog
            try:
                writers = catalog.writers()
                self.setToolTip('')
                self.setEnabled(True)
            except (OSError, ValueError, ImportError) as error:
                self.addItem('采集管理记录需要修复', '')
                self.setToolTip(str(error) + '\n' + str(catalog.index))
                self.setEnabled(self.allow_external)
                if self.allow_external:
                    self.setText(selected)
                return
            self.addItem('请选择书写者…', '')
            for key, item in sorted(writers.items(), key=lambda pair: (pair[1]['name'], pair[0])):
                suffix = key if not key.startswith('w_') else key[-8:]
                self.addItem(f"{item['name']} · {suffix}", key)
            self.setText(selected)


def new_writer(catalog, picker, parent):
    name, ok = QtWidgets.QInputDialog.getText(parent, '新建书写者', '显示名称（可用中文，身份自动生成）：')
    if ok:
        try:
            key = catalog.create_writer(name)
            picker.reload(key)
            return key
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(parent, '未创建书写者', str(error))
    return None


class HanTaskDialog(QtWidgets.QDialog):
    def __init__(self, catalog, writer, path=None, parent=None):
        super().__init__(parent)
        self.catalog, self.path, self.entries = catalog, Path(path) if path else None, None
        self.setWindowTitle('确认汉字采集任务')
        self.setObjectName('han_task_dialog')
        self.resize(650, 500)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.writer = WriterPicker(catalog, writer)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.writer, 1)
        add = QtWidgets.QPushButton('新建书写者…')
        add.clicked.connect(lambda: new_writer(catalog, self.writer, self))
        row.addWidget(add)
        form.addRow('书写者', row)
        self.name = QtWidgets.QLineEdit(self.path.stem if self.path else '汉字样本采集')
        form.addRow('任务名称', compact_field(self.name, maximum=340))
        self.repeats = QtWidgets.QSpinBox()
        self.repeats.setRange(1, 100)
        self.repeats.setValue(5)
        form.addRow('CSV 空份数 / 默认份数', compact_field(self.repeats))
        layout.addLayout(form)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("inkTone", "danger")
        layout.addWidget(self.error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.ok = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.ok.setProperty("inkRole", "primary")
        self.ok.setText('创建并开始采集')
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.repeats.valueChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        try:
            check_capture_paths(self.catalog.root, self.writer.text())
            if self.path:
                entries, duplicates = preview_han_file(self.path, self.repeats.value())
            else:
                entries = [(c, self.repeats.value(), i) for i, c in enumerate('永中人大小天地日月山水')]
                duplicates = []
            self.entries = entries
            self.summary.setText(f'{len(entries)} 个汉字 · 共 {sum(c for _, c, _ in entries)} 份；本任务按字表份数采集，不自动抵扣其他任务。\n'
                                 f'来源：{self.path or "内置汉字字表"}\n保存到：{self.catalog.root}\n'
                                 + (f'同字符同份数重复行已合并：{duplicates}' if duplicates else '重复份数冲突会阻止创建。'))
            self.preview.setPlainText('\n'.join(f'{char}　{count} 份' for char, count, _ in entries))
            self.error.clear()
            self.ok.setEnabled(True)
        except (OSError, ValueError) as error:
            self.entries = None
            self.error.setText(str(error))
            self.ok.setEnabled(False)

    def accept(self):
        self.update_preview()
        if not self.writer.text():
            self.error.setText('请选择或新建书写者')
        elif not self.name.text().strip():
            self.error.setText('请填写任务名称')
        elif self.entries:
            super().accept()


class TaskListDialog(QtWidgets.QDialog):
    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog, self.result_action = catalog, None
        self.setWindowTitle('采集任务管理')
        self.setObjectName('capture_task_list')
        self.resize(920, 570)
        layout = QtWidgets.QVBoxLayout(self)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('搜索任务名称、书写者或任务 ID；包含已完成、已取消及损坏任务')
        layout.addWidget(self.search)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(['任务', '类别', '书写者', '状态', '已保存 / 总份数'])
        layout.addWidget(self.tree, 1)
        self.info = QtWidgets.QLabel('关闭或取消任务均不删除已有样本。双击可打开；已取消任务需明确恢复。')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        row = QtWidgets.QHBoxLayout()
        self.actions = {}
        for action, title in [('open', '打开 / 继续'), ('restore', '恢复任务'), ('cancel', '取消任务…'), ('archive', '归档')]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda _, a=action: self.choose(a))
            self.actions[action] = button
            row.addWidget(button)
        close = QtWidgets.QPushButton('关闭')
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)
        secondary = QtWidgets.QHBoxLayout()
        for action, title in [('rename', '修改任务名称…'), ('copy', '复制未录部分…')]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda _, a=action: self.choose(a))
            self.actions[action] = button
            secondary.addWidget(button)
        layout.addLayout(secondary)
        self.search.textChanged.connect(self.filter_items)
        self.tree.itemSelectionChanged.connect(self.selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.choose('open'))
        writers = catalog.writers()
        for entry in catalog.tasks():
            task = entry['task']
            status = {'active':'进行中', 'paused':'已暂停', 'cancelled':'已取消', 'archived':'已归档', 'damaged':'需要修复'}[entry['state']]
            if task and task.is_complete and entry['state'] not in ('cancelled', 'archived'):
                status = '已完成'
            item = QtWidgets.QTreeWidgetItem([task.name if task else entry['path'].parent.name,
                '汉字样本' if entry['kind'] == 'han' else '标点与扩展',
                writers.get(task.writer_id, {'name':task.writer_id})['name'] if task else '—', status,
                f'{task.completed_count} / {len(task.items)}' if task else '—'])
            item.setData(0, QtCore.Qt.UserRole, entry)
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)
        self.selection_changed()

    def filter_items(self, text):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            entry = item.data(0, QtCore.Qt.UserRole)
            item.setHidden(text.casefold() not in (' '.join(item.text(c) for c in range(5)) + str(entry['path'])).casefold())

    def selection_changed(self):
        items = self.tree.selectedItems()
        entry = items[0].data(0, QtCore.Qt.UserRole) if items else None
        for action, button in self.actions.items():
            button.setEnabled(bool(entry and entry['task'] and (action != 'open' or entry['state'] not in ('cancelled', 'archived'))))
        if entry:
            self.info.setText(str(entry['path']) + ('\n需要修复，原文件未修改：' + entry['error'] if entry['error'] else '\n取消只停止剩余任务，已有样本和进度保留。'))

    def choose(self, action):
        items = self.tree.selectedItems()
        if items and self.actions[action].isEnabled():
            self.result_action = items[0].data(0, QtCore.Qt.UserRole), action
            self.accept()


class CaptureLifecycleMixin:
    """Both managed widgets share guards, pinned roots, task lists and rerecording."""
    def _task_dependencies(self):
        if not getattr(self, '_capture_catalog', None):
            return super()._task_dependencies()
        from handwriting_collector.storage import SampleStorage

        from .symbol_capture import SymbolStorage
        root = self._managed_root or self._capture_catalog.task_root(self._capture_kind)
        storage = SymbolStorage(root, self.variant_note.text) if self._capture_kind == 'symbol' else SampleStorage(root)
        return root, ManagedRepository(root, self), storage

    def _can_switch(self):
        if self.canvas.pen_down:
            QtWidgets.QMessageBox.information(self, '请先抬笔', '当前正在书写，请先抬笔再操作。')
            return False
        if not self.canvas.trajectory.point_count:
            return True
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle('当前笔迹尚未保存')
        box.setText('保存当前笔迹后继续，或放弃本次笔迹；已有样本不受影响。')
        save = box.addButton('保存并继续', QtWidgets.QMessageBox.AcceptRole)
        discard = box.addButton('放弃当前笔迹', QtWidgets.QMessageBox.DestructiveRole)
        back = box.addButton('返回采集', QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(back)
        save.setEnabled(bool(self.task and self.save_button.isEnabled()))
        box.exec()
        if box.clickedButton() is save:
            self.save_current()
            return not self.canvas.trajectory.point_count
        return box.clickedButton() is discard

    def _capture_error(self, error):
        QtWidgets.QMessageBox.warning(self, '采集操作未完成', str(error) + '\n原任务和样本保留；可在任务列表查看数据路径。')

    def set_task(self, task):
        if getattr(self, '_capture_catalog', None):
            root = self._capture_catalog.task_root(self._capture_kind)
            self._managed_root = root
            self._managed_stamp = task_hash(root / 'tasks' / task.task_id / 'state.json')
            self._capture_catalog.set_state(self._capture_kind, task.task_id, 'active')
        super().set_task(task)
        if getattr(self, '_capture_catalog', None):
            self.writer_picker.reload(task.writer_id)
            self.task_help.setText('任务身份固定；显示名称可修改。关闭、取消均保留已保存样本。')
            self._sync_selected_writer(task.writer_id)

    def refresh(self):
        super().refresh()
        if getattr(self, '_capture_catalog', None):
            for button in (self.pause_button, self.cancel_task_button):
                button.setEnabled(self.task is not None)
            self.review_button.setEnabled(bool(self.task and self.task.completed_count and not self.canvas.pen_down))
            if self.task:
                skipped = sum(i.status == 'skipped' for i in self.task.items)
                self.progress_label.setText(f'已保存 {self.task.completed_count} / {len(self.task.items)} · 稍后录 {skipped}')

    def _close_task(self):
        self.task = None
        self._managed_root, self._managed_stamp = None, None
        if hasattr(self, '_task_root'):
            self._task_root = None
        self.canvas.clear()
        if hasattr(self, 'variant_note'):
            self.variant_note.clear()
        self.writer_edit.setText(self._capture_selected())
        self.writer_picker.reload(self._capture_selected())
        self.refresh()

    def pause_task(self):
        if self.task and self._can_switch():
            try:
                self._capture_catalog.set_state(self._capture_kind, self.task.task_id, 'paused')
                self._close_task()
            except (OSError, ValueError) as error:
                self._capture_error(error)

    def cancel_task(self):
        if not self.task:
            return
        if QtWidgets.QMessageBox.question(self, '取消任务（保留样本）',
            '停止此任务的剩余采集？已保存样本和进度全部保留，可在任务列表恢复。',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        if self._can_switch():
            try:
                self._capture_catalog.set_state(self._capture_kind, self.task.task_id, 'cancelled')
                self._close_task()
            except (OSError, ValueError) as error:
                self._capture_error(error)

    def choose_writer(self, key):
        if not key:
            if self.task:
                self.writer_picker.reload(self.task.writer_id)
            return
        old = self.task.writer_id if self.task else self.writer_edit.text()
        try:
            if self.task and key != old:
                from .symbol_tasks import source_configuration
                reuse = source_configuration(self.task.source)['reuse']
                import json
                history = any(json.loads(p.read_text('utf-8')).get('task_id') == self.task.task_id
                              for p in (self._managed_root / 'revisions').glob('*/revision.json'))
                history = history or any(json.loads(p.read_text('utf-8')).get('task', {}).get('task_id') == self.task.task_id
                    for p in (self._managed_root / 'samples' / old).glob('*/*.json'))
                if self.task.completed_count == 0 and not history and not reuse:
                    if not self._can_switch():
                        self.writer_picker.reload(old)
                        return
                    # The guard may have saved the first specimen under the
                    # original author. Never reassign that now-populated task.
                    if self.task.completed_count:
                        self.writer_picker.reload(old)
                        self.task_help.setText('刚才的笔迹已保存给原书写者，任务归属未改变；请暂停后新建或复制未录部分。')
                        return
                    if QtWidgets.QMessageBox.question(self, '更换任务书写者', '此任务尚未保存样本，确认更换书写者？',
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
                        self.writer_picker.reload(old)
                        return
                    updated = type(self.task).from_dict(self.task.to_dict())
                    updated.writer_id = key
                    with self.task_lock():
                        self._task_dependencies()[1].save(updated)
                    self.canvas.clear()
                    self.set_task(updated)
                else:
                    if QtWidgets.QMessageBox.question(self, '任务已有样本或复用配置',
                        '已保存内容不能直接改变归属。暂停并关闭当前任务，为新任务选择该书写者？',
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
                        self.writer_picker.reload(old)
                        return
                    self.pause_task()
                    if self.task:
                        self.writer_picker.reload(old)
                        return
            self.writer_edit.setText(key)
            self.writer_picker.reload(key)
            self._sync_selected_writer(key)
        except (OSError, ValueError) as error:
            self.writer_picker.reload(old)
            self._capture_error(error)

    def _capture_selected(self):
        return self._capture_window.capture_selected_writer

    def _sync_selected_writer(self, key):
        self._capture_window.capture_selected_writer = key
        for other in (self._capture_window.single_widget, self._capture_window.symbol_widget):
            if other is not self and not other.task and hasattr(other, 'writer_picker'):
                other.writer_edit.setText(key)
                other.writer_picker.reload(key)
        self._capture_window.writer_selected.emit(key)

    def task_lock(self):
        from contextlib import contextmanager
        @contextmanager
        def locked():
            if not self.task or self._managed_root is None:
                yield
                return
            path = self._managed_root / 'tasks' / self.task.task_id / '.capture.lock'
            lock = QtCore.QLockFile(str(path))
            if not lock.tryLock(0):
                raise ValueError('另一窗口正在保存此任务，请稍后重试')
            try:
                expected = self._managed_stamp
                state = self._capture_catalog.read()['tasks'].get(self._capture_kind + ':' + self.task.task_id, 'active')
                if state != 'active':
                    raise ValueError('此任务已暂停、取消或归档，请在任务列表恢复或重新打开')
                if expected is not None and task_hash(path.parent / 'state.json') != expected:
                    raise ValueError('任务已被其他窗口修改，请重新打开；当前笔迹保留')
                yield
            finally:
                lock.unlock()
        return locked()

    def save_current(self):
        if not getattr(self, '_capture_catalog', None):
            return super().save_current()
        if getattr(self, '_capture_saving', False):
            return
        self._capture_saving = True
        try:
            with self.task_lock():
                if self.task and not self.canvas.pen_down:
                    check_capture_paths(self._managed_root, self.task.writer_id)
                    super().save_current()
        except (OSError, ValueError) as error:
            self._capture_error(error)
        finally:
            self._capture_saving = False

    def skip_current(self):
        if not getattr(self, '_capture_catalog', None):
            return super().skip_current()
        if self._can_switch():
            try:
                with self.task_lock():
                    super().skip_current()
            except (OSError, ValueError) as error:
                self._capture_error(error)

    def import_task(self):
        if not getattr(self, '_capture_catalog', None):
            return super().import_task()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '选择汉字字表', '', '字表 (*.txt *.csv)')
        if path:
            self.configure_han_task(path)

    def create_example_task(self):
        if not getattr(self, '_capture_catalog', None):
            return super().create_example_task()
        self.configure_han_task()

    def configure_han_task(self, path=None):
        from handwriting_collector.tasks import CollectionTask, TaskRepository
        try:
            dialog = HanTaskDialog(self._capture_catalog, self.writer_edit.text(), path, self)
            if dialog.exec() != QtWidgets.QDialog.Accepted or not self._can_switch():
                return
            root = self._capture_catalog.root
            task = CollectionTask.create(dialog.name.text().strip(), Path(path).name if path else 'builtin:cjk-demo',
                                         dialog.writer.text(), dialog.entries)
            TaskRepository(root).save(task)
            if self.task:
                self._capture_catalog.set_state(self._capture_kind, self.task.task_id, 'paused')
            self._managed_root = None
            self.set_task(task)
            self._capture_window.capture_selected_writer = task.writer_id
            self._capture_window.writer_selected.emit(task.writer_id)
        except (OSError, ValueError) as error:
            self._capture_error(error)

    def resume_task(self, *, quiet=False):
        if getattr(self, '_capture_catalog', None):
            if not quiet:
                self.task_list()
        else:
            return super().resume_task(quiet=quiet)

    def open_managed_task(self, entry):
        from handwriting_collector.tasks import TaskRepository
        if not self._can_switch():
            return
        root = entry['root']
        from handwriting_collector.storage import SampleStorage

        from .symbol_capture import SymbolStorage
        from .symbol_revisions import recover_revisions
        lock = QtCore.QLockFile(str(entry['path'].parent / '.capture.lock'))
        if not lock.tryLock(0):
            raise ValueError('另一窗口正在保存此任务，请稍后重试')
        try:
            task = TaskRepository(root).load(entry['path'])
            recover_revisions(root, task)
            storage = SymbolStorage(root) if self._capture_kind == 'symbol' else SampleStorage(root)
            if storage.reconcile_task(task):
                TaskRepository(root).save(task)
            if self.task and self.task.task_id != task.task_id:
                self._capture_catalog.set_state(self._capture_kind, self.task.task_id, 'paused')
            self.set_task(task)
        finally:
            lock.unlock()

    def task_list(self):
        try:
            dialog = TaskListDialog(self._capture_catalog, self)
            if dialog.exec() != QtWidgets.QDialog.Accepted:
                return
            entry, action = dialog.result_action
            target = self._capture_window.single_widget if entry['kind'] == 'han' else self._capture_window.symbol_widget
            if action == 'open':
                target.open_managed_task(entry)
                self._capture_window.tabs.setCurrentWidget(target)
            elif action in ('rename', 'copy'):
                self.edit_task(entry, action, target)
            elif action == 'restore':
                self._capture_catalog.set_state(entry['kind'], entry['task'].task_id, 'paused')
                target.open_managed_task(entry)
                self._capture_window.tabs.setCurrentWidget(target)
            else:
                if target.task and target.task.task_id == entry['task'].task_id:
                    if action == 'cancel':
                        target.cancel_task()
                    else:
                        target.pause_task()
                        if target.task is None:
                            self._capture_catalog.set_state(entry['kind'], entry['task'].task_id, 'archived')
                elif action != 'cancel' or QtWidgets.QMessageBox.question(self, '取消任务', '停止剩余采集并保留样本，可恢复？',
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes:
                    self._capture_catalog.set_state(entry['kind'], entry['task'].task_id, 'cancelled' if action == 'cancel' else 'archived')
        except (OSError, ValueError) as error:
            self._capture_error(error)

    def edit_task(self, entry, action, target):
        import json

        from handwriting_collector.tasks import CollectionTask, TaskRepository

        from .resource_catalog import atomic_json
        from .symbol_tasks import CUSTOM_PREFIXES, source_configuration
        repository = TaskRepository(entry['root'])
        if action == 'rename':
            name, ok = QtWidgets.QInputDialog.getText(self, '修改任务名称', '新名称：', text=entry['task'].name)
            if not ok or not name.strip():
                return
            lock = QtCore.QLockFile(str(entry['path'].parent / '.capture.lock'))
            if not lock.tryLock(0):
                raise ValueError('任务正在其他窗口保存，请稍后重试')
            try:
                task = repository.load(entry['path'])
                if task.to_dict() != entry['task'].to_dict():
                    raise ValueError('任务已变化，请重新打开任务列表')
                task.name = name.strip()
                repository.save(task)
                if target.task and target.task.task_id == task.task_id:
                    # Do not clear an unsaved canvas while only renaming a task.
                    target.task.name = task.name
                    target._managed_stamp = task_hash(entry['path'])
                    target.refresh()
            finally:
                lock.unlock()
            return
        pending = [i for i in entry['task'].items if i.status != 'completed']
        if not pending:
            raise ValueError('该任务没有未录份次；已完成样本可通过重录入口处理')
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('复制未录部分为新任务')
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel(f'复制 {len(pending)} 个未录份次；原任务、样本、进度不变。新书写者不继承原复用确认。'))
        picker = WriterPicker(self._capture_catalog, self._capture_selected())
        layout.addWidget(picker)
        create = QtWidgets.QPushButton('新建书写者…')
        create.clicked.connect(lambda: new_writer(self._capture_catalog, picker, dialog))
        layout.addWidget(create)
        name = QtWidgets.QLineEdit(entry['task'].name + ' · 未录部分')
        layout.addWidget(name)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        if not picker.text() or not name.text().strip():
            raise ValueError('请选择书写者并填写新任务名称')
        if repository.load(entry['path']).to_dict() != entry['task'].to_dict():
            raise ValueError('原任务已变化，请重新复制未录部分')
        counts = {}
        for item in pending:
            key = item.character, item.source_index
            counts[key] = counts.get(key, 0) + 1
        source = entry['task'].source
        if source.startswith(CUSTOM_PREFIXES):
            config = source_configuration(source)
            config['reuse'] = []
            prefix = next(prefix for prefix in CUSTOM_PREFIXES if source.startswith(prefix))
            source = prefix + json.dumps(config, separators=(',', ':'))
        task = CollectionTask.create(name.text().strip(), source, picker.text(), [(c,n,index) for (c,index),n in counts.items()])
        path = repository.path_for(task.task_id)
        path.parent.mkdir(parents=True, exist_ok=False)
        atomic_json(path.parent / 'copy-origin.json', {'schema_version':'inkstruct_capture_task_copy_v1',
            'task_id':task.task_id, 'source_task_id':entry['task'].task_id, 'source_state_sha256':task_hash(entry['path']),
            'source_item_ids':[i.item_id for i in pending]})
        repository.save(task)
        QtWidgets.QMessageBox.information(self, '新任务已创建', '原任务不变；请在任务列表选择新任务后继续采集。')

    def review_saved(self):
        if not self.task or not self.task.completed_count:
            return
        from .symbol_review_dialog import SymbolReviewDialog
        from .symbol_revisions import requeue_completed
        dialog = SymbolReviewDialog(self.task, self._task_dependencies()[0], self)
        if dialog.exec() == QtWidgets.QDialog.Accepted and self._can_switch():
            try:
                with self.task_lock():
                    root, repository, _ = self._task_dependencies()
                    requeue_completed(root, self.task, repository, dialog.selected_ids())
                self.canvas.clear()
                self.refresh()
            except (OSError, ValueError) as error:
                self._capture_error(error)


def install_capture_management(window, root):
    window.capture_selected_writer = ''
    catalog = CaptureCatalog(root)
    for kind, widget in [('han', window.single_widget), ('symbol', window.symbol_widget)]:
        widget._capture_kind, widget._capture_catalog, widget._capture_window = kind, catalog, window
        widget._managed_root, widget._managed_stamp = None, None
        widget.writer_edit.clear()
        widget.writer_edit.hide()
        for label in widget.findChildren(QtWidgets.QLabel):
            if label.text() == '书写者 ID':
                label.hide()
        widget.resume_button.hide()
        widget.example_button.setText('创建任务')
        panel = QtWidgets.QWidget()
        panel.setObjectName('capture_writer_panel')
        column = QtWidgets.QVBoxLayout(panel)
        column.setContentsMargins(12, 10, 12, 10)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('书写者'))
        widget.writer_picker = WriterPicker(catalog)
        row.addWidget(widget.writer_picker, 1)
        new = QtWidgets.QPushButton('新建书写者…')
        rename = QtWidgets.QPushButton('修改名称…')
        profiles = QtWidgets.QPushButton('书写者资料')
        profile_menu = QtWidgets.QMenu(profiles)
        profile_menu.addAction('导入书写者资料…', lambda _checked=False, w=widget: transfer_writer_profile(w, importing=True))
        profile_menu.addAction('导出当前书写者资料…', lambda _checked=False, w=widget: transfer_writer_profile(w, importing=False))
        profile_menu.addSeparator()
        profile_menu.addAction('导入样本文件或 ZIP 到当前书写者…', lambda _checked=False, w=widget: import_writer_samples(w))
        profile_menu.addAction('导入样本目录到当前书写者…', lambda _checked=False, w=widget: import_writer_samples(w, directory=True))
        profiles.setMenu(profile_menu)
        row.addWidget(new)
        row.addWidget(rename)
        row.addWidget(profiles)
        column.addLayout(row)
        widget.task_help = QtWidgets.QLabel('先选择或新建书写者，再创建任务。任务列表可恢复历史任务，关闭与取消不删除样本。')
        widget.task_help.setWordWrap(True)
        column.addWidget(widget.task_help)
        actions = QtWidgets.QHBoxLayout()
        task_list = QtWidgets.QPushButton('任务列表…')
        task_list.setObjectName('capture_task_list_button')
        widget.pause_button = QtWidgets.QPushButton('暂停并关闭')
        widget.pause_button.setObjectName('capture_pause_task')
        widget.cancel_task_button = QtWidgets.QPushButton('取消任务…')
        widget.cancel_task_button.setObjectName('capture_cancel_task')
        if kind == 'han':
            widget.review_button = QtWidgets.QPushButton('查看 / 重录已保存…')
            widget.review_button.clicked.connect(widget.review_saved)
            actions.addWidget(widget.review_button)
        for button in (task_list, widget.pause_button, widget.cancel_task_button):
            actions.addWidget(button)
        column.addLayout(actions)
        widget.layout().insertWidget(0, panel)
        widget.writer_picker.textChanged.connect(widget.choose_writer)
        def create(_checked=False, w=widget):
            key = new_writer(w._capture_catalog, w.writer_picker, w)
            if key:
                w.choose_writer(key)
        def rename_current(_checked=False, w=widget):
            key = w.task.writer_id if w.task else w.writer_edit.text()
            if not key:
                return
            name, ok = QtWidgets.QInputDialog.getText(w, '修改显示名称', '只改名称，不改样本归属：', text=w._capture_catalog.writers()[key]['name'])
            if ok:
                try:
                    w._capture_catalog.rename_writer(key, name)
                    for other in (window.single_widget, window.symbol_widget):
                        other.writer_picker.reload(other.task.writer_id if other.task else other.writer_edit.text())
                except (OSError, ValueError) as error:
                    w._capture_error(error)
        new.clicked.connect(create)
        rename.clicked.connect(rename_current)
        task_list.clicked.connect(widget.task_list)
        widget.pause_button.clicked.connect(widget.pause_task)
        widget.cancel_task_button.clicked.connect(widget.cancel_task)
        widget.refresh()


def transfer_writer_profile(widget, *, importing):
    catalog = widget._capture_catalog
    key = widget.writer_picker.text()
    filters = 'InkStruct 书写者资料 (*.inkwriter)'
    try:
        if importing:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(widget, '导入书写者资料', '', filters)
            if path:
                key = catalog.import_writer(path)
                widget.writer_picker.reload(key)
                widget.choose_writer(key)
        elif key:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(widget, '导出书写者资料', key + '.inkwriter', filters)
            if path:
                catalog.export_writer(key, path)
        else:
            raise ValueError('请先选择要导出的书写者')
    except (OSError, ValueError) as error:
        widget._capture_error(error)


def import_writer_samples(widget, *, directory=False):
    from .fonts.ui import Job
    from .writer_samples import SampleImports, inspect_samples

    if getattr(widget, '_writer_import_job', None) is not None:
        return
    writer = widget.writer_picker.text()
    if not writer:
        widget._capture_error(ValueError('请先选择接收样本的书写者'))
        return
    if directory:
        path = QtWidgets.QFileDialog.getExistingDirectory(widget, '选择样本目录')
    else:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(widget, '选择样本文件或 ZIP', '', '样本 (*.json *.zip)')
    if not path:
        return
    catalog, kind = widget._capture_catalog, widget._capture_kind

    def start(function, completed):
        job = widget._writer_import_job = Job(function)
        job.signals.completed.connect(completed, QtCore.Qt.ConnectionType.QueuedConnection)
        job.signals.failed.connect(failed, QtCore.Qt.ConnectionType.QueuedConnection)
        QtCore.QThreadPool.globalInstance().start(job)

    def failed(error):
        widget._writer_import_job = None
        widget._capture_error(ValueError(error))

    def finished(count):
        widget._writer_import_job = None
        widget.task_help.setText(f'已向 {writer} 导入 {count} 份新样本。')

    def confirm(selection):
        if widget._capture_catalog is not catalog or widget.writer_picker.text() != writer:
            widget._writer_import_job = None
            return
        box = QtWidgets.QMessageBox(widget)
        box.setWindowTitle('确认样本归属')
        box.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        box.setText(f'原书写者 ID  {selection.writer}\n目标书写者 ID  {writer}\n'
                    f'{len(selection.records)} 份样本，{len(selection.characters)} 个字符\n\n'
                    '确认样本由目标书写者录制。导入副本会记录原书写者、原样本 ID 和哈希。')
        box.setDetailedText(f'{path}\n\n字符范围\n{selection.characters}')
        buttons = QtWidgets.QMessageBox.StandardButton
        box.setStandardButtons(buttons.Yes | buttons.Cancel)
        box.setDefaultButton(buttons.Cancel)
        if box.exec() == buttons.Yes and widget._capture_catalog is catalog and widget.writer_picker.text() == writer:
            start(lambda _: SampleImports(catalog).add(kind, writer, selection), finished)
        else:
            widget._writer_import_job = None

    start(lambda _: inspect_samples(path, kind), confirm)
