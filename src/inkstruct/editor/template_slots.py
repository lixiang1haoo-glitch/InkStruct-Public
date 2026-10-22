"""Reusable field declarations edited transactionally, without document content."""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from ..document.template_slots import TemplateSlot, upgrade_template


class TemplateSlotsDialog(QtWidgets.QDialog):
    def __init__(self, template, parent=None):
        super().__init__(parent)
        self.template = template
        self.loading = False
        self.pending = False
        self.setWindowTitle("模板内容字段")
        self.resize(620, 560)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "字段声明保存在可复用模板中，实际文字在使用模板时绑定。"
            "首次添加字段会升级为 v2 模板；旧版程序无法读取。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.items = QtWidgets.QListWidget()
        self.items.currentRowChanged.connect(self.load_slot)
        layout.addWidget(self.items)
        form = QtWidgets.QFormLayout()
        self.slot_id, self.label = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.region, self.kind, self.pages, self.anchor = [QtWidgets.QComboBox() for _ in range(4)]
        for region in template.first.reserved:
            self.region.addItem(region.name, region.name)
        for label, kind in (
            ("任意完整块", "any"),
            ("段落或标题", "text"),
            ("独立公式", "math"),
            ("表格", "table"),
        ):
            self.kind.addItem(label, kind)
        self.required = QtWidgets.QCheckBox("必填，未绑定时阻止成品导出")
        self.pages.addItem("仅首页", "first")
        self.pages.addItem("每页重复", "all")
        self.scale = QtWidgets.QDoubleSpinBox()
        self.scale.setRange(0.25, 4)
        self.scale.setDecimals(6)
        self.anchor.addItem("不指定", None)
        for anchor in template.first.anchors:
            self.anchor.addItem(anchor.name, anchor.name)
        for label, widget in (
            ("稳定字段编号", self.slot_id),
            ("显示名称", self.label),
            ("填写区", self.region),
            ("内容类型", self.kind),
            ("是否必填", self.required),
            ("出现页面", self.pages),
            ("字号倍率", self.scale),
            ("首字基线锚点", self.anchor),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.new = QtWidgets.QPushButton("新建字段")
        self.new.clicked.connect(lambda: self.load_slot(-1))
        self.apply = QtWidgets.QPushButton("写入字段")
        self.apply.clicked.connect(self.apply_slot)
        self.remove = QtWidgets.QPushButton("删除选中字段")
        self.remove.clicked.connect(self.remove_slot)
        for button in (self.new, self.apply, self.remove):
            row.addWidget(button)
        layout.addLayout(row)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for control in (self.slot_id, self.label):
            control.textChanged.connect(self.mark_pending)
        for control in (self.region, self.kind, self.pages, self.anchor):
            control.currentIndexChanged.connect(self.mark_pending)
        self.required.toggled.connect(self.mark_pending)
        self.scale.valueChanged.connect(self.mark_pending)
        self.refresh()

    def mark_pending(self):
        if self.loading:
            return
        self.pending = True
        self.items.setEnabled(False)
        self.new.setEnabled(False)
        self.remove.setEnabled(False)

    def refresh(self, index=-1):
        self.loading = True
        self.items.clear()
        for s in getattr(self.template, "slots", ()):
            self.items.addItem(f"{s.label} · {s.slot_id} → {s.region}")
        self.items.setCurrentRow(index)
        self.loading = False
        self.load_slot(index)

    def load_slot(self, index):
        if self.loading:
            return
        self.loading = True
        self.edit_index = index
        self.items.setCurrentRow(index)
        slots = getattr(self.template, "slots", ())
        slot = slots[index] if 0 <= index < len(slots) else None
        self.slot_id.setText(slot.slot_id if slot else "")
        self.label.setText(slot.label if slot else "")
        for widget, value in (
            (self.region, slot.region if slot else self.region.itemData(0)),
            (self.kind, slot.kind if slot else "any"),
            (self.pages, slot.pages if slot else "first"),
            (self.anchor, slot.anchor if slot else None),
        ):
            widget.setCurrentIndex(widget.findData(value))
        self.required.setChecked(slot.required if slot else False)
        self.original_scale = slot.scale if slot else 1
        self.scale.setValue(self.original_scale)
        self.initial_scale = self.scale.value()
        self.loading = self.pending = False
        self.items.setEnabled(True)
        self.new.setEnabled(True)
        self.remove.setEnabled(slot is not None)
        self.error.clear()

    def apply_slot(self):
        try:
            slot = TemplateSlot(
                self.slot_id.text(),
                self.label.text(),
                self.region.currentData(),
                self.kind.currentData(),
                self.required.isChecked(),
                self.pages.currentData(),
                self.original_scale
                if self.scale.value() == self.initial_scale
                else self.scale.value(),
                self.anchor.currentData(),
            )
            template = upgrade_template(self.template)
            slots = list(template.slots)
            index = self.edit_index
            if 0 <= index < len(slots):
                slots[index] = slot
            else:
                index = len(slots)
                slots.append(slot)
            self.template = replace(template, slots=tuple(slots))
            self.refresh(index)
            return True
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return False

    def remove_slot(self):
        if 0 <= self.edit_index < len(getattr(self.template, "slots", ())):
            self.template = replace(
                self.template,
                slots=tuple(s for i, s in enumerate(self.template.slots) if i != self.edit_index),
            )
            self.refresh()

    def configuration(self):
        if self.pending:
            raise ValueError("字段属性尚未写入")
        return self.template

    def accept(self):
        if self.pending and not self.apply_slot():
            return
        super().accept()
