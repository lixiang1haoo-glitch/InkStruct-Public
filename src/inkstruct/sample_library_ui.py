"""Windows capture sample browser and offline exchange."""

from itertools import groupby
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .capture_workflow_ui import WriterPicker
from .fonts.ui import Job
from .sample_library import CATEGORIES, SampleLibrary, export_bundle, inventory, open_source, read_row
from .symbol_review_dialog import InkPreview


class SampleLibraryPage(QtWidgets.QWidget):
    def __init__(self, catalog, writer='', parent=None):
        super().__init__(parent)
        self.setObjectName('sample_library')
        self.library = SampleLibrary(catalog)
        self.all_rows, self.tasks = (), {}
        self.scan_errors = ()
        self.job = None
        self.pending_open = None
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel('样本库')
        title.setProperty('inkRole', 'title')
        heading.addWidget(title)
        heading.addStretch()
        layout.addLayout(heading)
        content = QtWidgets.QSplitter()
        browser = QtWidgets.QWidget()
        browser.setMinimumWidth(250)
        left = QtWidgets.QVBoxLayout(browser)
        left.setContentsMargins(0, 0, 0, 0)
        filters = QtWidgets.QFormLayout()
        self.writer = WriterPicker(catalog, writer, browser)
        self.writer.setAccessibleName('书写者')
        self.character = QtWidgets.QLineEdit()
        self.character.setPlaceholderText('输入字符或 U+ 编码')
        self.category = QtWidgets.QComboBox()
        self.category.addItem('全部类别', '')
        for key, label in CATEGORIES.items():
            self.category.addItem(label, key)
        self.task = QtWidgets.QLineEdit()
        self.task.setPlaceholderText('任务名称或 ID')
        filters.addRow('书写者', self.writer)
        for label, control in (('字符', self.character), ('类别', self.category), ('任务', self.task)):
            control.setAccessibleName(label)
            filters.addRow(label, control)
        left.addLayout(filters)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName('sample_library_list')
        self.table.setAccessibleName('按字符分组的样本列表')
        self.table.setHeaderLabels(['字符 / 样本', '类别 / 份数'])
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setUniformRowHeights(True)
        self.table.setColumnWidth(0, 135)
        left.addWidget(self.table, 1)
        content.addWidget(browser)
        details = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(details)
        column.setContentsMargins(0, 0, 0, 0)
        self.variants = QtWidgets.QComboBox()
        self.variants.setAccessibleName('同字符样本份次')
        self.variants.setPlaceholderText('选择字符后查看样本份次')
        column.addWidget(self.variants)
        self.preview = InkPreview(themed=True)
        self.preview.setAccessibleName('原始笔迹预览')
        self.preview.setProperty('inkRole', 'previewSurface')
        column.addWidget(self.preview, 1)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(145)
        self.details.setAccessibleName('样本来源')
        column.addWidget(self.details)
        content.addWidget(details)
        content.setStretchFactor(0, 1)
        content.setStretchFactor(1, 2)
        layout.addWidget(content, 1)

        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton('刷新')
        self.select_button = QtWidgets.QPushButton('全选筛选结果')
        self.selection_count = QtWidgets.QLabel()
        self.export_button = QtWidgets.QPushButton('导出所选…')
        self.import_button = QtWidgets.QPushButton('导入样本')
        menu = QtWidgets.QMenu(self.import_button)
        menu.addAction('采集包、旧 ZIP 或 JSON…', lambda: self.pick_import(False))
        menu.addAction('样本目录…', lambda: self.pick_import(True))
        self.import_button.setMenu(menu)
        for button in (self.refresh_button, self.select_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        actions.addWidget(self.selection_count)
        actions.addStretch()
        for button in (self.import_button, self.export_button):
            button.setAutoDefault(False)
            heading.addWidget(button)
        layout.addLayout(actions)

        self.refresh_button.clicked.connect(self.refresh)
        self.select_button.clicked.connect(self.select_filtered)
        self.export_button.clicked.connect(self.pick_export)
        self.writer.textChanged.connect(self.refresh)
        self.character.textChanged.connect(self.filter)
        self.category.currentIndexChanged.connect(self.filter)
        self.task.textChanged.connect(self.filter)
        self.table.currentItemChanged.connect(self.show_group)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.variants.currentIndexChanged.connect(self.show_sample)
        if writer:
            self.refresh()
        else:
            self.filter()

    def update_actions(self, *_):
        ready = self.job is None
        self.writer.setEnabled(ready)
        self.refresh_button.setEnabled(ready)
        self.import_button.setEnabled(ready and bool(self.writer.text()))
        self.select_button.setEnabled(ready and bool(self.table.topLevelItemCount()))
        count = len(self.selected_samples())
        self.selection_count.setText(f'已选 {count} 份')
        self.export_button.setEnabled(ready and bool(count))

    def selected_samples(self):
        return tuple(item.data(0, QtCore.Qt.UserRole) for item in self.table.selectedItems()
                     if item.parent() is not None)

    def select_filtered(self):
        with QtCore.QSignalBlocker(self.table):
            for index in range(self.table.topLevelItemCount()):
                group = self.table.topLevelItem(index)
                for child in range(group.childCount()):
                    group.child(child).setSelected(True)
        self.update_actions()

    def submit(self, work, callback, status):
        self.job = Job(lambda _: work())
        self.callback = callback
        self.job.signals.completed.connect(self.completed)
        self.job.signals.failed.connect(self.failed)
        self.status.setText(status)
        self.update_actions()
        QtCore.QThreadPool.globalInstance().start(self.job)

    @QtCore.Slot(object)
    def completed(self, result):
        self.job = None
        self.update_actions()
        self.callback(result)
        self.open_pending()

    @QtCore.Slot(str)
    def failed(self, error):
        self.job = None
        self.update_actions()
        self.status.setText(error)
        self.open_pending()

    def open_pending(self):
        if self.job is None and self.pending_open is not None:
            catalog, writer = self.pending_open
            self.pending_open = None
            self.open_catalog(catalog, writer)

    def open_catalog(self, catalog, writer=None):
        if self.job is not None:
            if (writer is not None or self.pending_open is None
                    or self.pending_open[0].root != catalog.root):
                self.pending_open = (catalog, writer)
            return
        if writer is None:
            writer = self.writer.text() if catalog.root == self.library.catalog.root else ''
        self.library = SampleLibrary(catalog)
        self.writer.catalog = catalog
        self.writer.reload(writer)
        self.refresh()

    def refresh(self, *_):
        if self.job is not None:
            return
        catalog, writer = self.library.catalog, self.writer.text()
        if not writer:
            self.all_rows, self.scan_errors, self.tasks = (), (), {}
            self.filter()
            self.status.setText('请选择书写者。')
            return

        def load():
            rows, errors = inventory(catalog, writer)
            tasks = {entry['task'].task_id: entry['task'].name for entry in catalog.tasks()
                     if entry['task'] and entry['task'].writer_id == writer}
            return rows, errors, tasks

        def display(result):
            self.all_rows, self.scan_errors, self.tasks = result
            self.filter()

        self.submit(load, display, '正在读取样本库…')

    def filter(self, *_):
        query = self.character.text().strip().casefold()
        category = self.category.currentData()
        task = self.task.text().strip().casefold()
        rows = tuple(row for row in self.all_rows
                     if (not category or row.category == category)
                     and (not query or row.character.casefold() in query or query == f'u+{ord(row.character):04x}')
                     and (not task or task in f'{row.task} {self.tasks.get(row.task, "")}'.casefold()))
        current = self.table.currentItem()
        selected = {row.path for row in self.selected_samples()}
        active = current.data(0, QtCore.Qt.UserRole) if current is not None else None
        expanded = {self.table.topLevelItem(i).text(0) for i in range(self.table.topLevelItemCount())
                    if self.table.topLevelItem(i).isExpanded()}
        focused = None
        with QtCore.QSignalBlocker(self.table):
            self.table.clear()
            for char, samples in groupby(rows, key=lambda row: row.character):
                samples = tuple(samples)
                group = QtWidgets.QTreeWidgetItem([f'{char} · U+{ord(char):04X}', f'{len(samples)} 份'])
                group.setFlags(group.flags() & ~QtCore.Qt.ItemIsSelectable)
                self.table.addTopLevelItem(group)
                group.setExpanded(group.text(0) in expanded)
                for number, row in enumerate(samples, 1):
                    item = QtWidgets.QTreeWidgetItem(group, [f'第 {number} 份', CATEGORIES[row.category]])
                    item.setData(0, QtCore.Qt.UserRole, row)
                    item.setSelected(row.path in selected)
                    if active and row.path == active.path:
                        focused = item
            if focused is not None:
                focused.parent().setExpanded(True)
            self.table.setCurrentItem(focused or self.table.topLevelItem(0), 0, QtCore.QItemSelectionModel.NoUpdate)
        self.show_group(self.table.currentItem())
        message = f'{len(rows)} 份符合筛选，共 {len(self.all_rows)} 份'
        if self.scan_errors:
            message += f' · {len(self.scan_errors)} 份无法读取 · {self.scan_errors[0]}'
        if self.job is None:
            self.status.setText(message)
        self.update_actions()

    def show_group(self, current, *_):
        with QtCore.QSignalBlocker(self.variants):
            self.variants.clear()
            if current is not None:
                group = current.parent() or current
                for i in range(group.childCount()):
                    row = group.child(i).data(0, QtCore.Qt.UserRole)
                    self.variants.addItem(f'{row.character} · 第 {i + 1} / {group.childCount()} 份 · {CATEGORIES[row.category]}', row)
                self.variants.setCurrentIndex(group.indexOfChild(current) if current.parent() else 0)
        self.variants.setEnabled(self.variants.count() > 1)
        self.show_sample()

    def show_sample(self, *_):
        self.preview.value = None
        self.details.clear()
        row = self.variants.currentData()
        if row is not None:
            try:
                self.preview.value = read_row(row)
                origin = row.origin or (row.writer, row.sample_id, row.raw_hash)
                task = self.tasks.get(row.task, '')
                self.details.setPlainText(f'{row.character}  U+{ord(row.character):04X}\n'
                                          f'库内书写者 {row.writer}\n样本 ID {row.sample_id}\n'
                                          f'原始任务 {task + " · " if task else ""}{row.task or "未记录"}\n'
                                          f'录制时间 {row.captured or "未记录"}\n原书写者 {origin[0]}\n'
                                          f'原样本 ID {origin[1]}\nSHA-256 {origin[2]}\n{row.path}')
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                self.details.setPlainText(str(error))
        self.preview.update()

    def pick_export(self):
        rows = sorted(self.selected_samples(), key=lambda row: (row.character, row.captured, row.sample_id))
        writer = self.writer.text()
        if not rows:
            return
        name = self.library.catalog.writers()[writer]['name']
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, '导出所选样本', writer + '.inkcapture',
                                                        'InkStruct 采集包 (*.inkcapture)')
        if path:
            path = Path(path)
            if path.suffix.lower() != '.inkcapture':
                path = path.with_suffix('.inkcapture')
            self.submit(lambda: export_bundle(path, writer, name, rows),
                        lambda count: self.status.setText(f'已导出 {count} 份 · {path}'), '正在导出原始样本…')

    def pick_import(self, directory):
        if directory:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, '选择样本目录')
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '选择采集包或旧样本', '',
                                                            '样本 (*.inkcapture *.zip *.json)')
        if path:
            self.preview_import(path)

    def preview_import(self, path):
        writer = self.writer.text()

        def inspect():
            bundle = open_source(path)
            return bundle, self.library.review(bundle, writer)

        self.submit(inspect, lambda data: self.confirm_import(writer, *data), '正在校验来源并比对目标库…')

    def confirm_import(self, writer, bundle, review):
        try:
            name = self.library.catalog.writers()[writer]['name']
        except (KeyError, OSError, ValueError):
            self.failed('目标书写者已变化，请刷新并重新选择。')
            return
        origins = '、'.join(sorted({sample.row.writer for sample in bundle.samples}))
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle('核对样本及书写者归属')
        box.setTextFormat(QtCore.Qt.PlainText)
        box.setText(f'来源书写者 {bundle.name}（{bundle.writer}）\n原始样本书写者 {origins}\n'
                    f'目标书写者 {name}（{writer}）\n\n新增 {len(review.new)} · 重复 {len(review.duplicates)}'
                    f' · 冲突 {len(review.conflicts)}\n\n确认新增样本均由目标书写者录制。重复和冲突项会跳过。')
        headings = (('新增', (item.row for item in review.new)), ('重复', review.duplicates), ('冲突', review.conflicts))
        box.setDetailedText('\n'.join(f'{label} · {row.character} · {row.writer} · {row.sample_id}'
                                      for label, rows in headings for row in rows))
        buttons = QtWidgets.QMessageBox.StandardButton
        box.setStandardButtons(buttons.Yes | buttons.Cancel if review.new else buttons.Close)
        box.setDefaultButton(buttons.Cancel if review.new else buttons.Close)
        if review.new:
            box.button(buttons.Yes).setText('确认并导入新增样本')
        if box.exec() == buttons.Yes and review.new:
            self.submit(lambda: self.library.import_confirmed(bundle, writer, review), self.imported,
                        '正在保存样本及原始来源…')

    def imported(self, count):
        self.refresh()
        self.status.setText(f'已导入 {count} 份新样本，正在刷新…')


class SampleLibraryDialog(QtWidgets.QDialog):
    """Standalone collector uses the same library when there is no app sidebar."""

    def __init__(self, catalog, writer='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('样本库')
        self.resize(980, 620)
        layout = QtWidgets.QVBoxLayout(self)
        self.page = SampleLibraryPage(catalog, writer, self)
        layout.addWidget(self.page)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def reject(self):
        if self.page.job is None:
            super().reject()
