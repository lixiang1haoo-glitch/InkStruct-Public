"""Import measured templates and choose printing mode without editing source text."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..document.template_authoring import read_template
from .template_bindings import TemplateBindingsWidget


class TemplateSettingsDialog(QtWidgets.QDialog):
    def __init__(
        self, template, parent=None, *, document=None, bindings=(), target=None, reason=""
    ):
        super().__init__(parent)
        self.original = template
        self.template = template
        self.target = target
        self.setWindowTitle("页面模板")
        self.resize(520, 300)
        self.form = QtWidgets.QFormLayout(self)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        self.form.addRow(self.summary)
        buttons = QtWidgets.QHBoxLayout()
        load = QtWidgets.QPushButton("导入模板 JSON…", self)
        load.clicked.connect(self.choose_template)
        buttons.addWidget(load)
        design = QtWidgets.QPushButton("新建 / 设计模板…", self)
        design.clicked.connect(self.design_template)
        buttons.addWidget(design)
        clear = QtWidgets.QPushButton("使用简单页面", self)
        clear.clicked.connect(lambda: self.set_template(None))
        buttons.addWidget(clear)
        self.form.addRow(buttons)
        modern = QtWidgets.QHBoxLayout()
        for text,kind in (("新建简单模板…","simple"),("新建自定义模板…","custom")):
            b=QtWidgets.QPushButton(text,self)
            b.clicked.connect(lambda checked=False,kind=kind:self.new_flow_template(kind))
            modern.addWidget(b)
        self.form.addRow(modern)
        self.migrate_button=QtWidgets.QPushButton("迁移旧版式为 v3…（保留原文件与正文）",self)
        self.migrate_button.clicked.connect(self.migrate)
        self.form.addRow(self.migrate_button)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("预印纸：框线和底图仅预览", "preprinted")
        self.mode.addItem("空白纸：绘制配置的框线", "blank")
        self.form.addRow("用纸模式", self.mode)
        self.controls, self.initial = {}, {}
        for name, label in (("offset_x_mm", "横向校准偏移"), ("offset_y_mm", "纵向校准偏移")):
            control = QtWidgets.QDoubleSpinBox()
            control.setRange(-2000, 2000)
            control.setDecimals(4)
            control.setSuffix(" mm")
            self.form.addRow(label, control)
            self.controls[name] = control
        note = QtWidgets.QLabel(
            "底图固定在纸面，偏移只移动书写内容。空白纸仅输出明确配置的框线，不会描摹扫描标题或条码。"
        )
        note.setWordWrap(True)
        self.form.addRow(note)
        self.binding_editor = TemplateBindingsWidget(document, bindings, self)
        self.form.addRow(self.binding_editor)
        self.rename_button = QtWidgets.QPushButton("联动重命名填写区 / 锚点…", self)
        self.rename_button.clicked.connect(self.rename_reference)
        self.form.addRow(self.rename_button)
        self.diagnostic_note = QtWidgets.QLabel()
        self.diagnostic_note.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.diagnostic_note.setWordWrap(True)
        if target:
            page = f" · 第 {target.page_index + 1} 页" if target.page_index is not None else ""
            face=('首页' if target.face=='first' else '续页')
            if getattr(template,'schema_version','')=='inkstruct_page_template_v3':
                face=next((p.label for p in template.effective_layouts if p.layout_id==target.face),'字段声明')
            self.diagnostic_note.setText(
                f"本次排版提示（修改后重新检查）：{face}{page} · "
                f"{target.slot_id or target.region}\n{reason}"
            )
        self.form.addRow(self.diagnostic_note)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.form.addRow(self.error)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.form.addRow(self.buttons)
        self.set_template(template)
        if target:
            self.binding_editor.focus_region(target.region)

    def set_template(self, template):
        from ..document.flow_template import FlowTemplate
        modern=isinstance(template,FlowTemplate)
        if modern and self.binding_editor.bindings:
            raise ValueError('旧源码绑定尚未解除；请先保留原项目并显式处理内容对应，不会自动丢弃绑定。')
        self.template = template
        self.rename_button.setEnabled(template is not None and not modern)
        self.rename_button.setVisible(template is not None and not modern)
        self.migrate_button.setVisible(template is not None and not modern)
        self.summary.setText(
            f"{template.name} · {template.width_mm:.3f} × {template.height_mm:.3f} mm"
            if template
            else "简单页面：连续正文自动分页；可新建带四向边距的简单模板。"
        )
        self.mode.setEnabled(template is not None)
        self.mode.setCurrentIndex(self.mode.findData(template.mode if template else "preprinted"))
        for name, control in self.controls.items():
            control.setEnabled(template is not None)
            control.setValue(getattr(template, name) if template else 0)
            self.initial[name] = control.value()
        self.error.clear()
        if template is None:
            self.binding_editor.bindings = ()
        self.binding_editor.set_template(None if modern else template)
        self.binding_editor.setVisible(not modern and template is not None)

    def choose_template(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入页面模板", "", "JSON (*.json)")
        if path:
            try:
                file = Path(path)
                if file.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("模板文件超过 16 MiB")
                self.set_template(read_template(file))
            except (OSError, ValueError, TypeError) as error:
                self.error.setText(str(error))

    def design_template(self):
        from ..document.flow_template import FlowTemplate
        from .flow_template_designer import FlowTemplateDesigner
        from .template_designer import TemplateDesignerDialog

        try:
            modern=self.template is None or isinstance(self.template,FlowTemplate)
            dialog = (FlowTemplateDesigner(self.configuration(),self) if modern else
                      TemplateDesignerDialog(self.configuration(), self))
            if self.target:
                dialog.focus_target(self.target)
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.set_template(dialog.configuration())
        dialog.deleteLater()

    def new_flow_template(self,kind):
        from ..document.flow_template import FlowTemplate, PageLayout
        from .flow_template_designer import FlowTemplateDesigner
        t=FlowTemplate() if kind=='simple' else FlowTemplate(name='自定义模板',kind='custom',layouts=(PageLayout('layout-1','初始空白版式'),),loop_pages=('layout-1',))
        dialog=FlowTemplateDesigner(t,self)
        try:
            if dialog.exec()==QtWidgets.QDialog.DialogCode.Accepted:
                if self.binding_editor.bindings:
                    raise ValueError('当前存在旧源码块绑定。请先另存原项目，再在新项目中显式解除绑定并填写命名字段；不会自动迁移正文。')
                self.set_template(dialog.configuration())
        except (ValueError,TypeError) as error:
            self.error.setText(str(error))
        finally:
            dialog.deleteLater()

    def migrate(self):
        from ..document.flow_template import migrate_layout
        from .flow_template_designer import FlowTemplateDesigner
        try:
            if self.binding_editor.bindings:
                raise ValueError('本项目的旧绑定和正文保持原样。请先导出旧模板 JSON，在新项目中导入后显式迁移页面版式并人工对应字段；不能自动改写绑定正文。')
            candidate=migrate_layout(self.configuration())
            dialog=FlowTemplateDesigner(candidate,self)
            try:
                if dialog.exec()==QtWidgets.QDialog.DialogCode.Accepted:
                    self.set_template(dialog.configuration())
            finally:
                dialog.deleteLater()
        except (ValueError,TypeError) as error:
            self.error.setText(str(error))

    def configuration(self):
        if self.template is None:
            return None
        changes = {k: c.value() for k, c in self.controls.items() if c.value() != self.initial[k]}
        return replace(self.template, mode=self.mode.currentData(), **changes)

    def rename_reference(self):
        from .template_rename import TemplateRenameDialog

        try:
            template = self.configuration()
            if template is None:
                return
            dialog = TemplateRenameDialog(
                template,
                self.binding_configuration(),
                self,
                region=self.binding_editor.region.currentData(),
            )
            try:
                if dialog.exec() != QtWidgets.QDialog.Accepted:
                    return
                updated, bindings = dialog.configuration()
                kind, old, new = (
                    dialog.kind.currentData(),
                    dialog.old_name.currentText(),
                    dialog.new_name.text(),
                )
            finally:
                dialog.deleteLater()
            self.binding_editor.bindings = bindings
            if self.target:
                key = "region" if kind == "region" else "anchor"
                if getattr(self.target, key) == old:
                    self.target = replace(self.target, **{key: new})
            self.set_template(updated)
            if kind == "region":
                self.binding_editor.focus_region(new)
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))

    def binding_configuration(self):
        from ..document.flow_template import FlowTemplate
        return self.binding_editor.bindings if self.template and not isinstance(self.template,FlowTemplate) else ()

    def accept(self):
        try:
            self.configuration()
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()
