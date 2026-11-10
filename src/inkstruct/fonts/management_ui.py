"""Library presentation shared by the main manager and compact font picker."""

from collections import OrderedDict
from itertools import pairwise
from pathlib import Path
import re
from zipfile import BadZipFile

from PySide6 import QtCore, QtSvgWidgets, QtWidgets

from ..resource_catalog import FontMetadata
from ..ui_behavior import open_containing_folder
from .library import fingerprint
from .management import GROUPS, inspect_font, summarize

_PREVIEW_CACHE_ENTRIES = 12
_PREVIEW_CACHE_SVG_LIMIT = 1024 * 1024
_PREVIEW_COLOR = re.compile(rb'\b(fill|stroke)="(white|#24354b|#111827|#c44848|#dc2626)"')


class FontPreview(QtSvgWidgets.QSvgWidget):
    """Recolor the generated display SVG when the window palette changes."""

    def set_preview(self, svg):
        self.preview_svg = svg
        self.update_preview_palette()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.PaletteChange and hasattr(self, "preview_svg"):
            self.update_preview_palette()

    def update_preview_palette(self):
        svg = self.preview_svg
        palette = self.palette()
        if palette.base().color().lightness() < 128:
            paper = palette.base().color().name().encode("ascii")
            ink = palette.text().color().name().encode("ascii")
            colors = {b"white": paper, b"#24354b": ink, b"#111827": ink,
                      b"#c44848": b"#ffabab", b"#dc2626": b"#ffabab"}
            svg = _PREVIEW_COLOR.sub(lambda match: match[1] + b'="' + colors[match[2]] + b'"', svg)
        self.load(svg)
        self.renderer().setAspectRatioMode(QtCore.Qt.KeepAspectRatio)


class FontManagement:
    def setup_management(self):
        self.setObjectName('font_library_browser')
        self.setStyleSheet('''
            QWidget#font_browser_sidebar { background: palette(alternate-base); border: 1px solid palette(mid); }
            QListWidget#installed_fonts { background: transparent; border: none; }
            QLabel#font_selected_title { font-size: 19px; font-weight: 600; color: palette(window-text); }
            QLabel#font_selected_meta, QLabel#font_library_count { font-size: 12px; color: palette(window-text); }
            QTabWidget#font_detail_tabs::pane { border: none; }
            QTabWidget#font_detail_tabs QTabBar::tab {
                background: transparent; border: none; border-bottom: 2px solid transparent;
                padding: 7px 12px;
            }
            QTabWidget#font_detail_tabs QTabBar::tab:selected {
                border-bottom-color: palette(highlight); color: palette(link);
            }
            QFrame#font_preview_surface { background: palette(alternate-base); border: 1px solid palette(mid); }
            QSvgWidget#font_preview_paper, QSvgWidget#font_character_preview {
                background: palette(base); border: 1px solid palette(mid);
            }
            QLabel#font_preview_message {
                background: palette(base); border: 1px solid palette(mid);
                color: palette(text); font-weight: 600;
            }
        ''')
        self.management = FontMetadata(self.root)
        self.catalog_error = ''
        try:
            self.catalog = self.management.read()
        except (OSError, ValueError) as error:
            self.catalog, self.catalog_error = {}, str(error)
        self.metadata_job = self.inspection_job = None
        self.preview_cache = OrderedDict()
        self.inspection_epoch = 0
        self.inspection_sample = self.character_offset = 0
        layout = self.layout()
        layout.removeWidget(self.list)
        layout.removeWidget(self.detail)
        split = QtWidgets.QSplitter()
        split.setObjectName('font_library_splitter')
        split.setChildrenCollapsible(False)
        left = QtWidgets.QWidget()
        left.setObjectName('font_browser_sidebar')
        side = QtWidgets.QVBoxLayout(left)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(8)
        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName('font_library_search')
        self.search.setAccessibleName('搜索字体')
        self.search.setPlaceholderText('搜索字体、书写者或内容版本')
        side.addWidget(self.search)
        filters = QtWidgets.QHBoxLayout()
        self.writer_filter = QtWidgets.QComboBox()
        self.writer_filter.setAccessibleName('按书写者筛选字体')
        self.writer_filter.addItem('全部书写者', '')
        filters.addWidget(self.writer_filter)
        self.show_history = QtWidgets.QCheckBox('历史版本')
        self.show_archived = QtWidgets.QCheckBox('已移出')
        filters.addWidget(self.show_history)
        filters.addWidget(self.show_archived)
        side.addLayout(filters)
        self.library_count = QtWidgets.QLabel()
        self.library_count.setObjectName('font_library_count')
        side.addWidget(self.library_count)
        self.list.setAccessibleName('字体列表')
        self.list.setWordWrap(False)
        self.list.setTextElideMode(QtCore.Qt.ElideRight)
        side.addWidget(self.list, 1)
        split.addWidget(left)
        right = QtWidgets.QWidget()
        right_col = QtWidgets.QVBoxLayout(right)
        right_col.setContentsMargins(12, 0, 0, 0)
        right_col.setSpacing(12)
        self.font_header = QtWidgets.QWidget()
        header_col = QtWidgets.QVBoxLayout(self.font_header)
        header_col.setContentsMargins(0, 0, 0, 0)
        header_col.setSpacing(4)
        self.font_title = QtWidgets.QLabel()
        self.font_title.setObjectName('font_selected_title')
        self.font_title.setTextFormat(QtCore.Qt.PlainText)
        self.font_title.setWordWrap(True)
        self.font_meta = QtWidgets.QLabel()
        self.font_meta.setObjectName('font_selected_meta')
        self.font_meta.setTextFormat(QtCore.Qt.PlainText)
        self.font_meta.setWordWrap(True)
        header_col.addWidget(self.font_title)
        header_col.addWidget(self.font_meta)
        right_col.addWidget(self.font_header)
        self.detail_stack = QtWidgets.QStackedWidget()
        self.detail_stack.setObjectName('font_library_details')
        empty = QtWidgets.QWidget()
        empty_col = QtWidgets.QVBoxLayout(empty)
        empty_col.setContentsMargins(24, 24, 24, 24)
        empty_col.addStretch()
        self.empty_title = QtWidgets.QLabel()
        self.empty_title.setProperty('inkRole', 'title')
        self.empty_title.setWordWrap(True)
        self.empty_text = QtWidgets.QLabel()
        self.empty_text.setWordWrap(True)
        self.empty_text.setTextFormat(QtCore.Qt.PlainText)
        self.empty_text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        empty_col.addWidget(self.empty_title)
        empty_col.addWidget(self.empty_text)
        empty_col.addStretch(2)
        self.detail_stack.addWidget(empty)
        self.empty_page = empty
        self.details_tabs = QtWidgets.QTabWidget()
        self.details_tabs.setObjectName('font_detail_tabs')
        preview_page = QtWidgets.QWidget()
        preview_col = QtWidgets.QVBoxLayout(preview_page)
        preview_col.setContentsMargins(0, 12, 0, 0)
        preview_col.setSpacing(8)
        preview_row = QtWidgets.QHBoxLayout()
        preview_row.addWidget(QtWidgets.QLabel('预览内容'))
        self.preview_mode = QtWidgets.QComboBox()
        self.preview_mode.setAccessibleName('字体预览内容')
        self.preview_mode.addItem('汉字与英文', 'mixed')
        self.preview_mode.addItem('公式示例', 'formula')
        self.preview_mode.addItem('自定义试写', 'custom')
        preview_row.addWidget(self.preview_mode)
        preview_row.addStretch()
        self.edit_preview_button = QtWidgets.QPushButton('编辑试写…')
        self.edit_preview_button.clicked.connect(self.edit_current_preview)
        preview_row.addWidget(self.edit_preview_button)
        preview_col.addLayout(preview_row)
        self.preview_text = QtWidgets.QPlainTextEdit('123 Abc，。 ∶ ∘')
        self.custom_preview_text = self.preview_text.toPlainText()
        self.preview_text.setAccessibleName('字体试写文字')
        self.preview_text.setMaximumHeight(78)
        self.preview_text.setPlaceholderText('输入试写文字；缺字显示红框，不以系统字体替代')
        preview_col.addWidget(self.preview_text)
        surface = QtWidgets.QFrame()
        surface.setObjectName('font_preview_surface')
        paper_col = QtWidgets.QVBoxLayout(surface)
        paper_col.setContentsMargins(16, 16, 16, 16)
        self.ink_preview = FontPreview()
        self.ink_preview.setObjectName('font_preview_paper')
        self.ink_preview.setMinimumSize(260, 170)
        self.preview_display = QtWidgets.QStackedWidget()
        self.preview_display.addWidget(self.ink_preview)
        self.preview_message = QtWidgets.QLabel()
        self.preview_message.setObjectName('font_preview_message')
        self.preview_message.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_display.addWidget(self.preview_message)
        paper_col.addWidget(self.preview_display, 1)
        preview_col.addWidget(surface, 1)
        self.preview_state = QtWidgets.QLabel('选择字体查看真实笔迹。')
        self.preview_state.setWordWrap(True)
        preview_col.addWidget(self.preview_state)
        # Keep the complete original summary for the explicit details view.
        self.detail.setParent(self)
        self.detail.hide()
        self.resource_state = QtWidgets.QLabel()
        self.resource_state.setWordWrap(True)
        preview_col.addWidget(self.resource_state)
        state_row = QtWidgets.QHBoxLayout()
        note = QtWidgets.QLabel('独立试写，不改变当前文档及冻结选样。')
        note.setWordWrap(True)
        state_row.addWidget(note, 1)
        self.preview_details_button = QtWidgets.QPushButton('查看提示…')
        self.preview_details_button.clicked.connect(self.show_preview_details)
        state_row.addWidget(self.preview_details_button)
        preview_col.addLayout(state_row)
        self.details_tabs.addTab(preview_page, '预览')
        characters = QtWidgets.QWidget()
        char_col = QtWidgets.QVBoxLayout(characters)
        row = QtWidgets.QHBoxLayout()
        self.character_group = QtWidgets.QComboBox()
        self.character_group.setAccessibleName('字符类别')
        self.character_group.addItems(GROUPS)
        self.character_search = QtWidgets.QLineEdit()
        self.character_search.setAccessibleName('查找字体中的字符')
        self.character_search.setPlaceholderText('查找字符，例如 A、孔 或 U+2218')
        row.addWidget(self.character_group)
        row.addWidget(self.character_search, 1)
        char_col.addLayout(row)
        self.character_list = QtWidgets.QListWidget()
        self.character_list.setAccessibleName('字体字符列表')
        char_col.addWidget(self.character_list, 1)
        self.character_preview = FontPreview()
        self.character_preview.setObjectName('font_character_preview')
        self.character_preview.setMinimumHeight(90)
        self.character_preview.setMaximumHeight(140)
        char_col.addWidget(self.character_preview)
        page_row = QtWidgets.QHBoxLayout()
        self.character_count = QtWidgets.QLabel()
        page_row.addWidget(self.character_count)
        for title, direction in [('上一组', -1), ('下一组', 1)]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda checked=False, d=direction: self.character_page(d))
            page_row.addWidget(button)
        char_col.addLayout(page_row)
        self.sample_count = QtWidgets.QLabel()
        self.sample_count.setWordWrap(True)
        char_col.addWidget(self.sample_count)
        samples = QtWidgets.QHBoxLayout()
        for title, direction in [('上一样本', -1), ('下一样本', 1)]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda checked=False, d=direction: self.sample_step(d))
            samples.addWidget(button)
        char_col.addLayout(samples)
        self.details_tabs.addTab(characters, '字符')
        self.version_info = QtWidgets.QPlainTextEdit()
        self.version_info.setAccessibleName('字体来源与版本')
        self.version_info.setReadOnly(True)
        version_page = QtWidgets.QWidget()
        version_col = QtWidgets.QVBoxLayout(version_page)
        version_col.addWidget(self.version_info, 2)
        version_col.addWidget(QtWidgets.QLabel('同一字体的其他版本 · 仅浏览，不自动升级本文'))
        self.version_list = QtWidgets.QListWidget()
        self.version_list.setAccessibleName('同一字体的其他版本')
        self.version_list.itemClicked.connect(self.choose_version)
        version_col.addWidget(self.version_list, 1)
        self.details_tabs.addTab(version_page, '来源与版本')
        self.file_info = QtWidgets.QPlainTextEdit()
        self.file_info.setAccessibleName('字体文件详情')
        self.file_info.setReadOnly(True)
        self.details_tabs.addTab(self.file_info, '文件信息')
        self.detail_stack.addWidget(self.details_tabs)
        right_col.addWidget(self.detail_stack, 1)
        split.addWidget(right)
        split.setSizes([360, 650])
        split.setStretchFactor(1, 2)
        layout.insertWidget(1, split, 1)
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(220)
        self.preview_timer.timeout.connect(self.inspect)
        for control, signal in ((self.search, self.search.textChanged),
                                (self.writer_filter, self.writer_filter.currentIndexChanged),
                                (self.show_history, self.show_history.toggled),
                                (self.show_archived, self.show_archived.toggled)):
            signal.connect(self.filter_fonts)
        self.preview_text.textChanged.connect(self.edit_preview_text)
        self.preview_mode.currentIndexChanged.connect(self.change_preview_mode)
        self.update_preview_controls()
        self.character_search.textChanged.connect(self.character_query)
        self.character_group.currentIndexChanged.connect(self.character_query)
        self.character_list.itemClicked.connect(self.choose_character)
        self.list.itemDoubleClicked.connect(lambda *_: self.show_details())
        self.default_button = QtWidgets.QPushButton('设为新文档默认')
        self.default_button.setToolTip('只改变以后新建文档的默认字体；当前文档不变。')
        self.default_button.clicked.connect(self.default_font)
        self.actions.insertWidget(1, self.default_button)
        self.selection_buttons.append(self.default_button)
        self.buttons.append(self.default_button)
        self.more_button = QtWidgets.QToolButton()
        self.more_button.setText('更多操作')
        self.more_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self.more_button)
        self.folder_action = menu.addAction('打开字体包所在文件夹', self.open_font_folder)
        self.rename_action = menu.addAction('修改库内显示名称…', self.rename_font)
        self.archive_action = menu.addAction('移出字体库 / 恢复', self.archive_font)
        menu.addAction('刷新资源列表', self.refresh)
        self.more_button.setMenu(menu)
        self.actions.addWidget(self.more_button)
        # Explicit order within the browser; hidden controls are skipped by Qt.
        order = [self.import_button, self.create_button, self.search, self.writer_filter,
                 self.show_history, self.show_archived, self.list, self.details_tabs,
                 self.preview_mode, self.edit_preview_button, self.preview_text,
                 self.preview_details_button, self.use_button, self.default_button,
                 *self.selection_buttons[1:-1], self.more_button]
        for first, second in pairwise(order):
            QtWidgets.QWidget.setTabOrder(first, second)

    def clear_font_details(self):
        """Invalidate the old selection before a pending preview can publish."""
        self.inspection_epoch += 1
        self.preview_timer.stop()
        self._inspection_path = None
        self.inspection_sample = self.character_offset = 0
        self.preview_display.setCurrentWidget(self.ink_preview)
        self.preview_message.clear()
        blank = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
        for preview in (self.ink_preview, self.character_preview):
            preview.set_preview(blank)
        for label in (self.detail, self.resource_state, self.preview_state,
                      self.sample_count, self.character_count, self.font_title, self.font_meta):
            label.clear()
            label.setToolTip('')
        self.font_header.hide()
        self.character_list.clear()
        self.version_info.clear()
        self.version_list.clear()
        self.file_info.clear()

    def show_font_message(self, title, message):
        self.empty_title.setText(title)
        self.empty_text.setText(message)
        self.detail_stack.setCurrentWidget(self.empty_page)

    def show_unselected_font(self):
        if self.catalog_error:
            self.show_font_message('字体库管理记录需要检查', self.catalog_error + '\n原记录保留，未自动覆盖。')
        elif not self.list.count():
            self.show_font_message('还没有字体', '点击右上角“导入字体…”选择已有字体包，或从已完成的生成结果“制作字体…”。')
        elif not any(not self.list.item(i).isHidden() for i in range(self.list.count())):
            self.show_font_message('没有匹配的字体', '请调整搜索词、书写者或历史版本／已移出筛选；原字体没有被移除。')
        else:
            self.show_font_message('请选择字体', '从左侧选择字体查看真实笔迹、字符样本及来源。浏览不会改变当前文档。')

    def metadata_for(self, path):
        data = self.catalog.get(Path(path).name, {})
        summary = data.get('summary')
        try:
            return summary if summary and summary.get('stamp') == list(fingerprint(path)) else None
        except OSError:
            return None

    def load_metadata(self):
        if self.metadata_job:
            return
        from .ui import Job
        paths = []
        for path in self.root.glob('*.inkfont'):
            try:
                if self.metadata_for(path) is None and self.catalog.get(path.name, {}).get('error_stamp') != list(fingerprint(path)):
                    paths.append(path)
            except OSError:
                continue
        if not paths:
            self.filter_fonts()
            return
        def calculate(progress):
            results = []
            for path in paths:
                try:
                    results.append((str(path), summarize(path), None))
                except (OSError, ValueError, KeyError, BadZipFile) as error:
                    results.append((str(path), None, str(error)))
            return results
        self.metadata_job = Job(calculate)
        self.metadata_job.signals.completed.connect(self.metadata_loaded)
        self.metadata_job.signals.failed.connect(self.metadata_failed)
        QtCore.QThreadPool.globalInstance().start(self.metadata_job)

    def metadata_loaded(self, results):
        self.metadata_job = None
        for path, summary, error in results:
            if not Path(path).is_file():
                continue
            item = self.catalog.setdefault(Path(path).name, {})
            changes = {}
            if summary and summary['stamp'] == list(fingerprint(path)):
                item['summary'] = summary
                item.pop('error', None)
                changes = {'summary': summary, 'error': '', 'error_stamp': None}
                self.font_entries[path] = (tuple(summary['stamp']), summary['title'], summary['detail'])
            elif error:
                item['error'] = error
                item['error_stamp'] = list(fingerprint(path))
                changes = {'error': error, 'error_stamp': item['error_stamp']}
            try:
                if changes:
                    self.management.update(Path(path).name, **changes)
            except (OSError, ValueError) as exc:
                self.catalog_error = str(exc)
        self.refresh()

    def metadata_failed(self, error):
        self.metadata_job = None
        self.progress.setText('目录摘要读取未完成：' + error)

    def filter_fonts(self, *_):
        if not hasattr(self, 'catalog'):
            return
        needle, writer = self.search.text().casefold(), self.writer_filter.currentData()
        newest = {}
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = Path(item.data(QtCore.Qt.UserRole))
            data = self.catalog.get(path.name, {})
            summary = self.metadata_for(path)
            if summary and not data.get('archived'):
                key = summary['manifest']['font_id']
                stamp = path.stat().st_mtime_ns
                if key not in newest or stamp > newest[key][0]:
                    newest[key] = (stamp, path.name)
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = Path(item.data(QtCore.Qt.UserRole))
            data = self.catalog.get(path.name, {})
            summary = self.metadata_for(path)
            historical = bool(summary and newest.get(summary['manifest']['font_id'], (0, path.name))[1] != path.name)
            hay = item.text() + ' ' + str(path) + (' '+str(summary['manifest']) if summary else '')
            owner = summary['manifest']['writer_alias'] if summary else ''
            item.setHidden(needle not in hay.casefold() or (writer and writer != owner)
                           or (historical and not self.show_history.isChecked() and '新文档默认' not in item.text())
                           or (data.get('archived', False) and not self.show_archived.isChecked()))
        selected = self.list.currentItem()
        if selected and selected.isHidden():
            self.list.setCurrentRow(next((i for i in range(self.list.count()) if not self.list.item(i).isHidden()), -1))
        visible = sum(not self.list.item(i).isHidden() for i in range(self.list.count()))
        self.library_count.setText(f'显示 {visible} / {self.list.count()} 项')
        if not self.list.currentItem():
            self.describe()

    def queue_inspection(self, *_):
        self.inspection_epoch += 1
        if self.list.currentItem() and self.detail_stack.currentWidget() is self.details_tabs:
            self.inspect(debounce=True)

    def show_preview_message(self, message, detail=''):
        self.preview_message.setText(message)
        self.preview_display.setCurrentWidget(self.preview_message)
        self.preview_state.setText(detail)
        self.preview_state.setToolTip('')

    def edit_preview_text(self):
        self.custom_preview_text = self.preview_text.toPlainText()
        with QtCore.QSignalBlocker(self.preview_mode):
            self.preview_mode.setCurrentIndex(2)
        with QtCore.QSignalBlocker(self.character_search):
            self.character_search.clear()
        self.update_preview_controls()
        self.queue_inspection()

    def change_preview_mode(self):
        if self.preview_mode.currentData() == 'custom':
            with QtCore.QSignalBlocker(self.preview_text):
                self.preview_text.setPlainText(self.custom_preview_text)
        self.update_preview_controls()
        with QtCore.QSignalBlocker(self.character_search):
            self.character_search.clear()
        self.inspection_sample = self.character_offset = 0
        self.queue_inspection()

    def update_preview_controls(self):
        custom = self.preview_mode.currentData() == 'custom'
        self.preview_text.setVisible(custom)
        self.edit_preview_button.setVisible(not custom)

    def edit_current_preview(self):
        self.custom_preview_text = self.preview_text.toPlainText()
        self.preview_mode.setCurrentIndex(2)
        self.preview_text.setFocus()
        self.preview_text.selectAll()

    def show_preview_details(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('字体与预览提示')
        dialog.resize(650, 450)
        col = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QPlainTextEdit()
        text.setReadOnly(True)
        text.setAccessibleName('完整字体与预览提示')
        text.setPlainText('\n\n'.join(p for p in (
            self.detail.text(), self.resource_state.text(), self.preview_state.text(),
            self.preview_state.toolTip(), self.catalog_error) if p))
        col.addWidget(text)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def character_query(self, *_):
        self.character_offset = self.inspection_sample = 0
        self.queue_inspection()

    def character_page(self, direction):
        self.character_offset = max(0, self.character_offset + direction*200)
        self.queue_inspection()

    def sample_step(self, direction):
        self.inspection_sample += direction
        self.queue_inspection()

    def choose_character(self, item):
        self.character_search.setText(item.data(QtCore.Qt.UserRole))

    def inspect(self, *, debounce=False):
        try:
            path = self.selected()
            data = self.catalog.get(path.name, {})
            if data.get('error'):
                raise ValueError(data['error'])
            epoch = self.inspection_epoch
            preset = self.preview_mode.currentData()
            text = self.preview_text.toPlainText()[:120] if preset == 'custom' else ''
            args = (text, self.character_search.text().strip(), self.inspection_sample,
                    self.character_group.currentText(), self.character_offset)
            key = (str(path), fingerprint(path), args, preset)
            if key in self.preview_cache:
                self.preview_timer.stop()
                self.preview_cache.move_to_end(key)
                self.show_inspection(self.preview_cache[key])
                return
            self.show_preview_message('正在加载预览…')
            if debounce or self.inspection_job:
                self.preview_timer.start()
                return
            from .ui import Job
            self.inspection_job = Job(lambda progress: (key, epoch, inspect_font(path, *args, preset=preset)))
            self.inspection_job.signals.completed.connect(self.inspected)
            self.inspection_job.signals.failed.connect(
                lambda error, p=str(path), e=epoch: self.inspection_failed(error, p, e))
            QtCore.QThreadPool.globalInstance().start(self.inspection_job)
        except (OSError, ValueError) as error:
            self.preview_timer.stop()
            self.show_preview_message('预览暂不可用', str(error))

    def inspected(self, value):
        self.inspection_job = None
        key, epoch, result = value
        if epoch != self.inspection_epoch or not self.list.currentItem():
            return
        path, stamp, _, _ = key
        if str(self.selected()) != path:
            return
        try:
            unchanged = stamp == result['stamp'] == fingerprint(path)
        except OSError:
            unchanged = False
        if not unchanged:
            self.show_preview_message('预览暂不可用', '字体文件已变化，请刷新后重新检查。')
            return
        if len(result['svg']) <= _PREVIEW_CACHE_SVG_LIMIT:
            self.preview_cache[key] = result
            if len(self.preview_cache) > _PREVIEW_CACHE_ENTRIES:
                self.preview_cache.popitem(last=False)
        self.show_inspection(result)

    def show_inspection(self, result):
        if 'preview_text' in result and self.preview_mode.currentData() != 'custom':
            with QtCore.QSignalBlocker(self.preview_text):
                self.preview_text.setPlainText(result['preview_text'])
        for preview in (self.ink_preview, self.character_preview):
            preview.set_preview(result['svg'])
        self.preview_display.setCurrentWidget(self.ink_preview)
        label = '公式示例 · 非成品导出' if self.preview_mode.currentData() == 'formula' else '真实笔迹 · 已更新'
        self.preview_state.setText(label + (' · 缺字：' + result['missing'] if result['missing'] else '') +
                                  ('\n' + '\n'.join(result.get('diagnostics', ())) if result.get('diagnostics') else ''))
        self.preview_state.setToolTip('\n'.join(p for p in (result.get('preview_note', ''), result.get('diagnostic_details', '')) if p))
        self.sample_count.setText(result['source'] or '选择单字可切换其所有样本。')
        with QtCore.QSignalBlocker(self.character_list):
            self.character_list.clear()
            for char in result['characters']:
                item = QtWidgets.QListWidgetItem(f'{char}    U+{ord(char):04X}')
                item.setData(QtCore.Qt.UserRole, char)
                self.character_list.addItem(item)
        self.character_count.setText(f'共 {result["total"]} 字 · 第 {self.character_offset+1}–{self.character_offset+len(result["characters"])} 字')

    def inspection_failed(self, error, path, epoch):
        self.inspection_job = None
        if epoch != self.inspection_epoch or not self.list.currentItem() or str(self.selected()) != path:
            return
        self.show_preview_message('预览加载失败', '字形预览未完成：' + error)

    def update_management(self, path):
        data = self.catalog.get(path.name, {})
        summary = self.metadata_for(path)
        if not summary:
            self.font_title.clear()
            self.font_meta.clear()
            self.font_header.hide()
            self.resource_state.setText('目录摘要正在读取；尚未声明完整验证通过。' + data.get('error', '') + self.catalog_error)
        else:
            manifest = summary['manifest']
            self.font_title.setText(data.get('alias') or manifest['name'])
            self.font_meta.setText('书写者：' + manifest['writer_alias'] + '  ·  内容版本：' + manifest['font_version'] +
                                   '  ·  ' + ('用户版' if manifest['package_kind'] == 'user' else '开发者版'))
            self.font_header.show()
            self.detail.setText((data.get('alias') or manifest['name']) + '\n书写者：' + manifest['writer_alias'] +
                                ' · 内容版本：' + manifest['font_version'] + ' · ' +
                                ('用户版' if manifest['package_kind'] == 'user' else '开发者版') + '\n' + summary['detail'])
            summary_line = (summary['detail'].splitlines() or ['字体摘要无详细统计'])[0]
            self.resource_state.setText(summary_line + '  ·  ' + ('完整验证通过（当前文件）' if data.get('verified_stamp') == list(fingerprint(path)) else '索引可读取 · 完整验证未运行'))
            self.version_info.setPlainText('字体：' + manifest['name'] + '\n书写者：' + manifest['writer_alias'] +
                '\n字体内容版本：' + manifest['font_version'] + '\n字符覆盖：' + str(summary['groups']) +
                '\n来源候选：' + str(summary['origins']) + '\n父包关系：' + str(manifest['derived_from_package']) +
                '\n同一 font_id 按入库文件时间展示最近项；不按名称猜测版本，不自动升级文档。')
            self.file_info.setPlainText('路径：' + str(path) + '\n包类型：' + manifest['package_kind'] +
                '\n字体格式：1.0（与应用版本独立）\nfont_id：' + manifest['font_id'] +
                '\nrelease_id：' + manifest['release_id'] + '\npackage_id：' + manifest['package_id'])
            self.version_list.clear()
            for name, entry in self.catalog.items():
                other = entry.get('summary', {}).get('manifest', {})
                if other.get('font_id') == manifest['font_id'] and not entry.get('archived'):
                    item = QtWidgets.QListWidgetItem((entry.get('alias') or other['name'])+' · 内容版本 '+other['font_version'])
                    item.setData(QtCore.Qt.UserRole, str(self.root/name))
                    self.version_list.addItem(item)
        self.queue_inspection()

    def show_details(self):
        self.details_tabs.setCurrentIndex(2)

    def open_font_folder(self):
        try:
            open_containing_folder(self.selected())
        except (OSError, ValueError) as error:
            self.set_progress(str(error))

    def choose_version(self, item):
        path = item.data(QtCore.Qt.UserRole)
        self.show_history.setChecked(True)
        for i in range(self.list.count()):
            if self.list.item(i).data(QtCore.Qt.UserRole) == path:
                self.list.setCurrentRow(i)
                break

    def change_metadata(self, **changes):
        path = self.selected()
        self.management.update(path.name, **changes)
        self.catalog.setdefault(path.name, {}).update(changes)
        self.refresh()

    def rename_font(self):
        try:
            path = self.selected()
            text, ok = QtWidgets.QInputDialog.getText(self, '库内显示名称', '不修改字体包或冻结身份', text=self.catalog.get(path.name, {}).get('alias', ''))
            if ok and text.strip():
                self.change_metadata(alias=text.strip())
        except (OSError, ValueError) as error:
            self.failed(str(error))

    def archive_font(self):
        try:
            path = self.selected()
            self.change_metadata(archived=not self.catalog.get(path.name, {}).get('archived', False))
        except (OSError, ValueError) as error:
            self.failed(str(error))

    def default_font(self):
        try:
            from .core import cached_font
            path = self.selected()
            def work(progress):
                progress('正在完整验证默认字体…当前文档保持不变。')
                cached_font(path)
                return {'path': str(path), 'default_ready': True, 'verified': True,
                        'stamp': fingerprint(path), 'message': '已设为新文档默认；当前文档和冻结字形保持原样。'}
            self.submit(work)
        except (OSError, ValueError) as error:
            self.failed(str(error))
