"""Library presentation shared by the main manager and compact font picker."""

from pathlib import Path
from zipfile import BadZipFile

from PySide6 import QtCore, QtSvgWidgets, QtWidgets

from ..resource_catalog import FontMetadata
from .library import fingerprint
from .management import GROUPS, inspect_font, summarize


class FontManagement:
    def setup_management(self):
        self.management = FontMetadata(self.root)
        self.catalog_error = ''
        try:
            self.catalog = self.management.read()
        except (OSError, ValueError) as error:
            self.catalog, self.catalog_error = {}, str(error)
        self.metadata_job = self.inspection_job = None
        self.inspection_epoch = 0
        self.inspection_sample = self.character_offset = 0
        layout = self.layout()
        layout.removeWidget(self.list)
        layout.removeWidget(self.detail)
        split = QtWidgets.QSplitter()
        left = QtWidgets.QWidget()
        side = QtWidgets.QVBoxLayout(left)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('搜索字体、书写者或内容版本')
        side.addWidget(self.search)
        filters = QtWidgets.QHBoxLayout()
        self.writer_filter = QtWidgets.QComboBox()
        self.writer_filter.addItem('全部书写者', '')
        filters.addWidget(self.writer_filter)
        self.show_history = QtWidgets.QCheckBox('历史版本')
        self.show_archived = QtWidgets.QCheckBox('已移出')
        filters.addWidget(self.show_history)
        filters.addWidget(self.show_archived)
        side.addLayout(filters)
        side.addWidget(self.list, 1)
        split.addWidget(left)
        self.details_tabs = QtWidgets.QTabWidget()
        preview_page = QtWidgets.QWidget()
        preview_col = QtWidgets.QVBoxLayout(preview_page)
        self.preview_text = QtWidgets.QPlainTextEdit('123 Abc，。 ∶ ∘')
        self.preview_text.setMaximumHeight(78)
        self.preview_text.setPlaceholderText('输入试写文字；缺字显示红框，不以系统字体替代')
        preview_col.addWidget(self.preview_text)
        self.ink_preview = QtSvgWidgets.QSvgWidget()
        self.ink_preview.setMinimumSize(260, 170)
        preview_col.addWidget(self.ink_preview, 1)
        self.preview_state = QtWidgets.QLabel('选择字体查看真实笔迹。')
        self.preview_state.setWordWrap(True)
        preview_col.addWidget(self.preview_state)
        preview_col.addWidget(self.detail)
        self.resource_state = QtWidgets.QLabel()
        self.resource_state.setWordWrap(True)
        preview_col.addWidget(self.resource_state)
        self.details_tabs.addTab(preview_page, '预览')
        characters = QtWidgets.QWidget()
        char_col = QtWidgets.QVBoxLayout(characters)
        row = QtWidgets.QHBoxLayout()
        self.character_group = QtWidgets.QComboBox()
        self.character_group.addItems(GROUPS)
        self.character_search = QtWidgets.QLineEdit()
        self.character_search.setPlaceholderText('查找字符，例如 A、孔 或 U+2218')
        row.addWidget(self.character_group)
        row.addWidget(self.character_search, 1)
        char_col.addLayout(row)
        self.character_list = QtWidgets.QListWidget()
        char_col.addWidget(self.character_list, 1)
        self.character_preview = QtSvgWidgets.QSvgWidget()
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
        self.version_info.setReadOnly(True)
        version_page = QtWidgets.QWidget()
        version_col = QtWidgets.QVBoxLayout(version_page)
        version_col.addWidget(self.version_info, 2)
        version_col.addWidget(QtWidgets.QLabel('同一字体的其他版本 · 仅浏览，不自动升级本文'))
        self.version_list = QtWidgets.QListWidget()
        self.version_list.itemClicked.connect(self.choose_version)
        version_col.addWidget(self.version_list, 1)
        self.details_tabs.addTab(version_page, '来源与版本')
        self.file_info = QtWidgets.QPlainTextEdit()
        self.file_info.setReadOnly(True)
        self.details_tabs.addTab(self.file_info, '文件信息')
        split.addWidget(self.details_tabs)
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
        self.preview_text.textChanged.connect(self.queue_inspection)
        self.character_search.textChanged.connect(self.character_query)
        self.character_group.currentIndexChanged.connect(self.character_query)
        self.character_list.itemClicked.connect(self.choose_character)
        self.list.itemDoubleClicked.connect(lambda *_: self.show_details())
        self.default_button = QtWidgets.QPushButton('设为新文档默认')
        self.default_button.clicked.connect(self.default_font)
        self.actions.insertWidget(1, self.default_button)
        self.selection_buttons.append(self.default_button)
        self.buttons.append(self.default_button)
        self.more_button = QtWidgets.QToolButton()
        self.more_button.setText('更多操作')
        self.more_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self.more_button)
        menu.addAction('修改库内显示名称…', self.rename_font)
        menu.addAction('移出字体库 / 恢复', self.archive_font)
        menu.addAction('刷新资源列表', self.refresh)
        self.more_button.setMenu(menu)
        self.actions.addWidget(self.more_button)

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

    def queue_inspection(self, *_):
        self.inspection_epoch += 1
        self.preview_timer.start()

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

    def inspect(self):
        if self.inspection_job:
            self.preview_timer.start()
            return
        try:
            path = self.selected()
            data = self.catalog.get(path.name, {})
            if data.get('error'):
                raise ValueError(data['error'])
            from .ui import Job
            epoch = self.inspection_epoch
            args = (self.preview_text.toPlainText(), self.character_search.text().strip(), self.inspection_sample,
                    self.character_group.currentText(), self.character_offset)
            self.inspection_job = Job(lambda progress: (str(path), epoch, inspect_font(path, *args)))
            self.inspection_job.signals.completed.connect(self.inspected)
            self.inspection_job.signals.failed.connect(self.inspection_failed)
            QtCore.QThreadPool.globalInstance().start(self.inspection_job)
        except (OSError, ValueError) as error:
            self.preview_state.setText(str(error))

    def inspected(self, value):
        self.inspection_job = None
        path, epoch, result = value
        if epoch != self.inspection_epoch or not self.list.currentItem() or str(self.selected()) != path:
            return
        try:
            unchanged = fingerprint(path) == result['stamp']
        except OSError:
            unchanged = False
        if not unchanged:
            self.preview_state.setText('字体文件已变化，请刷新后重新检查。')
            return
        self.ink_preview.load(result['svg'])
        self.character_preview.load(result['svg'])
        for preview in (self.ink_preview, self.character_preview):
            preview.renderer().setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self.preview_state.setText('真实笔迹预览 · 不改变选样。' + ('缺字：' + result['missing'] if result['missing'] else ''))
        self.sample_count.setText(result['source'] or '选择单字可切换其所有样本。')
        with QtCore.QSignalBlocker(self.character_list):
            self.character_list.clear()
            for char in result['characters']:
                item = QtWidgets.QListWidgetItem(f'{char}    U+{ord(char):04X}')
                item.setData(QtCore.Qt.UserRole, char)
                self.character_list.addItem(item)
        self.character_count.setText(f'共 {result["total"]} 字 · 第 {self.character_offset+1}–{self.character_offset+len(result["characters"])} 字')

    def inspection_failed(self, error):
        self.inspection_job = None
        self.preview_state.setText('字形预览未完成：' + error)

    def update_management(self, path):
        data = self.catalog.get(path.name, {})
        summary = self.metadata_for(path)
        if not summary:
            self.resource_state.setText('目录摘要正在读取；尚未声明完整验证通过。' + data.get('error', '') + self.catalog_error)
        else:
            manifest = summary['manifest']
            self.resource_state.setText('资源状态：' + ('完整验证通过（当前文件）' if data.get('verified_stamp') == list(fingerprint(path)) else '索引可读取 · 完整验证未运行') + '\n本文是否缺字或可导出，需要单独适配检查。')
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
