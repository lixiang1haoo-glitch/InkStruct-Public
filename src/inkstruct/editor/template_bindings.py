"""Source block bindings for fixed template regions, without copied field text."""

from PySide6 import QtCore, QtWidgets

from ..document.styles import FlowStyle
from ..document.template import TemplateBinding
from ..document.template_slots import KINDS

KIND_LABELS = {"any": "任意完整块", "text": "段落或标题", "math": "独立公式", "table": "表格"}


class TemplateBindingsWidget(QtWidgets.QWidget):
    def __init__(self, document, bindings, parent=None):
        super().__init__(parent)
        self.document = document
        self.bindings = tuple(bindings)
        self.template = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fields = QtWidgets.QListWidget()
        self.fields.setMaximumHeight(110)
        self.fields.currentRowChanged.connect(self.load_binding)
        layout.addWidget(self.fields)
        form = QtWidgets.QFormLayout()
        self.region = QtWidgets.QComboBox()
        self.anchor = QtWidgets.QComboBox()
        self.policy = QtWidgets.QComboBox()
        self.policy.addItem("仅首页", "first")
        self.policy.addItem("所有页（重复字段）", "all")
        self.scale = QtWidgets.QDoubleSpinBox()
        self.scale.setRange(0.25, 4)
        self.scale.setDecimals(4)
        self.scale.setValue(1)
        self.scale_initial = 1
        self.scale_original = 1
        self.nodes = QtWidgets.QListWidget()
        self.nodes.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.nodes.setMaximumHeight(130)
        if document:
            for node in document.nodes:
                text = document.source[node.span.start : node.span.end].replace("\n", " ")[:80]
                item = QtWidgets.QListWidgetItem(f"{node.kind} · {text}")
                item.setData(QtCore.Qt.ItemDataRole.UserRole, node.node_id)
                self.nodes.addItem(item)
        form.addRow("填写区域", self.region)
        form.addRow("源码块（可多选）", self.nodes)
        form.addRow("出现页面", self.policy)
        form.addRow("字号倍率", self.scale)
        form.addRow("首字基线锚点", self.anchor)
        layout.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("绑定所选源码块", self)
        self.apply_button.clicked.connect(self.apply_binding)
        row.addWidget(self.apply_button)
        self.remove_button = QtWidgets.QPushButton("解除选中绑定", self)
        self.remove_button.clicked.connect(self.remove_binding)
        row.addWidget(self.remove_button)
        layout.addLayout(row)
        self.error = QtWidgets.QLabel()
        self.error.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        note = QtWidgets.QLabel(
            "绑定后内容移出正文流，正文仍是唯一文本来源。只绑定完整顶层块；超出固定区域会阻止导出。字号倍率用于正文、数学与代码，表格保留独立尺寸。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.refresh()
        self.region.currentIndexChanged.connect(self.select_region)
        self.nodes.itemSelectionChanged.connect(self.update_apply_action)
        self.update_apply_action()

    def binding_prerequisite(self):
        if self.template is None:
            return "请先导入或设计页面模板。"
        if self.region.currentData() is None:
            return "请先在模板首页新增填写区，再选择目标区域。"
        if self.document is None or not self.nodes.count():
            return "请先在编辑器输入正文并完成预览。"
        if not self.nodes.selectedItems():
            return "请先选择要填入该区域的源码块；可按住 Ctrl / ⌘ 多选。"
        return ""

    def update_apply_action(self):
        reason = self.binding_prerequisite()
        self.apply_button.setEnabled(not reason)
        self.apply_button.setToolTip(reason or "将所选完整源码块绑定到目标填写区域")

    def selected_slot(self):
        return next(
            (
                s
                for s in getattr(self.template, "slots", ())
                if s.region == self.region.currentData()
            ),
            None,
        )

    def focus_region(self, region):
        """Select a binding, or an unbound field without inheriting other selections."""
        index = next((i for i, b in enumerate(self.bindings) if b.region == region), -1)
        self.fields.setCurrentRow(index)
        if index >= 0:
            self.load_binding(index)
        else:
            self.nodes.clearSelection()
            self.policy.setCurrentIndex(self.policy.findData("first"))
            self.anchor.setCurrentIndex(self.anchor.findData(None))
            self.scale.setValue(1)
            self.scale_initial = self.scale_original = 1
            self.region.setCurrentIndex(self.region.findData(region))
            self.select_region()
        self.remove_button.setEnabled(index >= 0)
        self.region.setFocus()
        return self.region.currentIndex() >= 0

    def select_region(self):
        slot = self.selected_slot()
        for control in (self.policy, self.scale, self.anchor):
            control.setEnabled(slot is None)
        if slot:
            self.policy.setCurrentIndex(self.policy.findData(slot.pages))
            self.scale.setValue(slot.scale)
            self.scale_initial, self.scale_original = self.scale.value(), slot.scale
            self.anchor.setCurrentIndex(self.anchor.findData(slot.anchor))
        self.update_apply_action()

    def set_template(self, template):
        self.template = template
        self.region.clear()
        self.anchor.clear()
        self.anchor.addItem("区域左上角（不指定锚点）", None)
        if template:
            slots = {s.region: s for s in getattr(template, "slots", ())}
            for region in template.first.reserved:
                slot = slots.get(region.name)
                self.region.addItem(
                    f"{slot.label if slot else region.name} · {region.width_mm:g} × {region.height_mm:g} mm"
                    + (
                        f" · {KIND_LABELS[slot.kind]} · {'必填' if slot.required else '选填'}"
                        if slot
                        else ""
                    ),
                    region.name,
                )
            for anchor in template.first.anchors:
                self.anchor.addItem(anchor.name, anchor.name)
        self.refresh()
        self.select_region()

    def refresh(self):
        current = self.fields.currentRow()
        with QtCore.QSignalBlocker(self.fields):
            self.fields.clear()
            nodes = {n.node_id: n for n in self.document.nodes} if self.document else {}
            for binding in self.bindings:
                labels = []
                for node_id in binding.node_ids:
                    node = nodes.get(node_id)
                    labels.append(
                        self.document.source[node.span.start : node.span.end].replace("\n", " ")[
                            :35
                        ]
                        if node
                        else "源码块已失效"
                    )
                self.fields.addItem(
                    f"{binding.region} · {'所有页' if binding.pages == 'all' else '首页'} · {' / '.join(labels)}"
                )
        if self.bindings:
            self.fields.setCurrentRow(min(max(current, 0), len(self.bindings) - 1))
        self.remove_button.setEnabled(bool(self.bindings))

    def load_binding(self, index):
        if not 0 <= index < len(self.bindings):
            return
        binding = self.bindings[index]
        self.region.setCurrentIndex(self.region.findData(binding.region))
        self.policy.setCurrentIndex(self.policy.findData(binding.pages))
        self.anchor.setCurrentIndex(self.anchor.findData(binding.anchor))
        self.scale.setValue(binding.scale)
        self.scale_initial = self.scale.value()
        self.scale_original = binding.scale
        for i in range(self.nodes.count()):
            item = self.nodes.item(i)
            item.setSelected(item.data(QtCore.Qt.ItemDataRole.UserRole) in binding.node_ids)
        self.select_region()

    def apply_binding(self):
        reason = self.binding_prerequisite()
        if reason:
            self.error.setText(reason)
            return
        try:
            region = self.region.currentData()
            node_ids = tuple(
                self.nodes.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
                for i in range(self.nodes.count())
                if self.nodes.item(i).isSelected()
            )
            scale = (
                self.scale_original
                if self.scale.value() == self.scale_initial
                else self.scale.value()
            )
            binding = TemplateBinding(
                region, node_ids, self.policy.currentData(), scale, self.anchor.currentData()
            )
            slot = self.selected_slot()
            if slot:
                binding = slot.bind(node_ids)
                kinds = KINDS[slot.kind]
                if kinds is not None and any(
                    n.kind not in kinds for n in self.document.nodes if n.node_id in node_ids
                ):
                    raise ValueError(
                        f"字段“{slot.label}”不接受所选内容类型（要求 {KIND_LABELS[slot.kind]}）"
                    )
            if binding.pages == "all":
                if not any(r.name == region for r in self.template.continuation.reserved):
                    raise ValueError("续页缺少同名填写区域，无法在所有页重复")
                if binding.anchor and not any(
                    a.name == binding.anchor for a in self.template.continuation.anchors
                ):
                    raise ValueError("续页缺少同名基线锚点")
            bindings = tuple(b for b in self.bindings if b.region != region) + (binding,)
            FlowStyle(template=self.template, template_bindings=bindings)
            self.bindings = bindings
            self.error.clear()
            self.refresh()
            self.fields.setCurrentRow(len(bindings) - 1)
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))

    def remove_binding(self):
        index = self.fields.currentRow()
        if 0 <= index < len(self.bindings):
            self.bindings = self.bindings[:index] + self.bindings[index + 1 :]
            self.error.clear()
            self.refresh()
