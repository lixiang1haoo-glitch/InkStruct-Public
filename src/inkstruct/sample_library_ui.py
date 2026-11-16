"""Windows capture sample browser and offline exchange."""

from collections import Counter
from datetime import datetime
from functools import lru_cache
from itertools import groupby
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .capture_workflow_ui import WriterPicker
from .fonts.ui import Job
from .sample_library import CATEGORIES, SampleLibrary, export_bundle, inventory, open_source, read_row
from .sample_preview import SampleDrawing, SamplePreview, SampleView


Qt = QtCore.Qt
THUMBNAIL_SIZE = 36
PREVIEW_SIZE = 224
MIN_PREVIEW_SIZE = 136
SOURCE_WIDTH = 250
READ_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError)


def sample_key(row):
    return row.path, row.raw_hash


def local_time(raw):
    try:
        return datetime.fromisoformat(raw).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError, OverflowError):
        return raw or '未记录'


def plain_label(text='', *, role=None, selectable=False):
    label = QtWidgets.QLabel(text)
    label.setTextFormat(Qt.PlainText)
    if role:
        label.setProperty('inkRole', role)
    if selectable:
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
    return label


class LibraryWriterPicker(WriterPicker):
    def reload(self, selected=''):
        super().reload(selected)
        names = [self.itemText(i).rsplit(' · ', 1)[0] for i in range(1, self.count())]
        counts = Counter(names)
        with QtCore.QSignalBlocker(self):
            for index, name in enumerate(names, 1):
                if counts[name] == 1:
                    self.setItemText(index, name)


class CheckScope(QtWidgets.QCheckBox):
    def nextCheckState(self):
        self.setChecked(self.checkState() != Qt.Checked)


class IndependentChecks:
    """Toggle the check cell without moving the view's preview selection."""

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and self.is_check_hit(index, event.position().toPoint()):
            self.check_press = QtCore.QPersistentModelIndex(index)
            event.accept()
            return
        self.check_press = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed = getattr(self, 'check_press', None)
        self.check_press = None
        if pressed is not None and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            if index == pressed and self.is_check_hit(index, pos):
                self.toggle_check(index)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint()
        if event.button() == Qt.LeftButton and self.is_check_hit(self.indexAt(pos), pos):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.currentIndex().isValid():
            self.toggle_check(self.currentIndex())
            event.accept()
            return
        super().keyPressEvent(event)


class CharacterDirectory(IndependentChecks, QtWidgets.QTreeWidget):
    def is_check_hit(self, index, pos):
        return index.isValid() and index.column() == 0

    def toggle_check(self, index):
        item = self.itemFromIndex(index)
        item.setCheckState(0, Qt.Checked if item.checkState(0) != Qt.Checked else Qt.Unchecked)


class SampleCheckDelegate(QtWidgets.QStyledItemDelegate):
    def check_rect(self, view, index):
        option = QtWidgets.QStyleOptionViewItem()
        view.initViewItemOption(option)
        option.rect = view.visualRect(index)
        self.initStyleOption(option, index)
        return view.style().subElementRect(QtWidgets.QStyle.SE_ItemViewItemCheckIndicator, option, view)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        state = index.data(Qt.CheckStateRole)
        if state not in (Qt.Unchecked, Qt.Unchecked.value):
            return
        style_option = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        widget = option.widget
        if widget is None:
            return
        rect = widget.style().subElementRect(QtWidgets.QStyle.SE_ItemViewItemCheckIndicator, style_option, widget)
        role = (QtGui.QPalette.HighlightedText if option.state & QtWidgets.QStyle.State_Selected
                else QtGui.QPalette.Text)
        color = option.palette.color(role)
        color.setAlpha(125)
        painter.save()
        painter.setPen(color)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -2, -2), 2, 2)
        painter.restore()


class VariantStrip(IndependentChecks, QtWidgets.QListWidget):
    def is_check_hit(self, index, pos):
        return index.isValid() and self.itemDelegate().check_rect(self, index).contains(pos)

    def toggle_check(self, index):
        item = self.item(index.row())
        item.setCheckState(Qt.Checked if item.checkState() != Qt.Checked else Qt.Unchecked)


class VariantItem(QtWidgets.QListWidgetItem):
    def __init__(self, label, row, library):
        super().__init__(label)
        self.setData(Qt.UserRole, row)
        self.setCheckState(Qt.Unchecked)
        self.library = library
        self.thumbnail = None

    def data(self, role):
        if role == Qt.DecorationRole:
            if self.thumbnail is None:
                self.thumbnail = self.library.thumbnail(super().data(Qt.UserRole))
            return self.thumbnail
        return super().data(role)


def sample_form(fields):
    widget = QtWidgets.QWidget()
    form = QtWidgets.QGridLayout(widget)
    form.setContentsMargins(0, 0, 0, 0)
    form.setColumnStretch(1, 1)
    values = {}
    for row, (key, name) in enumerate(fields):
        label = plain_label(name)
        value = plain_label(selectable=True)
        value.setWordWrap(True)
        value.setMinimumWidth(0)
        value.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        value.setAccessibleName(name)
        form.addWidget(label, row, 0, Qt.AlignTop)
        form.addWidget(value, row, 1)
        values[key] = value
    return widget, values


class SampleLibraryPage(QtWidgets.QWidget):
    def __init__(self, catalog, writer='', parent=None):
        super().__init__(parent)
        self.setObjectName('sample_library')
        self.library = SampleLibrary(catalog)
        self.all_rows, self.tasks = (), {}
        self.scan_errors = ()
        self.scan_in_progress = False
        self.scan_failed = False
        self.rows_scope = None
        self.checked_by_scope = {}
        self.visible_rows = ()
        self.groups = {}
        self.numbers = {}
        self.active_row = None
        self.read_preview = lru_cache(maxsize=96)(read_row)
        self.job = None
        self.pending_open = None
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(plain_label('样本库', role='title'))
        heading.addStretch()
        self.refresh_button = QtWidgets.QPushButton('刷新')
        self.import_button = QtWidgets.QPushButton('导入样本')
        menu = QtWidgets.QMenu(self.import_button)
        menu.addAction('采集包、旧 ZIP 或 JSON…', lambda: self.pick_import(False))
        menu.addAction('样本目录…', lambda: self.pick_import(True))
        self.import_button.setMenu(menu)
        heading.addWidget(self.refresh_button)
        heading.addWidget(self.import_button)
        layout.addLayout(heading)

        self.filters = QtWidgets.QGridLayout()
        self.writer = LibraryWriterPicker(catalog, writer, self)
        self.writer.setMinimumContentsLength(12)
        self.character = QtWidgets.QLineEdit()
        self.character.setPlaceholderText('输入字符或 U+ 编码')
        self.character.setClearButtonEnabled(True)
        self.category = QtWidgets.QComboBox()
        self.category.addItem('全部类别', '')
        for key, label in CATEGORIES.items():
            self.category.addItem(label, key)
        self.task = QtWidgets.QLineEdit()
        self.task.setPlaceholderText('全部任务 · 名称或 ID')
        self.task.setClearButtonEnabled(True)
        self.task_model = QtCore.QStringListModel(self)
        task_completer = QtWidgets.QCompleter(self.task_model, self.task)
        task_completer.setCaseSensitivity(Qt.CaseInsensitive)
        task_completer.setFilterMode(Qt.MatchContains)
        self.task.setCompleter(task_completer)
        self.filter_fields = []
        for label, control in (('书写者', self.writer), ('查找字符', self.character),
                               ('类别', self.category), ('采集任务', self.task)):
            control.setAccessibleName(label)
            caption = plain_label(label)
            caption.setBuddy(control)
            self.filter_fields.append((caption, control))
        self.filter_columns = 0
        self.place_filters(4)
        layout.addLayout(self.filters)

        content = QtWidgets.QSplitter(Qt.Horizontal)
        content.setChildrenCollapsible(False)
        browser = QtWidgets.QWidget()
        browser.setMinimumWidth(175)
        browser.setMaximumWidth(480)
        left = QtWidgets.QVBoxLayout(browser)
        left.setContentsMargins(0, 0, 0, 0)
        browser_heading = QtWidgets.QHBoxLayout()
        browser_heading.addWidget(plain_label('字符目录', role='sectionTitle'))
        browser_heading.addStretch()
        self.catalog_count = plain_label(role='hint')
        browser_heading.addWidget(self.catalog_count)
        left.addLayout(browser_heading)
        self.select_button = CheckScope('全选筛选结果')
        left.addWidget(self.select_button)
        self.table = CharacterDirectory()
        self.table.setObjectName('sample_library_list')
        self.table.setAccessibleName('字符目录。空格键勾选当前字符的筛选结果')
        self.table.setHeaderLabels(['', '字符', '样本'])
        self.table.setRootIsDecorated(False)
        self.table.setItemsExpandable(False)
        self.table.setAllColumnsShowFocus(True)
        self.table.setUniformRowHeights(True)
        self.table.setItemDelegate(SampleCheckDelegate(self.table))
        self.table.header().setMinimumSectionSize(28)
        self.table.header().setStretchLastSection(False)
        self.table.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.table.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.header().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 34)
        left.addWidget(self.table, 1)
        content.addWidget(browser)

        self.inspector = QtWidgets.QScrollArea()
        self.inspector.setWidgetResizable(True)
        self.inspector.setFrameShape(QtWidgets.QFrame.NoFrame)
        inspector_panel = QtWidgets.QWidget()
        self.inspector.setWidget(inspector_panel)
        panel = QtWidgets.QVBoxLayout(inspector_panel)
        panel.setContentsMargins(10, 0, 4, 0)
        self.inspector_margins = panel.contentsMargins()
        self.preview_message = plain_label()
        self.preview_message.setAlignment(Qt.AlignCenter)
        self.preview_message.setWordWrap(True)
        panel.addWidget(self.preview_message, 1)
        self.detail_panel = QtWidgets.QWidget()
        panel.addWidget(self.detail_panel)
        panel.addStretch()
        column = self.detail_layout = QtWidgets.QVBoxLayout(self.detail_panel)
        column.setContentsMargins(0, 0, 0, 0)
        preview_heading = QtWidgets.QHBoxLayout()
        self.active_character = plain_label(role='title')
        self.variant_count = plain_label(role='hint')
        self.guides = QtWidgets.QCheckBox('参考线')
        self.guides.setChecked(True)
        self.guides.setToolTip('显示采集画布边界和书写参考线')
        self.preview_view = SampleView(self)
        self.zoom_button = QtWidgets.QToolButton()
        self.zoom_button.setText('100%')
        self.zoom_button.setMinimumWidth(53)
        self.zoom_button.setToolTip('Ctrl + 滚轮缩放 · 点击恢复采集比例')
        self.zoom_button.setAccessibleDescription('点击恢复采集比例和位置')
        self.zoom_button.clicked.connect(self.preview_view.reset)
        self.preview_view.changed.connect(self.update_zoom_label)
        self.compare_button = QtWidgets.QPushButton('并排比较')
        self.compare_button.setCheckable(True)
        preview_heading.addWidget(self.active_character)
        preview_heading.addWidget(self.variant_count)
        preview_heading.addStretch()
        preview_heading.addWidget(self.zoom_button)
        preview_heading.addWidget(self.guides)
        preview_heading.addWidget(self.compare_button)
        column.addLayout(preview_heading)

        self.review = QtWidgets.QGridLayout()
        column.addLayout(self.review)
        self.review.setColumnStretch(1, 1)
        boards = QtWidgets.QWidget()
        boards_layout = QtWidgets.QHBoxLayout(boards)
        boards_layout.setContentsMargins(0, 0, 0, 0)
        primary = QtWidgets.QVBoxLayout()
        primary_row = QtWidgets.QHBoxLayout()
        self.primary_label = plain_label(role='sectionTitle')
        primary_row.addWidget(self.primary_label)
        primary_row.addStretch()
        primary.addLayout(primary_row)
        self.preview = SamplePreview(self.preview_view)
        self.preview.setAccessibleName('原始笔迹预览')
        self.preview.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        primary.addWidget(self.preview)
        boards_layout.addLayout(primary)
        self.compare_panel = QtWidgets.QWidget()
        comparison = QtWidgets.QVBoxLayout(self.compare_panel)
        comparison.setContentsMargins(0, 0, 0, 0)
        counterpart_row = QtWidgets.QHBoxLayout()
        self.counterpart = QtWidgets.QComboBox()
        self.counterpart.setAccessibleName('对照样本')
        self.counterpart.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.counterpart.setMinimumContentsLength(5)
        counterpart_row.addWidget(plain_label('对照样本'))
        counterpart_row.addWidget(self.counterpart, 1)
        comparison.addLayout(counterpart_row)
        self.compare_preview = SamplePreview(self.preview_view)
        self.compare_preview.setAccessibleName('对照笔迹预览')
        self.compare_preview.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        comparison.addWidget(self.compare_preview)
        primary_row.addStrut(self.counterpart.sizeHint().height())
        boards_layout.addWidget(self.compare_panel)
        self.review.addWidget(boards, 0, 0, Qt.AlignLeft | Qt.AlignTop)

        self.source_box = QtWidgets.QGroupBox('样本信息')
        self.source_below = None
        self.source_box.setMinimumWidth(SOURCE_WIDTH)
        self.source_box.setMaximumWidth(390)
        self.source_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        source_layout = QtWidgets.QVBoxLayout(self.source_box)
        source_panel, self.source_fields = sample_form((
            ('writer', '库内书写者'), ('task', '采集任务'), ('time', '录制时间'), ('origin', '来源')))
        source_layout.addWidget(source_panel)
        self.technical_button = QtWidgets.QToolButton()
        self.technical_button.setText('技术详情')
        self.technical_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.technical_button.setCheckable(True)
        self.technical_button.setArrowType(Qt.RightArrow)
        source_layout.addWidget(self.technical_button, 0, Qt.AlignLeft)
        self.technical_panel, self.technical_fields = sample_form((
            ('codepoint', '字符编码'), ('sample', '样本 ID'), ('writer', '原始书写者 ID'),
            ('task', '原始任务 ID'), ('origin', '原始样本 ID'), ('hash', '原始 SHA-256'),
            ('path', '文件位置')))
        self.technical_panel.hide()
        source_layout.addWidget(self.technical_panel)
        self.preview_warning = plain_label(role='hint', selectable=True)
        self.preview_warning.setWordWrap(True)
        column.addWidget(self.preview_warning)

        self.variants_label = plain_label('同字样本', role='sectionTitle')
        column.addWidget(self.variants_label)
        self.variants = VariantStrip()
        self.variants.setAccessibleName('同字样本。空格键勾选当前样本')
        self.variants.setFlow(QtWidgets.QListView.LeftToRight)
        self.variants.setWrapping(False)
        self.variants.setSpacing(4)
        self.variants.setUniformItemSizes(True)
        self.variants.setIconSize(QtCore.QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.variants.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.variants.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.variants.setItemDelegate(SampleCheckDelegate(self.variants))
        self.variants.setFixedHeight(THUMBNAIL_SIZE + 34)
        column.addWidget(self.variants)
        self.single_check = QtWidgets.QCheckBox('勾选此样本')
        column.addWidget(self.single_check, 0, Qt.AlignLeft)
        content.addWidget(self.inspector)
        content.setStretchFactor(0, 0)
        content.setStretchFactor(1, 1)
        content.setSizes([260, 760])
        layout.addWidget(content, 1)

        self.status = plain_label(role='status')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.HLine)
        layout.addWidget(divider)
        actions = QtWidgets.QHBoxLayout()
        self.selection_count = plain_label()
        self.selection_count.setWordWrap(True)
        self.clear_button = QtWidgets.QPushButton('清空勾选')
        self.export_button = QtWidgets.QPushButton('导出所选…')
        self.export_button.setProperty('inkRole', 'primary')
        actions.addWidget(self.selection_count)
        actions.addStretch()
        for button in (self.clear_button, self.export_button):
            actions.addWidget(button)
        for button in (self.refresh_button, self.import_button, self.compare_button, self.clear_button, self.export_button):
            button.setAutoDefault(False)
        layout.addLayout(actions)

        self.refresh_button.clicked.connect(self.refresh)
        self.select_button.clicked.connect(self.select_filtered)
        self.clear_button.clicked.connect(self.clear_selected)
        self.export_button.clicked.connect(self.pick_export)
        self.writer.textChanged.connect(self.refresh)
        self.character.textChanged.connect(self.filter)
        self.category.currentIndexChanged.connect(self.filter)
        self.task.textChanged.connect(self.filter)
        self.table.currentItemChanged.connect(self.show_group)
        self.table.itemChanged.connect(self.check_group)
        self.variants.currentItemChanged.connect(self.show_sample)
        self.variants.itemChanged.connect(self.check_variant)
        self.single_check.clicked.connect(self.check_single)
        self.compare_button.toggled.connect(self.show_sample)
        self.counterpart.currentIndexChanged.connect(self.paint_comparison)
        self.guides.toggled.connect(self.paint_comparison)
        self.technical_button.toggled.connect(self.show_technical)
        self.inspector.viewport().installEventFilter(self)
        self.refresh()

    def place_filters(self, columns):
        if self.filter_columns == columns:
            return
        self.filter_columns = columns
        while self.filters.count():
            self.filters.takeAt(0)
        for index, (label, control) in enumerate(self.filter_fields):
            row, column = divmod(index, columns)
            self.filters.addWidget(label, row * 2, column)
            self.filters.addWidget(control, row * 2 + 1, column)
            self.filters.setColumnStretch(index, 2 if index < columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_filters(4 if event.size().width() >= 650 else 2)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Resize and watched is self.inspector.viewport():
            self.layout_preview()
        return super().eventFilter(watched, event)

    def layout_preview(self):
        comparing = self.counterpart.currentIndex() >= 0
        margins = self.inspector_margins
        available = self.inspector.viewport().width() - margins.left() - margins.right()
        spacing = max(8, self.review.horizontalSpacing())
        below = comparing or available < PREVIEW_SIZE + SOURCE_WIDTH + spacing
        if comparing:
            available = (available - spacing) // 2
        elif not below:
            available -= SOURCE_WIDTH + spacing
        size = min(PREVIEW_SIZE, max(MIN_PREVIEW_SIZE, available))
        if self.preview.width() != size:
            self.preview.setFixedSize(size, size)
            self.compare_preview.setFixedSize(size, size)
        if below == self.source_below:
            return
        self.source_below = below
        self.review.removeWidget(self.source_box)
        self.detail_layout.removeWidget(self.source_box)
        if below:
            self.detail_layout.addWidget(self.source_box, 0, Qt.AlignLeft | Qt.AlignTop)
        else:
            self.review.addWidget(self.source_box, 0, 1, Qt.AlignLeft | Qt.AlignTop)

    def update_actions(self):
        ready = self.job is None
        self.writer.setEnabled(ready)
        self.refresh_button.setEnabled(ready)
        self.import_button.setEnabled(ready and bool(self.writer.text()))
        self.select_button.setEnabled(bool(self.visible_rows))
        count, hidden = self.selection_summary()
        suffix = f' · 含 {hidden} 份在当前筛选之外' if hidden else ''
        self.selection_count.setText(f'已勾选 {count} 份{suffix}')
        self.clear_button.setVisible(bool(count))
        self.export_button.setText(f'导出所选 {count} 份…' if count else '导出所选…')
        self.export_button.setEnabled(ready and bool(count))

    def scope(self):
        return self.library.catalog.root, self.writer.text()

    def selected_keys(self):
        if self.rows_scope != self.scope():
            return set()
        return self.checked_by_scope.setdefault(self.rows_scope, set())

    def selected_samples(self):
        checked = self.selected_keys()
        return tuple(row for row in self.all_rows if sample_key(row) in checked)

    def selection_summary(self):
        checked = self.selected_keys()
        return len(checked), len(checked.difference(map(sample_key, self.visible_rows)))

    def sync_checks(self):
        checked = self.selected_keys()

        def check_state(rows):
            count = sum(sample_key(row) in checked for row in rows)
            if count == 0:
                return Qt.Unchecked
            return Qt.Checked if count == len(rows) else Qt.PartiallyChecked

        with QtCore.QSignalBlocker(self.select_button):
            self.select_button.setCheckState(check_state(self.visible_rows))
        with QtCore.QSignalBlocker(self.table):
            for index in range(self.table.topLevelItemCount()):
                item = self.table.topLevelItem(index)
                item.setCheckState(0, check_state(self.groups[item.text(1)]))
        with QtCore.QSignalBlocker(self.variants):
            for index in range(self.variants.count()):
                item = self.variants.item(index)
                item.setCheckState(check_state((item.data(Qt.UserRole),)))
        with QtCore.QSignalBlocker(self.single_check):
            self.single_check.setChecked(bool(self.active_row and sample_key(self.active_row) in checked))
        self.update_actions()

    def set_selected(self, rows, selected):
        checked = self.selected_keys()
        if selected:
            checked.update(map(sample_key, rows))
        else:
            checked.difference_update(map(sample_key, rows))
        self.sync_checks()

    def select_filtered(self, checked):
        self.set_selected(self.visible_rows, checked)

    def clear_selected(self):
        self.selected_keys().clear()
        self.sync_checks()
        self.character.setFocus()

    def check_group(self, item, column):
        if column == 0:
            self.set_selected(self.groups[item.text(1)], item.checkState(0) == Qt.Checked)

    def check_variant(self, item):
        self.set_selected((item.data(Qt.UserRole),), item.checkState() == Qt.Checked)

    def check_single(self, checked):
        if self.active_row is not None:
            self.set_selected((self.active_row,), checked)

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
        if self.scan_in_progress:
            self.scan_in_progress = False
            self.scan_failed = True
            self.update_preview_message()
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
        scope = self.scope()
        self.scan_in_progress = bool(writer)
        self.scan_failed = False
        self.read_preview.cache_clear()
        if self.rows_scope != scope:
            self.rows_scope = None
            self.all_rows, self.scan_errors, self.tasks = (), (), {}
            self.numbers = {}
            self.task_model.setStringList([])
            self.filter()
        if not writer:
            self.status.setText('请选择书写者。')
            return

        def load():
            rows, errors = inventory(catalog, writer)
            tasks = {entry['task'].task_id: entry['task'].name for entry in catalog.tasks()
                     if entry['task'] and entry['task'].writer_id == writer}
            return rows, errors, tasks

        def display(result):
            self.scan_in_progress = False
            self.rows_scope = scope
            self.all_rows, self.scan_errors, self.tasks = result
            self.selected_keys().intersection_update(map(sample_key, self.all_rows))
            self.numbers = {
                sample_key(row): number
                for _, group in groupby(self.all_rows, key=lambda row: row.character)
                for number, row in enumerate(group, 1)
            }
            self.task_model.setStringList(sorted(set(self.tasks.values())))
            self.filter()

        self.update_preview_message()
        self.submit(load, display, '')

    def filter(self, *_):
        query = self.character.text().strip().casefold()
        category = self.category.currentData()
        task = self.task.text().strip().casefold()
        self.visible_rows = tuple(
            row for row in self.all_rows
            if (not category or row.category == category)
            and (not query or row.character.casefold() in query or query == f'u+{ord(row.character):04x}')
            and (not task or task in f'{row.task} {self.tasks.get(row.task, "")}'.casefold())
        )
        self.groups = {char: tuple(rows) for char, rows in groupby(self.visible_rows, key=lambda row: row.character)}
        active = self.active_row.character if self.active_row is not None else None
        char_font = self.table.font()
        char_font.setPointSizeF(max(char_font.pointSizeF(), 9) + 2)
        focused = None
        with QtCore.QSignalBlocker(self.table):
            self.table.clear()
            for char, samples in self.groups.items():
                group = QtWidgets.QTreeWidgetItem(['', char, str(len(samples))])
                group.setFont(1, char_font)
                group.setSizeHint(1, QtCore.QSize(0, 30))
                group.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                group.setToolTip(0, f'勾选「{char}」在当前筛选内的 {len(samples)} 份样本')
                group.setToolTip(1, f'{char} · U+{ord(char):04X}')
                group.setCheckState(0, Qt.Unchecked)
                self.table.addTopLevelItem(group)
                if char == active:
                    focused = group
            if self.groups:
                self.table.setCurrentItem(focused or self.table.topLevelItem(0), 1)
        self.show_group(self.table.currentItem())
        self.catalog_count.setText(f'{len(self.groups)} 字 · {len(self.visible_rows)} 份')
        message = f'库中共 {len(self.all_rows)} 份'
        if self.scan_errors:
            message += f' · {len(self.scan_errors)} 份无法读取 · {self.scan_errors[0]}'
        if self.job is None and not self.scan_in_progress:
            self.status.setText(message)

    def show_group(self, current, *_):
        group = self.groups[current.text(1)] if current is not None else ()
        active = None
        with QtCore.QSignalBlocker(self.variants):
            self.variants.clear()
            for row in group:
                tile = VariantItem(self.variant_name(row), row, self)
                tile.setToolTip(f'{tile.text()} · {self.tasks.get(row.task) or row.task or "未记录任务"}'
                                f' · {local_time(row.captured)}')
                self.variants.addItem(tile)
                if self.active_row == row:
                    active = tile
            if group:
                self.variants.setCurrentItem(active or self.variants.item(0))
        has_variants = len(group) > 1
        self.variants_label.setVisible(has_variants)
        self.variants.setVisible(has_variants)
        self.single_check.setVisible(len(group) == 1)
        self.compare_button.setVisible(has_variants)
        if not has_variants:
            with QtCore.QSignalBlocker(self.compare_button):
                self.compare_button.setChecked(False)
        self.show_sample()
        self.update_preview_message()

    def update_preview_message(self):
        show_preview = self.active_row is not None and not self.scan_in_progress
        self.detail_panel.setVisible(show_preview)
        self.preview_message.setVisible(not show_preview)
        if show_preview:
            return
        if self.scan_in_progress:
            message = '正在读取样本库…'
        elif self.scan_failed or (self.scan_errors and not self.all_rows):
            message = '无法读取样本库'
        elif not self.writer.text():
            message = '选择书写者以查看样本'
        elif self.all_rows:
            message = '没有符合筛选条件的样本'
        else:
            message = '此书写者的样本库为空'
        self.preview_message.setText(message)

    def variant_name(self, row):
        return f'样本 {self.numbers[sample_key(row)]}'

    def thumbnail(self, row):
        try:
            value = self.read_preview(row)
        except READ_ERRORS:
            return QtGui.QIcon()
        size = THUMBNAIL_SIZE
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        try:
            SampleDrawing(value).paint_thumbnail(painter, QtCore.QRectF(0, 0, size, size), self.palette())
        finally:
            painter.end()
        return QtGui.QIcon(pixmap)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.PaletteChange and hasattr(self, 'variants'):
            for index in range(self.variants.count()):
                self.variants.item(index).thumbnail = None
            self.variants.viewport().update()

    def show_sample(self, *_):
        item = self.variants.currentItem()
        row = item.data(Qt.UserRole) if item is not None else None
        previous = self.active_row
        old_counterpart = self.counterpart.currentData()
        if old_counterpart == row:
            old_counterpart = self.active_row
        self.active_row = row
        with QtCore.QSignalBlocker(self.counterpart):
            self.counterpart.clear()
            if row is not None and self.compare_button.isChecked():
                for other in self.groups[row.character]:
                    if other != row:
                        self.counterpart.addItem(self.variant_name(other), other)
                index = self.counterpart.findData(old_counterpart)
                self.counterpart.setCurrentIndex(max(0, index))
        if row is not None:
            self.active_character.setText(row.character)
            self.variant_count.setText(f'{len(self.groups[row.character])} 份 · {CATEGORIES[row.category]}')
            self.show_source(row)
        reset_view = (previous is None or row is None
                      or (previous.writer, previous.character) != (row.writer, row.character))
        self.paint_comparison(reset_view=reset_view)
        self.sync_checks()

    def show_source(self, row):
        origin = row.origin or (row.writer, row.sample_id, row.raw_hash)
        summary = {
            'writer': self.writer.currentText(),
            'task': self.tasks.get(row.task) or row.task or '未记录',
            'time': local_time(row.captured),
            'origin': '导入样本' if row.origin else '本地记录',
        }
        technical = {
            'codepoint': f'U+{ord(row.character):04X}', 'sample': row.sample_id, 'writer': origin[0],
            'task': row.task or '未记录', 'origin': origin[1], 'hash': origin[2], 'path': str(row.path),
        }
        for fields, values in ((self.source_fields, summary), (self.technical_fields, technical)):
            for key, label in fields.items():
                label.setText(values[key])

    def show_technical(self, expanded):
        self.technical_panel.setVisible(expanded)
        self.technical_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def update_zoom_label(self):
        self.zoom_button.setText(f'{self.preview_view.zoom:.0%}')

    def paint_comparison(self, *_, reset_view=False):
        row, other = self.active_row, self.counterpart.currentData()
        notices = []
        for preview, sample in ((self.preview, row), (self.compare_preview, other)):
            preview.guides = self.guides.isChecked()
            value = None
            if sample is not None:
                try:
                    value = self.read_preview(sample)
                except READ_ERRORS as error:
                    notices.append(f'{self.variant_name(sample)}无法读取 · {error}')
            preview.set_sample(value)
            if preview.drawing is not None and preview.drawing.missing_scale:
                notices.append(f'{self.variant_name(sample)}缺少采集比例 · 按约略尺寸显示')
        drawings = [p.drawing for p in (self.preview, self.compare_preview) if p.drawing is not None]
        self.preview_view.frame(drawings, reset=reset_view)
        self.zoom_button.setEnabled(bool(drawings))
        self.preview.update()
        self.compare_preview.update()
        self.compare_button.setText('退出比较' if other is not None else '并排比较')
        self.compare_panel.setVisible(other is not None)
        if row is not None:
            self.primary_label.setText(f'{self.variant_name(row)} · {"当前预览" if other else "原始笔迹"}')
        self.layout_preview()
        self.preview_warning.setText('\n'.join(notices))
        self.preview_warning.setVisible(bool(notices))

    def pick_export(self):
        rows = self.selected_samples()
        writer = self.writer.text()
        if not rows:
            return
        try:
            name = self.library.catalog.writers()[writer]['name']
        except (KeyError, OSError, ValueError) as error:
            self.status.setText(f'无法读取书写者信息 · {error}')
            return
        _, hidden = self.selection_summary()
        scope = f'{name} · {len({row.character for row in rows})} 字 · {len(rows)} 份样本'
        if hidden:
            scope += f'\n其中 {hidden} 份在当前筛选之外。'
        buttons = QtWidgets.QMessageBox.StandardButton
        if QtWidgets.QMessageBox.question(self, '确认导出范围', scope, buttons.Yes | buttons.Cancel, buttons.Cancel) != buttons.Yes:
            return
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
