"""Reusable-template catalog and selectors, separate from document and defaults."""

import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.template_authoring import read_template, template_json
from .template_viewport import FitSvgPreview


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
        else f"自定义模板 · {len(template.start_pages)} 起始 / {len(template.loop_pages)} 循环页 · {len(template.fields)} 字段"
        if kind == "custom"
        else "旧版模板 · 保留原协议与绑定"
    )


def save_reusable_template(editor, path, template):
    from ..document.template_revision import version_template
    from ..resource_catalog import TemplateStore, workspace_for

    versioned = version_template(template)
    raw = template_json(versioned)
    from ..document.template_authoring import parse_template
    parse_template(raw)
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(raw)
    TemplateStore(workspace_for(editor) / 'templates').add(path)
    remember_template(path)

def export_template_json(parent, template):
    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        parent, '导出 JSON', template.name + '.json', '模板 (*.json)'
    )
    if path:
        with Path(path).open('x', encoding='utf-8') as stream:
            stream.write(template_json(template))


def copy_template_as(parent, editor, template):
    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        parent, '另存为新模板', '', '模板 (*.json)'
    )
    if path:
        save_reusable_template(editor, path, template)
    return path


def save_external_template(path, original, candidate):
    from ..document.template_authoring import parse_template
    from ..document.template_revision import version_template

    path = Path(path)
    if path.is_symlink():
        raise ValueError('不能覆盖符号链接指向的模板，请另存为新模板。')
    raw = template_json(version_template(candidate, parent=original))
    parse_template(raw)
    data = raw.encode('utf-8')
    save = QtCore.QSaveFile(str(path))
    if not save.open(QtCore.QIODevice.WriteOnly):
        raise OSError(save.errorString())
    try:
        if save.write(data) != len(data):
            raise OSError(save.errorString())
        if read_template(path) != original:
            raise ValueError('原模板文件已改变，请重新打开后编辑，或另存为新模板。')
        if not save.commit():
            raise OSError(save.errorString())
    finally:
        if save.isOpen():
            save.cancelWriting()


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
        from ..global_defaults import GlobalDefaultsStore
        try:
            ordinary = GlobalDefaultsStore().ordinary_template()
        except (ValueError, TypeError, OSError):
            ordinary = FlowTemplate(name="普通页面", mode="blank")
        self.options = [template, ordinary]
        self.list.addItem("普通页面 · 内置简单模板")
        from ..resource_catalog import TemplateStore, workspace_for
        self.store = TemplateStore(workspace_for(parent) / 'templates')
        try:
            for entry in self.store.entries():
                if not entry['archived']:
                    self.options.append(entry)
                    revision = entry.get('revision', {}).get('number', 1)
                    self.list.addItem(f'库内 · {entry["name"]} · 修订 {revision}')
        except (OSError, ValueError):
            self.list.addItem('模板库索引异常，请到模板库查看')
            self.options.append({'unavailable': True})
        for path in catalog_paths():
            self.options.append(path)
            self.list.addItem('最近文件 · ' + path.stem + (' · 文件已移动' if not path.exists() else ''))
        self.list.setCurrentRow(0)
        self.list.currentRowChanged.connect(self.select)
        row.addWidget(self.list, 1)
        self.preview = FitSvgPreview()
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
        self.import_button = QtWidgets.QPushButton("从文件导入…")
        self.import_button.clicked.connect(self.load)
        col.addWidget(self.import_button)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(
            "使用此默认模板" if default else "应用到当前文档"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        col.addWidget(self.buttons)
        self.select(0)

    def show_preview(self, candidate):
        from .template_library import preview_layouts

        self.preview_candidate = candidate
        with QtCore.QSignalBlocker(self.layout_picker):
            self.layout_picker.clear()
            for key, label in preview_layouts(candidate):
                self.layout_picker.addItem(label, key)
        self.render_layout()

    def render_layout(self, *_):
        from ..document.template_authoring import geometry_preview

        candidate = self.preview_candidate
        try:
            svg = (geometry_preview(candidate, self.layout_picker.currentData()).encode() if candidate else
                   b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 280"><rect width="200" height="280" fill="white" stroke="gray"/></svg>')
            if not self.preview.show_svg(svg):
                raise ValueError("模板预览渲染失败")
        except (ValueError, TypeError, KeyError, OSError) as error:
            self.preview_failed(str(error))
            return
        self.template = candidate
        self.summary.setText(description(candidate))
        self.error.clear()
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def preview_failed(self, error, *, clear_layouts=False):
        self.template = None
        if clear_layouts:
            self.preview_candidate = None
            with QtCore.QSignalBlocker(self.layout_picker):
                self.layout_picker.clear()
        self.summary.setText('模板不可预览')
        self.preview.clear()
        self.error.setText(error)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)

    def select(self, index):
        try:
            if not 0 <= index < len(self.options):
                raise ValueError('请选择模板')
            item = self.options[index]
            if isinstance(item, dict):
                if item.get('unavailable'):
                    raise ValueError('模板库索引异常，原数据保留')
                candidate = self.store.read(item)
            else:
                candidate = read_template(item) if isinstance(item, Path) else item
            self.show_preview(candidate)
        except (ValueError, TypeError, OSError, KeyError) as error:
            self.preview_failed(str(error), clear_layouts=True)

    def load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入模板库副本（原文件保留）", "", "模板 (*.json)")
        if path:
            try:
                entry = self.store.add(path)
                remember_template(path)
                row = next((i for i, item in enumerate(self.options)
                            if isinstance(item, dict) and item.get('id') == entry['id']), len(self.options))
                if row == len(self.options):
                    self.options.append(entry)
                    self.list.addItem(f'库内 · {entry["name"]} · 修订 {entry.get("revision", {}).get("number", 1)}')
                else:
                    self.options[row] = entry
                with QtCore.QSignalBlocker(self.list):
                    self.list.setCurrentRow(row)
                self.select(row)
            except (ValueError, TypeError, OSError, KeyError) as error:
                with QtCore.QSignalBlocker(self.list):
                    self.list.setCurrentRow(-1)
                self.preview_failed(str(error), clear_layouts=True)

    def accept(self):
        if self.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled():
            super().accept()


def perform_template_action(editor, action, template, *, target=None, save_revision=None, initial_blank=None):
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
            template, editor, editor=editor, document_mode=action == "document",
            save_revision=save_revision, initial_blank=initial_blank,
        )
    else:
        dialog = TemplateDesignerDialog(template, editor)
        dialog.setWindowTitle(
            "旧版模板 · 编辑当前文档版式" if action == "document" else
            "旧版模板 · 编辑现有模板" if save_revision is not None else "旧版模板 · 编辑可复用副本"
        )
        dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(
            "应用到当前文档" if action == "document" else
            "保存修改" if save_revision is not None else "另存为新模板…"
        )
        dialog.saved_revision = None
        if action != "document":
            dialog.buttons.accepted.disconnect()

            def save_legacy():
                try:
                    candidate = dialog.configuration()
                    if save_revision is not None:
                        dialog.saved_revision = save_revision(candidate)
                        dialog.accept()
                        return
                    if copy_template_as(dialog, editor, candidate):
                        dialog.accept()
                except (ValueError, TypeError, OSError, KeyError) as error:
                    dialog.error.setText(str(error))

            dialog.buttons.accepted.connect(save_legacy)
            if save_revision is not None:
                def run_file_action(callback):
                    try:
                        callback(dialog.configuration())
                    except (ValueError, TypeError, OSError, KeyError) as error:
                        dialog.error.setText(str(error))

                copy = dialog.buttons.addButton("另存为新模板…", QtWidgets.QDialogButtonBox.ActionRole)
                export = dialog.buttons.addButton("导出 JSON…", QtWidgets.QDialogButtonBox.ActionRole)
                copy.clicked.connect(lambda: run_file_action(
                    lambda candidate: copy_template_as(dialog, editor, candidate)
                ))
                export.clicked.connect(lambda: run_file_action(
                    lambda candidate: export_template_json(dialog, candidate)
                ))
    if target:
        dialog.focus_target(target)
    try:
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            if action == "document":
                editor.template_content_panel.apply_template(dialog.configuration())
            return dialog.saved_revision
    except (ValueError, TypeError, OSError) as error:
        QtWidgets.QMessageBox.warning(editor, "模板未应用", str(error))
    finally:
        dialog.deleteLater()
