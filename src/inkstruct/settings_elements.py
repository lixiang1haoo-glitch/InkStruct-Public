"""Independent draft editors for table/image scopes, with explicit inheritance."""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from .document.tables import table_model
from .settings_pages import acceptable, embed, label


class ElementPage(QtWidgets.QWidget):
    def __init__(self, kind, document, flow, *, scrollable=True):
        super().__init__()
        self.kind, self.flow = kind, flow
        self.document = document
        self.scrollable = scrollable
        self.nodes = [n for root in document.nodes for n in root.walk() if n.kind == kind]
        self.editors, self.independent = {}, {}
        self.current_key = None
        column = QtWidgets.QVBoxLayout(self)
        self.explanation = label("独立属性仅影响选中的元素；沿用默认时使用本文保存的默认值。")
        column.addWidget(self.explanation)
        self.scope = QtWidgets.QComboBox()
        self.scope.setAccessibleName("设置对象")
        self.scope.addItem("文档默认", None)
        for i, node in enumerate(self.nodes, 1):
            preview = document.source[node.span.start : node.span.end].replace("\n", " ")[:36]
            name = "表格" if kind == "table" else "图片"
            self.scope.addItem(f"{name} {i} · {preview}", node.node_id)
        column.addWidget(self.scope)
        row = QtWidgets.QHBoxLayout()
        self.inherit = QtWidgets.QRadioButton("沿用文档默认")
        self.custom = QtWidgets.QRadioButton("独立设置")
        self.group = QtWidgets.QButtonGroup(self)
        self.group.addButton(self.inherit)
        self.group.addButton(self.custom)
        row.addWidget(self.inherit)
        row.addWidget(self.custom)
        row.addStretch()
        column.addLayout(row)
        self.status = label("")
        column.addWidget(self.status)
        self.stack = QtWidgets.QStackedWidget()
        column.addWidget(self.stack)
        column.addStretch()
        self.scope.currentIndexChanged.connect(self.select_scope)
        self.custom.toggled.connect(self.toggle_independent)
        self.select_scope()

    def make_editor(self, key, style):
        if self.kind == "table":
            from .editor.table_settings import TableSettingsDialog

            node = next((n for n in self.nodes if n.node_id == key), None)
            flow = replace(self.flow, table=style)
            editor = TableSettingsDialog(
                flow, columns=table_model(node).columns if node else None, scrollable=self.scrollable
            )
            editor.scope.hide()
            editor.inherit.hide()
            editor.scope_info.hide()
            form = editor.findChild(QtWidgets.QFormLayout)
            for control in (editor.scope,):
                field_label = form.labelForField(control)
                if field_label:
                    field_label.hide()
            form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        else:
            from .editor.image_settings import ImageSettingsDialog

            overrides = dict(self.flow.image_overrides)
            if key:
                overrides[key] = style
            editor = ImageSettingsDialog(
                self.document,
                replace(self.flow, image=style, image_overrides=tuple(overrides.items())),
            )
            editor.picker.setCurrentIndex(max(0, editor.picker.findData(key)))
            editor.picker.hide()
            editor.inherit.hide()
            editor.scope_info.hide()
            field_label = editor.layout().labelForField(editor.picker)
            if field_label:
                field_label.hide()
            editor.layout().setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        embed(editor)
        self.stack.addWidget(editor)
        return editor

    def style_for_editor(self, editor, key):
        acceptable(editor)
        if self.kind == "table":
            _, style = editor.configuration()
            if key:
                columns = table_model(next(n for n in self.nodes if n.node_id == key)).columns
                if any(
                    values and len(values) != columns
                    for values in (style.columns, style.column_alignments)
                ):
                    raise ValueError(f"当前表格需要 {columns} 项列设置")
            return style
        flow = editor.configuration()
        return flow.image_for(key) if key else flow.image

    def default_style(self):
        return (
            self.style_for_editor(self.editors[None], None)
            if None in self.editors
            else getattr(self.flow, self.kind)
        )

    def select_scope(self):
        key = self.scope.currentData()
        self.current_key = key
        overrides = dict(getattr(self.flow, self.kind + "_overrides"))
        if key not in self.editors:
            try:
                default = self.default_style()
            except ValueError:
                default = getattr(self.flow, self.kind)
            style = overrides.get(key, default) if key else default
            self.editors[key] = self.make_editor(key, style)
            self.independent[key] = key in overrides
        if key and not self.independent[key]:
            # Reflect edited defaults without converting inheritance into an override.
            try:
                default = self.default_style()
                old = self.editors[key]
                self.editors[key] = self.make_editor(key, default)
                self.stack.removeWidget(old)
                old.deleteLater()
            except ValueError:
                pass  # Keep the draft; Apply will identify the invalid default.
        with QtCore.QSignalBlocker(self.custom), QtCore.QSignalBlocker(self.inherit):
            self.custom.setChecked(bool(key and self.independent[key]))
            self.inherit.setChecked(bool(key and not self.independent[key]))
        self.custom.setVisible(bool(key))
        self.inherit.setVisible(bool(key))
        editor = self.editors[key]
        self.stack.setCurrentWidget(editor)
        editor.setEnabled(not key or self.independent[key])
        self.status.setText(
            "正在编辑文档默认设置"
            if not key
            else "当前元素：独立设置"
            if self.independent[key]
            else "当前元素沿用文档默认，选择“独立设置”后可修改"
        )

    def toggle_independent(self, checked):
        if not self.current_key:
            return
        self.independent[self.current_key] = checked
        self.editors[self.current_key].setEnabled(checked)
        self.status.setText("当前元素：独立设置" if checked else "当前元素沿用文档默认")

    def configuration(self):
        default = self.default_style()
        overrides = dict(getattr(self.flow, self.kind + "_overrides"))
        resources = {r.source: r for r in self.flow.images}
        original_resources = dict(resources)
        for key, editor in self.editors.items():
            try:
                if key:
                    if self.independent[key]:
                        overrides[key] = self.style_for_editor(editor, key)
                    else:
                        overrides.pop(key, None)
                if self.kind == "image":
                    for resource in editor.flow.images:
                        if resource != original_resources.get(resource.source):
                            resources[resource.source] = resource
            except ValueError:
                self.scope.setCurrentIndex(self.scope.findData(key))
                raise
        changes = {self.kind: default, self.kind + "_overrides": tuple(overrides.items())}
        if self.kind == "image":
            changes["images"] = tuple(resources.values())
        return changes

    def reset_defaults(self):
        key = self.current_key
        old = self.editors[key]
        style = type(getattr(self.flow, self.kind))() if key is None else self.default_style()
        if key is None and self.kind == 'image':
            style = replace(style, height_mm=60)
        self.editors[key] = self.make_editor(key, style)
        if key:
            self.independent[key] = False
        self.stack.removeWidget(old)
        old.deleteLater()
        self.select_scope()
