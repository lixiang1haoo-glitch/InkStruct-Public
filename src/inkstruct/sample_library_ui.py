"""Windows capture sample browser and offline exchange."""

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .capture_workflow_ui import WriterPicker
from .fonts.ui import Job
from .sample_library import CATEGORIES, SampleLibrary, export_bundle, inventory, open_source, read_row
from .symbol_review_dialog import InkPreview


class SampleRows(QtCore.QAbstractTableModel):
    headers = ('字符', '类别', '任务', '录制时间', '来源')

    def __init__(self, parent):
        super().__init__(parent)
        self.rows = ()
        self.tasks = {}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role):
        if index.isValid() and role == QtCore.Qt.DisplayRole:
            row = self.rows[index.row()]
            return (row.character, CATEGORIES[row.category], self.tasks.get(row.task, row.task) or '—',
                    row.captured, row.origin[0] if row.origin else '原始采集')[index.column()]
        return None

    def update_rows(self, rows, tasks):
        self.beginResetModel()
        self.rows, self.tasks = rows, tasks
        self.endResetModel()


class SampleLibraryDialog(QtWidgets.QDialog):
    def __init__(self, catalog, writer='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('样本库')
        self.resize(980, 620)
        self.library = SampleLibrary(catalog)
        self.all_rows, self.tasks = (), {}
        self.scan_errors = ()
        self.job = None
        layout = QtWidgets.QVBoxLayout(self)
        filters = QtWidgets.QFormLayout()
        self.writer = WriterPicker(catalog, writer, self)
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
        layout.addLayout(filters)

        content = QtWidgets.QSplitter()
        self.model = SampleRows(self)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(2, 155)
        self.table.setColumnWidth(3, 175)
        content.addWidget(self.table)
        details = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(details)
        self.preview = InkPreview()
        column.addWidget(self.preview, 1)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(145)
        self.details.setAccessibleName('样本来源')
        column.addWidget(self.details)
        content.addWidget(details)
        content.setStretchFactor(0, 2)
        content.setStretchFactor(1, 1)
        layout.addWidget(content, 1)

        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton('刷新')
        self.select_button = QtWidgets.QPushButton('全选筛选结果')
        self.export_button = QtWidgets.QPushButton('导出所选…')
        self.import_button = QtWidgets.QPushButton('导入样本')
        menu = QtWidgets.QMenu(self.import_button)
        menu.addAction('采集包、旧 ZIP 或 JSON…', lambda: self.pick_import(False))
        menu.addAction('样本目录…', lambda: self.pick_import(True))
        self.import_button.setMenu(menu)
        close = QtWidgets.QPushButton('关闭')
        for button in (self.refresh_button, self.select_button, self.export_button, self.import_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)

        self.refresh_button.clicked.connect(self.refresh)
        self.select_button.clicked.connect(self.table.selectAll)
        self.export_button.clicked.connect(self.pick_export)
        close.clicked.connect(self.reject)
        self.writer.textChanged.connect(self.refresh)
        self.character.textChanged.connect(self.filter)
        self.category.currentIndexChanged.connect(self.filter)
        self.task.textChanged.connect(self.filter)
        self.table.selectionModel().currentRowChanged.connect(self.show_sample)
        self.table.selectionModel().selectionChanged.connect(self.update_actions)
        self.refresh()

    def update_actions(self, *_):
        ready = self.job is None
        self.writer.setEnabled(ready)
        self.refresh_button.setEnabled(ready)
        self.import_button.setEnabled(ready and bool(self.writer.text()))
        self.select_button.setEnabled(ready and bool(self.model.rows))
        self.export_button.setEnabled(ready and self.table.selectionModel().hasSelection())

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

    @QtCore.Slot(str)
    def failed(self, error):
        self.job = None
        self.update_actions()
        self.status.setText(error)

    def reject(self):
        if self.job is None:
            super().reject()

    def refresh(self, *_):
        if self.job is not None:
            return
        catalog, writer = self.library.catalog, self.writer.text()

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
        self.model.update_rows(rows, self.tasks)
        self.show_sample(QtCore.QModelIndex())
        message = f'{len(rows)} 份符合筛选，共 {len(self.all_rows)} 份'
        if self.scan_errors:
            message += f' · {len(self.scan_errors)} 份无法读取 · {self.scan_errors[0]}'
        if self.job is None:
            self.status.setText(message)
        self.update_actions()

    def show_sample(self, current, *_):
        self.preview.value = None
        self.details.clear()
        if current.isValid():
            row = self.model.rows[current.row()]
            try:
                self.preview.value = read_row(row)
                origin = row.origin or (row.writer, row.sample_id, row.raw_hash)
                self.details.setPlainText(f'{row.character}  U+{ord(row.character):04X}\n'
                                          f'库内书写者 {row.writer}\n样本 ID {row.sample_id}\n'
                                          f'任务 {row.task or "未记录"}\n原书写者 {origin[0]}\n'
                                          f'原样本 ID {origin[1]}\nSHA-256 {origin[2]}\n{row.path}')
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                self.details.setPlainText(str(error))
        self.preview.update()

    def pick_export(self):
        selected = self.table.selectionModel().selectedRows()
        rows = tuple(self.model.rows[index.row()] for index in sorted(selected, key=lambda i: i.row()))
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
