"""Reusable-template catalog and selectors, separate from document and defaults."""

import json
from pathlib import Path

from PySide6 import QtCore, QtSvgWidgets, QtWidgets

from ..document.flow_template import FlowTemplate, PageLayout
from ..document.template_authoring import read_template, template_json


def catalog_settings():
    return QtCore.QSettings(
        QtCore.QSettings.defaultFormat(), QtCore.QSettings.UserScope, "InkStruct", "TemplateCatalog"
    )


def catalog_paths():
    settings = catalog_settings()
    try:
        value = json.loads(settings.value("recent_paths", "[]", str))
        if not isinstance(value, list):
            return []
        return [Path(p) for p in value[:40] if isinstance(p, str)]
    except (ValueError, TypeError):
        return []


def remember_template(path):
    path = Path(path).absolute()
    paths = [path, *(p for p in catalog_paths() if p != path)]
    catalog_settings().setValue("recent_paths", json.dumps([str(p) for p in paths[:40]]))


def description(template):
    if template is None:
        return "普通页面 · 连续正文自动分页"
    kind = getattr(template, "kind", "legacy")
    return f"{template.name}\n{template.width_mm:g} × {template.height_mm:g} mm · " + (
        "简单模板"
        if kind == "simple"
        else f"自定义模板 · {len(template.start_pages)} 起始 / {len(template.loop_pages)} 循环布局 · {len(template.fields)} 字段"
        if kind == "custom"
        else "旧版模板 · 保留原协议与绑定"
    )


class TemplatePicker(QtWidgets.QDialog):
    def __init__(self, template=None, parent=None, *, default=False):
        super().__init__(parent)
        self.template = template
        self.setWindowTitle("选择新文档默认模板" if default else "更换当前文档模板")
        self.resize(780, 540)
        col = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel(description(template))
        self.summary.setTextFormat(QtCore.Qt.PlainText)
        self.summary.setWordWrap(True)
        col.addWidget(self.summary)
        row = QtWidgets.QHBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.list.setMinimumHeight(80)
        self.list.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        self.list.addItem("保留当前选择")
        self.options = [template, None]
        self.list.addItem("普通页面（不使用模板）")
        from ..resource_catalog import TemplateStore, workspace_for
        self.store = TemplateStore(workspace_for(parent) / 'templates')
        try:
            for entry in self.store.entries():
                if not entry['archived']:
                    self.options.append(entry)
                    self.list.addItem('库内 · ' + entry['name'])
        except (OSError, ValueError):
            self.list.addItem('模板库索引异常，请到字体与模板查看')
            self.options.append({'unavailable': True})
        for path in catalog_paths():
            self.options.append(path)
            self.list.addItem('最近文件 · ' + path.stem + (' · 文件已移动' if not path.exists() else ''))
        self.list.setCurrentRow(0)
        self.list.currentRowChanged.connect(self.select)
        row.addWidget(self.list, 1)
        self.preview = QtSvgWidgets.QSvgWidget()
        pane = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(pane)
        self.layout_picker = QtWidgets.QComboBox()
        self.layout_picker.currentIndexChanged.connect(self.render_layout)
        right.addWidget(self.layout_picker)
        right.addWidget(self.preview, 1)
        row.addWidget(pane, 2)
        col.addLayout(row, 1)
        note = QtWidgets.QLabel(
            "模板副本随文档保存；更换保留正文、排版样式、资源和冻结选样。"
            if not default
            else "只设置以后新建文档使用的默认模板，不修改当前文档。"
        )
        note.setWordWrap(True)
        col.addWidget(note)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        col.addWidget(self.error)
        load = QtWidgets.QPushButton("从文件导入…")
        load.clicked.connect(self.load)
        col.addWidget(load)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(
            "使用此默认模板" if default else "应用到当前文档"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        col.addWidget(self.buttons)
        self.show_preview()

    def show_preview(self):
        self.summary.setText(description(self.template))
        with QtCore.QSignalBlocker(self.layout_picker):
            self.layout_picker.clear()
            if isinstance(self.template, FlowTemplate):
                for layout in self.template.effective_layouts:
                    self.layout_picker.addItem(layout.label, layout.layout_id)
            elif self.template:
                self.layout_picker.addItem('首页', 'first')
                self.layout_picker.addItem('续页', 'continuation')
        self.render_layout()
        self.error.clear()
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def render_layout(self, *_):
        if isinstance(self.template, FlowTemplate):
            from ..document.flow_template_preview import geometry_preview
            self.preview.load(
                geometry_preview(
                    self.template, self.layout_picker.currentData() or self.template.effective_layouts[0].layout_id
                ).encode()
            )
        elif self.template is not None:
            from ..document.template_authoring import geometry_preview as legacy_preview

            self.preview.load(legacy_preview(self.template, self.layout_picker.currentData() or 'first').encode())
        else:
            self.preview.load(
                b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="280"><rect width="200" height="280" fill="white" stroke="gray"/></svg>'
            )
        self.preview.renderer().setAspectRatioMode(QtCore.Qt.KeepAspectRatio)

    def select(self, index):
        try:
            item = self.options[index]
            if isinstance(item, dict):
                if item.get('unavailable'):
                    raise ValueError('模板库索引异常，原数据保留')
                self.template = self.store.read(item)
            else:
                self.template = read_template(item) if isinstance(item, Path) else item
            self.show_preview()
        except (ValueError, TypeError, OSError) as error:
            self.error.setText(str(error))
            self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)

    def load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入模板库副本（原文件保留）", "", "模板 (*.json)")
        if path:
            try:
                self.template = self.store.read(self.store.add(path))
                remember_template(path)
                self.show_preview()
            except (ValueError, TypeError, OSError) as error:
                self.error.setText(str(error))
                self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)


class DefaultTemplateChoice(QtWidgets.QWidget):
    def __init__(self, template, parent=None):
        super().__init__(parent)
        self.template = template
        col = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel()
        self.summary.setTextFormat(QtCore.Qt.PlainText)
        self.summary.setWordWrap(True)
        col.addWidget(self.summary)
        b = QtWidgets.QPushButton("选择新文档默认模板…")
        b.clicked.connect(self.choose)
        col.addWidget(b)
        self.set_template(template)

    def set_template(self, template):
        self.template = template
        self.summary.setText(description(template))

    def choose(self):
        d = TemplatePicker(self.template, self, default=True)
        try:
            if d.exec() == QtWidgets.QDialog.Accepted:
                self.set_template(d.template)
        finally:
            d.deleteLater()

    def configuration(self):
        return self.template

    def binding_configuration(self):
        return ()


class TemplateManagerPage(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        col = QtWidgets.QVBoxLayout(self)
        current = QtWidgets.QGroupBox("当前文档布局")
        box = QtWidgets.QVBoxLayout(current)
        info = QtWidgets.QLabel(description(owner.editor.flow.template))
        info.setTextFormat(QtCore.Qt.PlainText)
        info.setWordWrap(True)
        box.addWidget(info)
        b = QtWidgets.QPushButton("编辑当前文档布局…")
        b.clicked.connect(
            lambda: owner.request_template_action("document", owner.editor.flow.template)
        )
        box.addWidget(b)
        col.addWidget(current)
        col.addWidget(QtWidgets.QLabel("可复用模板 · 编辑副本不会修改原文件或当前文档"))
        self.list = QtWidgets.QListWidget()
        self.list.setMinimumHeight(80)
        self.list.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)
        for path in catalog_paths():
            item = QtWidgets.QListWidgetItem(path.stem)
            item.setToolTip(str(path))
            item.setData(QtCore.Qt.UserRole, str(path))
            self.list.addItem(item)
        col.addWidget(self.list, 1)
        row = QtWidgets.QHBoxLayout()
        for text, call in [
            ("新建模板…", self.create),
            ("导入模板…", self.load),
            ("编辑副本…", self.edit_copy),
        ]:
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(call)
            row.addWidget(b)
        col.addLayout(row)
        migrate = QtWidgets.QToolButton()
        migrate.setText("高级操作")
        migrate.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        migration_menu = QtWidgets.QMenu(migrate)
        migration_menu.addAction("显式复制旧布局为新模板…", self.migrate_copy)
        migrate.setMenu(migration_menu)
        col.addWidget(migrate)
        self.error = QtWidgets.QLabel(
            "进入工作台前退出设置；工作台单独确认，不会被设置窗口的取消影响。"
        )
        self.error.setWordWrap(True)
        col.addWidget(self.error)

    def create(self):
        kind, ok = QtWidgets.QInputDialog.getItem(
            self,
            "新建模板",
            "选择模板类型",
            ["简单模板：纸张与四向边距", "自定义模板：背景、页组与文本框"],
            0,
            False,
        )
        if ok:
            template = (
                FlowTemplate()
                if kind.startswith("简单")
                else FlowTemplate(
                    name="自定义模板",
                    kind="custom",
                    layouts=(PageLayout("layout-1", "布局 1"),),
                    loop_pages=("layout-1",),
                )
            )
            self.owner.request_template_action("reusable", template)

    def load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入可复用模板", "", "模板 (*.json)")
        if path:
            try:
                template = read_template(path)
                remember_template(path)
                item = QtWidgets.QListWidgetItem(
                    template.name + (" · 旧版" if not isinstance(template, FlowTemplate) else "")
                )
                item.setData(QtCore.Qt.UserRole, path)
                item.setToolTip(path)
                self.list.addItem(item)
                self.list.setCurrentItem(item)
                self.error.setText("已加入最近使用列表；当前文档和默认设置未改变。")
            except (ValueError, TypeError, OSError) as error:
                self.error.setText(str(error))

    def edit_copy(self):
        item = self.list.currentItem()
        if item:
            try:
                self.owner.request_template_action(
                    "reusable", read_template(item.data(QtCore.Qt.UserRole))
                )
            except (ValueError, TypeError, OSError) as error:
                self.error.setText(str(error))
        else:
            self.error.setText("请先选择或导入模板。")

    def migrate_copy(self):
        item = self.list.currentItem()
        try:
            if item is None:
                raise ValueError("请先选择已导入的旧版模板。")
            template = read_template(item.data(QtCore.Qt.UserRole))
            if isinstance(template, FlowTemplate):
                raise TypeError("此模板已使用现有字段协议，无需迁移。")
            from ..document.flow_template import migrate_layout

            candidate = migrate_layout(template)
            self.owner.request_template_action("reusable", candidate)
        except (ValueError, TypeError, OSError) as error:
            self.error.setText(str(error))


def perform_template_action(editor, action, template, *, target=None):
    from .flow_template_designer import FlowTemplateDesigner
    from .template_designer import TemplateDesignerDialog

    modern = template is None or isinstance(template, FlowTemplate)
    template = template or FlowTemplate(
        width_mm=editor.page.width_mm,
        height_mm=editor.page.height_mm,
        margins_mm=(editor.page.margin_mm,) * 4,
    )
    if modern:
        dialog = FlowTemplateDesigner(
            template, editor, editor=editor, document_mode=action == "document"
        )
    else:
        dialog = TemplateDesignerDialog(template, editor)
        dialog.setWindowTitle(
            "旧版模板 · 编辑当前文档布局" if action == "document" else "旧版模板 · 编辑可复用副本"
        )
        dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(
            "应用到当前文档" if action == "document" else "保存为新模板…"
        )
        if action != "document":
            dialog.buttons.accepted.disconnect()

            def save_legacy():
                try:
                    candidate = dialog.configuration()
                    path, _ = QtWidgets.QFileDialog.getSaveFileName(
                        dialog, "保存旧模板副本（保留原文件）", "", "模板 (*.json)"
                    )
                    if not path:
                        return
                    with Path(path).open("x", encoding="utf-8") as stream:
                        stream.write(template_json(candidate))
                    remember_template(path)
                    from ..resource_catalog import TemplateStore, workspace_for
                    TemplateStore(workspace_for(editor) / 'templates').add(path)
                    dialog.accept()
                except (ValueError, TypeError, OSError) as error:
                    dialog.error.setText(str(error))

            dialog.buttons.accepted.connect(save_legacy)
    if target:
        dialog.focus_target(target)
    try:
        if dialog.exec() == QtWidgets.QDialog.Accepted and action == "document":
            editor.template_content_panel.apply_template(dialog.configuration())
    except (ValueError, TypeError, OSError) as error:
        QtWidgets.QMessageBox.warning(editor, "模板未应用", str(error))
    finally:
        dialog.deleteLater()
