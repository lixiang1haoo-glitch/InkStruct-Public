"""Template management and selectors share previews and explicit managed copies."""

import datetime
import hashlib
from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.template_authoring import read_template
from ..global_defaults import GlobalDefaultsStore
from ..resource_catalog import TemplateStore, workspace_for
from ..ui_behavior import open_containing_folder
from .template_manager import catalog_paths, description, perform_template_action
from .template_viewport import FitSvgPreview


def preview_layouts(template):
    """Document order takes precedence over the layout-definition order."""
    if not isinstance(template, FlowTemplate):
        return (('first', '首页'), ('continuation', '续页')) if template else ()
    if template.kind == 'simple':
        return (('simple', '简单模板 · 重复单页'),)
    layouts = {p.layout_id: p.label for p in template.effective_layouts}
    order = dict.fromkeys((*template.start_pages, *template.loop_pages, *layouts))
    result = []
    for key in order:
        roles = []
        if key in template.start_pages:
            roles.append('起始')
        if key in template.loop_pages:
            roles.append('循环')
        result.append((key, f'{layouts[key]} · ' + ('、'.join(roles) or '备用版式（未加入页组）')))
    return result


class TemplateLibrary(QtWidgets.QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.store = TemplateStore(workspace_for(editor) / 'templates')
        self.template = None
        self.metadata_jobs = {}
        self.thumbnail_cache = {}
        self.metadata_epoch = 0
        self.preview_epoch = 0
        self.preview_jobs = {}
        col = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel('我的模板')
        title.setProperty('inkRole', 'title')
        heading.addWidget(title)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('搜索模板名称、纸张或来源文件')
        self.search.setAccessibleName('搜索模板')
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
        self.history = QtWidgets.QCheckBox('显示历史修订')
        self.archived = QtWidgets.QCheckBox('显示已移出模板')
        filters.addWidget(self.recent)
        filters.addWidget(self.history)
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
        self.summary = QtWidgets.QLabel('选择模板即可查看页面版式。')
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(QtCore.Qt.PlainText)
        right.addWidget(self.summary)
        self.layouts = QtWidgets.QComboBox()
        right.addWidget(self.layouts)
        self.preview = FitSvgPreview()
        self.preview.setProperty('inkRole', 'previewSurface')
        self.preview_stack = QtWidgets.QStackedWidget()
        self.preview_stack.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.preview_stack.setMinimumHeight(48)
        self.preview_stack.addWidget(self.preview)
        self.preview_status = QtWidgets.QLabel()
        self.preview_status.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_status.setWordWrap(True)
        self.preview_status.setTextFormat(QtCore.Qt.PlainText)
        self.preview_status.setProperty('inkRole', 'previewSurface')
        self.preview_stack.addWidget(self.preview_status)
        right.addWidget(self.preview_stack, 1)
        self.info = QtWidgets.QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setFixedHeight(112)
        right.addWidget(self.info)
        split.addWidget(detail)
        split.setStretchFactor(1, 2)
        col.addWidget(split, 1)
        actions = QtWidgets.QHBoxLayout()
        self.use_button = QtWidgets.QPushButton('用于当前文档…')
        self.use_button.setProperty('inkRole', 'primary')
        self.use_button.clicked.connect(self.use)
        self.edit_button = QtWidgets.QPushButton('编辑模板…')
        self.edit_button.clicked.connect(self.edit)
        self.default_button = QtWidgets.QPushButton('设为新文档默认')
        self.default_button.clicked.connect(self.set_default)
        self.add_recent = QtWidgets.QPushButton('将此文件加入模板库')
        self.add_recent.clicked.connect(self.add_selected)
        for button in (self.use_button, self.edit_button, self.default_button, self.add_recent):
            actions.addWidget(button)
        self.more_button = more = QtWidgets.QToolButton()
        more.setText('更多操作')
        more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(more)
        self.folder_action = menu.addAction('打开模板所在文件夹', self.open_template_folder)
        menu.addAction('导出 JSON…', self.export)
        menu.addAction('另存为新模板…', self.copy_template)
        self.managed_actions = (
            menu.addAction('导入为所选模板的新修订…', self.load_revision),
            menu.addAction('修改库内显示名称…', self.rename),
            menu.addAction('移出模板库 / 恢复', self.archive),
        )
        menu.addAction('从其他位置导入模板…', self.load)
        self.migrate_action = menu.addAction('迁移旧版式为新模板…', self.migrate)
        more.setMenu(menu)
        actions.addWidget(more)
        col.addLayout(actions)
        self.error = QtWidgets.QLabel('模板与背景保存在库内副本中；外部更新不改变已保存文档。')
        self.error.setWordWrap(True)
        col.addWidget(self.error)
        self.search.textChanged.connect(self.filter)
        self.kind.currentIndexChanged.connect(self.filter)
        self.recent.toggled.connect(self.refresh)
        self.history.toggled.connect(self.refresh)
        self.archived.toggled.connect(self.refresh)
        self.list.currentItemChanged.connect(self.describe)
        self.list.itemDoubleClicked.connect(lambda *_: self.show_details())
        self.layouts.currentIndexChanged.connect(self.show_layout)
        self.refresh()

    def selected(self):
        item = self.list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item and not item.isHidden() else None

    def refresh(self, *_):
        self.metadata_epoch += 1
        previous = self.selected()
        try:
            entries = self.store.entries()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.list.clear()
            self.describe()
            self.error.setText(str(error))
            return
        with QtCore.QSignalBlocker(self.list):
            self.list.clear()
            ordinary = QtWidgets.QListWidgetItem('普通页面 · 内置简单模板')
            ordinary.setData(QtCore.Qt.UserRole, {'managed': None, 'path': '内置普通页面', 'builtin': True})
            self.list.addItem(ordinary)
            managed_sources = {entry['source'] for entry in entries}
            superseded = self.store.superseded_ids(entries)
            for entry in sorted(entries, key=lambda e: e['created_ns'], reverse=True):
                if entry['archived'] and not self.archived.isChecked():
                    continue
                if not entry['archived'] and entry['id'] in superseded and not self.history.isChecked():
                    continue
                revision = entry.get('revision', {}).get('number', 1)
                item = QtWidgets.QListWidgetItem(f'{entry["name"]} · 修订 {revision}' + (' · 已移出' if entry['archived'] else ''))
                item.setData(QtCore.Qt.UserRole, {'managed': entry, 'path': str(self.store.path(entry['id']))})
                self.list.addItem(item)
            if self.recent.isChecked():
                for path in catalog_paths():
                    if str(path) not in managed_sources:
                        item = QtWidgets.QListWidgetItem('待入库 · ' + path.stem + (' · 文件已移动' if not path.is_file() else ''))
                        item.setData(QtCore.Qt.UserRole, {'managed': None, 'path': str(path)})
                        self.list.addItem(item)
            for i in range(self.list.count()):
                if previous and self.list.item(i).data(QtCore.Qt.UserRole)['path'] == previous['path']:
                    self.list.setCurrentRow(i)
            self.filter()
        self.describe()
        self.load_thumbnails()

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
                    builtin = data.get('builtin')
                    template = GlobalDefaultsStore().ordinary_template() if builtin else None
                    stamp = template_json(template) if builtin else fingerprint(data['path'])
                    if data['path'] in cache and cache[data['path']][1] == stamp:
                        output.append(cache[data['path']])
                        continue
                    if not builtin:
                        template = self.store.read(data['managed']) if data['managed'] else read_template(data['path'])
                    from ..document.template_authoring import geometry_preview
                    face = preview_layouts(template)[0][0]
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
        default = GlobalDefaultsStore().for_new_document()[0].flow.template
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
            if data['path'] in self.thumbnail_cache:
                hay += ' ' + self.thumbnail_cache[data['path']][2]
            wanted = self.kind.currentText()
            item.setHidden(needle not in hay.casefold() or (wanted != '全部类型' and wanted not in hay))
        if self.selected() is None:
            row = next((i for i in range(self.list.count()) if not self.list.item(i).isHidden()), -1)
            self.list.setCurrentRow(row)

    def read_selected(self):
        data = self.selected()
        if not data:
            raise ValueError('请选择模板')
        if data.get('builtin'):
            return GlobalDefaultsStore().ordinary_template()
        return self.store.read(data['managed']) if data['managed'] else read_template(data['path'])

    def describe(self, *_):
        self.preview_epoch += 1
        self.template = None
        data = self.selected()
        path = data['path'] if data else None
        keep_layout = self.layouts.currentData() if path == getattr(self, '_described_path', None) else None
        self._described_path = path
        with QtCore.QSignalBlocker(self.layouts):
            self.layouts.clear()
        try:
            if not data:
                raise ValueError('请调整筛选或导入模板。' if self.list.count() else '可新建模板或导入文件。')
            self.template = self.read_selected()
            self.summary.setText(description(self.template))
            self.list.currentItem().setToolTip(description(self.template) + '\n' + data['path'])
            with QtCore.QSignalBlocker(self.layouts):
                for key, label in preview_layouts(self.template):
                    self.layouts.addItem(label, key)
                if keep_layout is not None:
                    self.layouts.setCurrentIndex(max(0, self.layouts.findData(keep_layout)))
            if isinstance(self.template, FlowTemplate):
                t = self.template
                names = {layout.layout_id: layout.label for layout in t.effective_layouts}
                groups = ('起始页：' + (' → '.join(names[k] for k in t.start_pages) or '无') +
                          '\n循环页：' + ' → '.join(names[k] for k in t.loop_pages) + ' ↻') if t.kind == 'custom' else '重复单页版式 · 正文连续分页'
            else:
                groups = '旧版兼容 · 原绑定和协议保持'
            managed = data['managed']
            stamp = datetime.datetime.fromtimestamp(managed['created_ns']/1e9).strftime('%Y-%m-%d %H:%M') if managed else ''
            field_info = ('\n字段：'+ '、'.join(f.label+' ['+f.field_id+']'+(' 必填' if f.required else '') for f in self.template.fields)) if isinstance(self.template, FlowTemplate) and self.template.fields else ''
            revision = self.template.revision
            revision_info = (f'\n模板身份：{revision.template_id}\n修订 {revision.number}：{revision.revision_id}'
                             + (f'\n上一修订：{revision.parent_id}' if revision.parent_id else '')) if revision else ''
            self.info.setPlainText(groups + field_info + revision_info + '\n资源状态：结构可读取；用于本文仍须适配检查。\n' +
                              ('内置简单模板' if data.get('builtin') else
                               f'库内副本 · {stamp}\n来源：{managed["source"]}' if managed else '外部最近文件 · 尚未加入模板库'))
            self.error.setText('单击和预览不会改变文档。字段内容不包含在模板库副本中。')
            self.show_layout()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.summary.setText('资源不可读取 · 原记录保留' if data else
                                 '还没有模板 · 可在右上角新建或导入' if not self.list.count() else
                                 '没有匹配的模板')
            self.info.setPlainText(str(data['path']) if data else '')
            self.error.setText(str(error))
            self.show_preview_status('模板读取失败\n' + str(error) if data else
                                     '没有匹配的模板' if self.list.count() else '没有可预览的页面版式')
        self.layouts.setVisible(self.template is not None)
        self.info.setVisible(bool(data))
        allowed = self.template is not None and not (data and data['managed'] and data['managed']['archived'])
        for button in (self.use_button, self.edit_button, self.default_button):
            button.setEnabled(allowed)
        self.add_recent.setVisible(bool(data and not data['managed'] and not data.get('builtin')))
        self.add_recent.setEnabled(self.template is not None)
        self.more_button.setEnabled(bool(data))
        self.folder_action.setEnabled(bool(data and not data.get('builtin')))
        for action in self.managed_actions:
            action.setEnabled(bool(data and data['managed']))
        self.migrate_action.setEnabled(self.template is not None and not isinstance(self.template, FlowTemplate))

    def show_layout(self, *_):
        self.preview_epoch += 1
        epoch = self.preview_epoch
        template, key = self.template, self.layouts.currentData()
        if not template or key is None:
            self.show_preview_status('没有可预览的页面版式')
            return
        from ..document.template_authoring import geometry_preview
        from ..fonts.ui import Job

        self.show_preview_status('正在加载模板预览…')
        job = Job(lambda progress: (epoch, geometry_preview(template, key).encode()))
        self.preview_jobs[epoch] = job
        job.signals.completed.connect(self.layout_loaded)
        job.signals.failed.connect(lambda error: self.layout_failed(epoch, error))
        QtCore.QThreadPool.globalInstance().start(job)

    def show_preview_status(self, text):
        self.preview_status.setText(text)
        self.preview_stack.setCurrentWidget(self.preview_status)

    def layout_loaded(self, result):
        epoch, svg = result
        self.preview_jobs.pop(epoch, None)
        if epoch != self.preview_epoch:
            return
        if not self.preview.show_svg(svg):
            self.show_preview_status('模板预览渲染失败')
            return
        self.preview_stack.setCurrentWidget(self.preview)

    def layout_failed(self, epoch, error):
        self.preview_jobs.pop(epoch, None)
        if epoch == self.preview_epoch:
            self.show_preview_status('模板预览渲染失败\n' + error)

    def guard(self, callback):
        try:
            callback()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.error.setText(str(error))

    def load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '导入模板副本（原文件保留）', '', '模板 (*.json)')
        if path:
            self.guard(lambda: self.import_path(path))

    def import_path(self, path, *, revision_parent=None):
        entry = self.store.add(path, revision_parent=revision_parent)
        self.select_entry(entry)
        self.error.setText('已加入模板库；原文件、当前文档和默认设置未改变。')

    def select_entry(self, entry):
        with QtCore.QSignalBlocker(self.search), QtCore.QSignalBlocker(self.kind):
            self.search.clear()
            self.kind.setCurrentIndex(0)
        self.refresh()
        for i in range(self.list.count()):
            if (self.list.item(i).data(QtCore.Qt.UserRole).get('managed') or {}).get('id') == entry['id']:
                self.list.setCurrentRow(i)
                break

    def load_revision(self):
        data = self.selected()
        if not self.template or not data or not data['managed']:
            self.error.setText('请先选择库内模板作为上一修订。')
            return
        parent = self.template
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '选择新修订文件', '', '模板 (*.json)')
        if path and QtWidgets.QMessageBox.question(
            self, '确认模板修订关系',
            f'将“{Path(path).name}”作为库内“{data["managed"]["name"]}”的新修订？原版继续保留。',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No,
        ) == QtWidgets.QMessageBox.Yes:
            self.guard(lambda: self.import_path(path, revision_parent=parent))

    def add_selected(self):
        if data := self.selected():
            self.guard(lambda: self.import_path(data['path']))

    def open_template_folder(self):
        if data := self.selected():
            self.guard(lambda: open_containing_folder(data['path']))

    def create(self):
        choice, ok = QtWidgets.QInputDialog.getItem(self, '新建模板', '模板类型', ['简单模板', '自定义模板'], 0, False)
        if not ok:
            return
        from ..document.flow_template import PageLayout
        starter = None if choice == '简单模板' else PageLayout('layout-1', '初始空白版式')
        template = (FlowTemplate() if starter is None else FlowTemplate(
            name='自定义模板', kind='custom', layouts=(starter,), loop_pages=(starter.layout_id,)
        ))
        perform_template_action(self.editor, 'reusable', template, initial_blank=starter)
        self.refresh()

    def edit(self):
        def action():
            data = self.selected()
            template = self.read_selected()
            parent = data['managed']
            external_saved = False
            builtin_saved = False

            def save(candidate):
                nonlocal builtin_saved, external_saved
                if data.get('builtin'):
                    GlobalDefaultsStore().save_ordinary(template, candidate)
                    builtin_saved = True
                    return None
                if parent:
                    return self.store.save_revision(parent['id'], candidate)
                from .template_manager import save_external_template
                save_external_template(data['path'], template, candidate)
                external_saved = True

            revision = perform_template_action(self.editor, 'reusable', template, save_revision=save)
            if revision:
                self.select_entry(revision)
                self.error.setText('已保存到当前模板。旧版本可在“显示历史修订”中查看。')
            else:
                self.refresh()
                if builtin_saved:
                    self.error.setText('普通页面的纸张和边距已保存。已保存文档仍使用内嵌版式。')
                elif external_saved:
                    self.error.setText('已保存到原模板文件。')
        self.guard(action)

    def copy_template(self):
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

            store = GlobalDefaultsStore()
            defaults, warning = store.load()
            if warning:
                raise ValueError(warning)
            selected = self.read_selected()
            template = None if self.selected().get('builtin') else selected
            defaults = replace(defaults, flow=replace(defaults.flow, template=template))
            store.save(defaults)
            self.refresh()
            self.error.setText('已设为新文档默认；当前文档和字段内容不变。')
        self.guard(action)

    def export(self):
        from .template_manager import export_template_json

        self.guard(lambda: export_template_json(self, self.read_selected()))

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
