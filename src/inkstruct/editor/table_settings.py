"""Table style dialog; accept applies a single configuration transaction."""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

LABELS = {"auto": "沿用", "left": "左", "center": "中", "right": "右", "decimal": "小数点"}


class TableSettingsDialog(QtWidgets.QDialog):
    def __init__(self, flow, node_id=None, columns=None, parent=None, *, tables=None, scrollable=True):
        super().__init__(parent)
        self.flow, self.node_id, self.columns = flow, node_id, columns
        self.setWindowTitle("表格设置")
        self.resize(530, 690)
        self.setObjectName("table_settings_dialog")
        self.setStyleSheet('QCheckBox::indicator:unchecked {background: transparent; border: 1px solid #8995a5; border-radius: 2px;}')
        layout = QtWidgets.QVBoxLayout(self)
        content = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(content)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        if scrollable:
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            layout.addWidget(scroll, 1)
        else:
            layout.addWidget(content)
        self.scope = QtWidgets.QComboBox()
        self.scope.addItem("文档默认（已有独立设置的表格不变）", None)
        self.column_counts = {key: count for key, count, _ in (tables or [])}
        if tables is not None:
            for key, count, label in tables:
                self.scope.addItem(label + " · 个性化设置", key)
            if node_id:
                self.scope.setCurrentIndex(max(0, self.scope.findData(node_id)))
        elif node_id:
            self.column_counts[node_id] = columns
            self.scope.addItem(f"当前表格（{columns} 列）", node_id)
            self.scope.setCurrentIndex(1)
        form.addRow("应用范围", self.scope)
        self.inherit = QtWidgets.QCheckBox("当前表格恢复沿用文档默认")
        form.addRow(self.inherit)
        self.scope_info = QtWidgets.QLabel()
        self.scope_info.setWordWrap(True)
        form.addRow(self.scope_info)
        self.total_mode = QtWidgets.QComboBox()
        self.total_mode.addItem("手动指定", "fixed")
        self.total_mode.addItem("按内容确定", "content")
        self.total_mode.setToolTip("按内容确定时，表格随内容收窄，最多占用正文框的可用宽度。")
        form.addRow("总宽方式", self.total_mode)
        self.controls = {}
        for key, label in (
            ("width_mm", "表格总宽"),
            ("min_row_height_mm", "行高"),
            ("digit_height_mm", "数字高度"),
            ("text_em_mm", "其他文字大小"),
            ("line_height_mm", "格内文字行高"),
            ("stroke_width_mm", "笔宽"),
            ("padding_top_mm", "上留白"),
            ("padding_right_mm", "右留白"),
            ("padding_bottom_mm", "下留白"),
            ("padding_left_mm", "左留白"),
        ):
            widget = QtWidgets.QDoubleSpinBox()
            widget.setObjectName(key)
            widget.setDecimals(4)
            widget.setRange(
                0 if key.startswith("padding") else 0.0001,
                100 if key.startswith("padding") else 2000,
            )
            widget.setSuffix(" mm")
            widget.setSingleStep(0.1 if key.startswith("padding") else 0.5)
            form.addRow(label, widget)
            self.controls[key] = widget
            if key == "width_mm":
                self.add_column_width_controls(form)
        self.alignments = QtWidgets.QLineEdit()
        self.alignments.setPlaceholderText("如：左,小数点,中；留空沿用源码单元格对齐")
        form.addRow("各列对齐", self.alignments)
        self.fixed = QtWidgets.QCheckBox("固定行高（放不下时报告溢出）")
        self.repeat = QtWidgets.QCheckBox("跨页重复表头（需有表头行）")
        form.addRow(self.fixed)
        form.addRow(self.repeat)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b43d3d")
        layout.addWidget(self.error)
        note = QtWidgets.QLabel(
            "确定后应用于所选范围；切换范围会重新载入该范围的设置。修改默认值不影响已有独立设置的表格。修改尺寸会重新分页，格内内容过长不会自动缩小字形。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.scope.currentIndexChanged.connect(self.load_style)
        self.inherit.toggled.connect(self.update_controls)
        self.total_mode.currentIndexChanged.connect(self.update_controls)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.load_style()

    def add_column_width_controls(self, form):
        self.mode = QtWidgets.QComboBox()
        for key, label in (
            ("content", "按内容分配"),
            ("equal", "等宽"),
            ("ratio", "按比例"),
            ("fixed", "固定列宽"),
        ):
            self.mode.addItem(label, key)
        self.mode.setToolTip("在表格总宽内决定各列宽度。固定列宽需要手动指定总宽。")
        form.addRow("列宽方式", self.mode)
        self.sizes = QtWidgets.QLineEdit()
        self.sizes.setPlaceholderText("逗号分隔；固定列宽单位 mm，合计须等于表宽")
        form.addRow("列宽或比例", self.sizes)

    def load_style(self):
        target = self.scope.currentData()
        self.columns = self.column_counts.get(target)
        self.original = (
            self.flow.table_for(target) if target else self.flow.table
        )
        self.scope_info.setText("正在编辑文档默认设置" if not target else
                                "当前表格：独立设置" if target in dict(self.flow.table_overrides) else
                                "当前表格：沿用文档默认，修改并确定后建立独立设置")
        self.inherit.setEnabled(bool(self.scope.currentData()))
        self.inherit.setChecked(False)
        self.initial = {}
        for key, widget in self.controls.items():
            value = getattr(self.original, key)
            with QtCore.QSignalBlocker(widget):
                widget.setMinimum(min(widget.minimum(), value))
                widget.setValue(value)
            self.initial[key] = widget.value()
        with QtCore.QSignalBlocker(self.total_mode), QtCore.QSignalBlocker(self.mode):
            self.total_mode.setCurrentIndex(self.total_mode.findData(self.original.total_width_mode))
            self.mode.setCurrentIndex(self.mode.findData(self.original.width_mode))
        self.sizes.setText(", ".join(str(v) for v in self.original.columns))
        self.alignments.setText(", ".join(LABELS[v] for v in self.original.column_alignments))
        self.fixed.setChecked(self.original.fixed_row_height)
        self.repeat.setChecked(self.original.repeat_header)
        self.update_controls()

    def update_controls(self):
        enabled = not (self.scope.currentData() and self.inherit.isChecked())
        manual_width = self.total_mode.currentData() == "fixed"
        fixed_item = self.mode.findData("fixed")
        if not manual_width and self.mode.currentIndex() == fixed_item:
            with QtCore.QSignalBlocker(self.mode):
                self.mode.setCurrentIndex(self.mode.findData("content"))
        self.mode.model().item(fixed_item).setEnabled(manual_width)
        for control in (*self.controls.values(), self.total_mode, self.mode, self.alignments, self.fixed, self.repeat):
            control.setEnabled(enabled)
        self.controls["width_mm"].setEnabled(enabled and manual_width)
        self.sizes.setEnabled(enabled and self.mode.currentData() in {"ratio", "fixed"})

    def configuration(self):
        target = self.scope.currentData()
        if target and self.inherit.isChecked():
            return target, None
        changes = {k: c.value() for k, c in self.controls.items() if c.value() != self.initial[k]}
        mode = self.mode.currentData()
        sizes = (
            tuple(float(v.strip()) for v in self.sizes.text().replace("，", ",").split(",") if v.strip())
            if mode in {"ratio", "fixed"} else ()
        )
        lookup = {**{v: k for k, v in LABELS.items()}, **{k: k for k in LABELS}}
        try:
            alignments = tuple(
                lookup[v.strip()]
                for v in self.alignments.text().replace("，", ",").split(",")
                if v.strip()
            )
        except KeyError as error:
            raise ValueError("列对齐请填写：沿用、左、中、右、小数点") from error
        style = replace(
            self.original,
            **changes,
            columns=sizes,
            column_alignments=alignments,
            width_mode=mode,
            total_width_mode=self.total_mode.currentData(),
            fixed_row_height=self.fixed.isChecked(),
            repeat_header=self.repeat.isChecked(),
        )
        if target and any(
            values and len(values) != self.columns for values in (style.columns, alignments)
        ):
            raise ValueError(f"当前表格需要 {self.columns} 项列设置")
        if mode == "fixed" and abs(sum(style.columns) - style.width_mm) > 1e-7:
            raise ValueError("固定列宽之和必须等于表格总宽")
        return target, style

    def accept(self):
        try:
            self.configuration()
        except ValueError as error:
            self.error.setText(str(error))
            return
        super().accept()
