"""Template management and selectors share previews and explicit managed copies."""

import datetime
import hashlib
from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg, QtSvgWidgets, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.template_authoring import read_template
from ..resource_catalog import TemplateStore, workspace_for
from .template_manager import catalog_paths, description, perform_template_action


class TemplateLibrary(QtWidgets.QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.store = TemplateStore(workspace_for(editor) / 'templates')
        self.template = None
        self.metadata_jobs = {}
        self.thumbnail_cache = {}
        self.metadata_epoch = 0
        col = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(QtWidgets.QLabel('我的模板'))
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('搜索模板名称、纸张或来源文件')
        heading.addWidget(self.search, 1)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(['全部类型', '简单模板', '自定义模板', '旧版兼容'])
        heading.addWidget(self.kind)
        for title, callback in [('导入模板…', self.load), ('新建模板…', self.create)]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(callback)
            heading.addWidget(button)
        col.addLayout(heading)
        filters = QtWidgets.QHBoxLayout()
        self.recent = QtWidgets.QCheckBox('显示待入库的最近文件')
        self.archived = QtWidgets.QCheckBox('显示已移出模板')
        filters.addWidget(self.recent)
        filters.addWidget(self.archived)
        filters.addStretch()
        col.addLayout(filters)
        split = QtWidgets.QSplitter()
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName('template_library_list')
        self.list.setMinimumWidth(230)
        self.list.setIconSize(QtCore.QSize(60, 78))
        split.addWidget(self.list)
        detail = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(detail)
        self.summary = QtWidgets.QLabel('选择模板查看布局，不会自动应用。')
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(QtCore.Qt.PlainText)
        right.addWidget(self.summary)
        self.layouts = QtWidgets.QComboBox()
        right.addWidget(self.layouts)
        self.preview = QtSvgWidgets.QSvgWidget()
        self.preview.setMinimumSize(240, 250)
        right.addWidget(self.preview, 1)
        self.info = QtWidgets.QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(180)
        right.addWidget(self.info)
        split.addWidget(detail)
        split.setStretchFactor(1, 2)
        col.addWidget(split, 1)
        actions = QtWidgets.QHBoxLayout()
        self.use_button = QtWidgets.QPushButton('用于当前文档…')
        self.use_button.clicked.connect(self.use)
        self.edit_button = QtWidgets.QPushButton('编辑模板副本…')
        self.edit_button.clicked.connect(self.edit)
        self.default_button = QtWidgets.QPushButton('设为新文档默认')
        self.default_button.clicked.connect(self.set_default)
        self.add_recent = QtWidgets.QPushButton('将此文件加入模板库')
        self.add_recent.clicked.connect(self.add_selected)
        for button in (self.use_button, self.edit_button, self.default_button, self.add_recent):
            actions.addWidget(button)
        more = QtWidgets.QToolButton()
        more.setText('更多操作')
        more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(more)
        menu.addAction('导出模板…', self.export)
        menu.addAction('修改库内显示名称…', self.rename)
        menu.addAction('移出模板库 / 恢复', self.archive)
        menu.addAction('重新定位最近文件…', self.relocate)
        menu.addAction('显式复制旧布局为新模板…', self.migrate)
        more.setMenu(menu)
        actions.addWidget(more)
        col.addLayout(actions)
        self.error = QtWidgets.QLabel('模板与背景保存在库内副本中；外部更新不改变已保存文档。')
        self.error.setWordWrap(True)
        col.addWidget(self.error)
        self.search.textChanged.connect(self.filter)
        self.kind.currentIndexChanged.connect(self.filter)
        self.recent.toggled.connect(self.refresh)
        self.archived.toggled.connect(self.refresh)
        self.list.currentItemChanged.connect(self.describe)
        self.list.itemDoubleClicked.connect(lambda *_: self.show_details())
        self.layouts.currentIndexChanged.connect(self.show_layout)
        self.refresh()

    def selected(self):
        item = self.list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def refresh(self, *_):
        self.metadata_epoch += 1
        previous = self.selected()
        self.list.clear()
        try:
            entries = self.store.entries()
            managed_sources = {entry['source'] for entry in entries}
            for entry in sorted(entries, key=lambda e: e['created_ns'], reverse=True):
                if entry['archived'] and not self.archived.isChecked():
                    continue
                item = QtWidgets.QListWidgetItem(entry['name'] + (' · 已移出' if entry['archived'] else ''))
                item.setData(QtCore.Qt.UserRole, {'managed': entry, 'path': str(self.store.path(entry['id']))})
                self.list.addItem(item)
            if self.recent.isChecked():
                for path in catalog_paths():
                    if str(path) not in managed_sources:
                        item = QtWidgets.QListWidgetItem('待入库 · ' + path.stem + (' · 文件已移动' if not path.is_file() else ''))
                        item.setData(QtCore.Qt.UserRole, {'managed': None, 'path': str(path)})
                        self.list.addItem(item)
            for i in range(self.list.count()):
                if self.list.item(i).data(QtCore.Qt.UserRole) == previous:
                    self.list.setCurrentRow(i)
            if not self.list.currentItem() and self.list.count():
                self.list.setCurrentRow(0)
            self.filter()
            self.describe()
            self.load_thumbnails()
        except (OSError, ValueError, KeyError) as error:
            self.error.setText(str(error))

    def load_thumbnails(self):
        from ..fonts.ui import Job
        epoch = self.metadata_epoch
        cache = dict(self.thumbnail_cache)
        values = [self.list.item(i).data(QtCore.Qt.UserRole) for i in range(self.list.count())]
        def calculate(progress):
            from ..document.template_authoring import template_json
            from ..fonts.library import fingerprint
            output = []
            for data in values:
                stamp = None
                try:
                    stamp = fingerprint(data['path'])
                    if data['path'] in cache and cache[data['path']][1] == stamp:
                        output.append(cache[data['path']])
                        continue
                    template = self.store.read(data['managed']) if data['managed'] else read_template(data['path'])
                    if isinstance(template, FlowTemplate):
                        from ..document.flow_template_preview import geometry_preview
                        face = template.effective_layouts[0].layout_id
                    else:
                        from ..document.template_authoring import geometry_preview
                        face = 'first'
                    renderer = QtSvg.QSvgRenderer(geometry_preview(template, face).encode())
                    renderer.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
                    image = QtGui.QImage(60, 78, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(QtCore.Qt.GlobalColor.transparent)
                    painter = QtGui.QPainter(image)
                    renderer.render(painter)
                    painter.end()
                    data_buffer = QtCore.QByteArray()
                    buffer = QtCore.QBuffer(data_buffer)
                    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
                    image.save(buffer, 'PNG')
                    buffer.close()
                    output.append((data['path'], stamp, description(template), bytes(data_buffer),
                                   hashlib.sha256(template_json(template).encode()).hexdigest(), None))
                except (ValueError, TypeError, OSError) as error:
                    output.append((data['path'], stamp, '', None, '', str(error)))
            return epoch, output
        job = Job(calculate)
        self.metadata_jobs[epoch] = job
        job.signals.completed.connect(self.thumbnails_loaded)
        job.signals.failed.connect(lambda error, e=epoch: self.thumbnails_failed(e, error))
        QtCore.QThreadPool.globalInstance().start(job)

    def thumbnails_loaded(self, result):
        epoch, values = result
        self.metadata_jobs.pop(epoch, None)
        if epoch != self.metadata_epoch:
            return
        from ..document.template_authoring import template_json
        from ..global_defaults import GlobalDefaultsStore
        default = GlobalDefaultsStore().load()[0].flow.template
        default_hash = hashlib.sha256(template_json(default).encode()).hexdigest() if default else ''
        lookup = {self.list.item(i).data(QtCore.Qt.UserRole)['path']: self.list.item(i) for i in range(self.list.count())}
        for value in values:
            path, _stamp, summary, png, canonical, error = value
            self.thumbnail_cache[path] = value
            if len(self.thumbnail_cache) > 128:
                self.thumbnail_cache.pop(next(iter(self.thumbnail_cache)))
            item = lookup.get(path)
            if item is None:
                continue
            item.setToolTip(summary+'\n'+path if not error else error+'\n'+path)
            if error:
                item.setText(item.text()+' · 不可读取')
                item.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning))
            else:
                image = QtGui.QPixmap()
                image.loadFromData(png, 'PNG')
                item.setIcon(QtGui.QIcon(image))
                if canonical == default_hash:
                    item.setText(item.text()+' · 新文档默认')
        self.filter()

    def thumbnails_failed(self, epoch, error):
        self.metadata_jobs.pop(epoch, None)
        if epoch == self.metadata_epoch:
            self.error.setText('缩略图未完成：'+error)

    def filter(self, *_):
        needle = self.search.text().casefold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            data = item.data(QtCore.Qt.UserRole)
            hay = item.text() + ' ' + data['path'] + ' ' + item.toolTip()
            wanted = self.kind.currentText()
            item.setHidden(needle not in hay.casefold() or (wanted != '全部类型' and wanted not in hay))

    def read_selected(self):
        data = self.selected()
        if not data:
            raise ValueError('请选择模板')
        return self.store.read(data['managed']) if data['managed'] else read_template(data['path'])

    def describe(self, *_):
        self.template = None
        self.layouts.clear()
        self.preview.load(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        data = self.selected()
        try:
            if not data:
                raise ValueError('模板库为空。可新建模板，或显式导入文件；最近记录不会自动迁移。')
            self.template = self.read_selected()
            self.summary.setText(description(self.template))
            self.list.currentItem().setToolTip(description(self.template) + '\n' + data['path'])
            if isinstance(self.template, FlowTemplate):
                t = self.template
                for layout in t.effective_layouts:
                    self.layouts.addItem(layout.label, layout.layout_id)
                names = {layout.layout_id: layout.label for layout in t.effective_layouts}
                groups = ('起始页：' + (' → '.join(names[k] for k in t.start_pages) or '无') +
                          '\n循环页：' + ' → '.join(names[k] for k in t.loop_pages) + ' ↻') if t.kind == 'custom' else '重复单页布局 · 正文连续分页'
            else:
                self.layouts.addItem('首页', 'first')
                self.layouts.addItem('续页', 'continuation')
                groups = '旧版兼容 · 原绑定和协议保持'
            managed = data['managed']
            stamp = datetime.datetime.fromtimestamp(managed['created_ns']/1e9).strftime('%Y-%m-%d %H:%M') if managed else ''
            field_info = ('\n字段：'+ '、'.join(f.label+' ['+f.field_id+']'+(' 必填' if f.required else '') for f in self.template.fields)) if isinstance(self.template, FlowTemplate) and self.template.fields else ''
            self.info.setPlainText(groups + field_info + '\n资源状态：结构可读取；用于本文仍须适配检查。\n' +
                              (f'库内副本 · {stamp}\n来源：{managed["source"]}' if managed else '外部最近文件 · 尚未加入模板库'))
            self.error.setText('单击和预览不会改变文档。字段内容不包含在模板库副本中。')
            self.show_layout()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.summary.setText('资源不可读取 · 原记录保留')
            self.info.setPlainText(str(data['path']) if data else '')
            self.error.setText(str(error))
        allowed = self.template is not None and not (data and data['managed'] and data['managed']['archived'])
        for button in (self.use_button, self.edit_button, self.default_button):
            button.setEnabled(allowed)
        self.add_recent.setVisible(bool(data and not data['managed']))
        self.add_recent.setEnabled(self.template is not None)

    def show_layout(self, *_):
        if not self.template or self.layouts.currentIndex() < 0:
            return
        if isinstance(self.template, FlowTemplate):
            from ..document.flow_template_preview import geometry_preview
        else:
            from ..document.template_authoring import geometry_preview
        self.preview.load(geometry_preview(self.template, self.layouts.currentData()).encode())
        self.preview.renderer().setAspectRatioMode(QtCore.Qt.KeepAspectRatio)

    def guard(self, callback):
        try:
            callback()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.error.setText(str(error))

    def load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '导入模板副本（原文件保留）', '', '模板 (*.json)')
        if path:
            self.guard(lambda: self.import_path(path))

    def import_path(self, path):
        entry = self.store.add(path)
        self.refresh()
        for i in range(self.list.count()):
            if (self.list.item(i).data(QtCore.Qt.UserRole).get('managed') or {}).get('id') == entry['id']:
                self.list.setCurrentRow(i)
                break
        self.error.setText('已加入独立库内副本；原文件、当前文档和默认设置未改变。')

    def add_selected(self):
        if data := self.selected():
            self.guard(lambda: self.import_path(data['path']))

    def relocate(self):
        self.load()

    def create(self):
        choice, ok = QtWidgets.QInputDialog.getItem(self, '新建模板', '模板类型', ['简单模板', '自定义模板'], 0, False)
        if not ok:
            return
        from ..document.flow_template import PageLayout
        template = FlowTemplate() if choice == '简单模板' else FlowTemplate(name='自定义模板', kind='custom', layouts=(PageLayout('layout-1', '布局 1'),), loop_pages=('layout-1',))
        perform_template_action(self.editor, 'reusable', template)
        self.refresh()

    def edit(self):
        self.guard(lambda: perform_template_action(self.editor, 'reusable', self.read_selected()))
        self.refresh()

    def migrate(self):
        def action():
            from ..document.flow_template import migrate_layout
            template = self.read_selected()
            if isinstance(template, FlowTemplate):
                raise TypeError('此模板已使用当前字段协议，无需迁移')
            perform_template_action(self.editor, 'reusable', migrate_layout(template))
        self.guard(action)
        self.refresh()

    def show_details(self):
        QtWidgets.QMessageBox.information(self, '模板详情', self.summary.text() + '\n\n' + self.info.toPlainText())

    def use(self):
        from .resource_apply import TemplateApplyDialog
        if self.template:
            TemplateApplyDialog(self.editor, self.template, self).exec()

    def set_default(self):
        def action():
            from dataclasses import replace

            from ..global_defaults import GlobalDefaultsStore
            store = GlobalDefaultsStore()
            defaults, warning = store.load()
            if warning:
                raise ValueError(warning)
            defaults = replace(defaults, flow=replace(defaults.flow, template=self.read_selected()))
            store.save(defaults)
            self.refresh()
            self.error.setText('已设为新文档默认；当前文档和字段内容不变。')
        self.guard(action)

    def export(self):
        def action():
            from ..document.template_authoring import template_json
            template = self.read_selected()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, '导出模板（不覆盖已有文件）', template.name+'.json', '模板 (*.json)')
            if path:
                with Path(path).open('x', encoding='utf-8') as stream:
                    stream.write(template_json(template))
        self.guard(action)

    def rename(self):
        data = self.selected()
        if data and data['managed']:
            name, ok = QtWidgets.QInputDialog.getText(self, '修改库内显示名称', '不改变模板文件、字段身份或旧文档', text=data['managed']['name'])
            if ok:
                self.guard(lambda: self.store.update(data['managed']['id'], name=name.strip()))
                self.refresh()

    def archive(self):
        data = self.selected()
        if data and data['managed']:
            self.guard(lambda: self.store.update(data['managed']['id'], archived=not data['managed']['archived']))
            self.refresh()
