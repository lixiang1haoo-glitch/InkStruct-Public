"""Stage image resources and physical dimensions before applying to the document."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..document.images import import_image_file
from ..document.line_svg import LineSvgResource


class ImageSettingsDialog(QtWidgets.QDialog):
    def __init__(self, document, flow, parent=None):
        super().__init__(parent)
        self.flow = flow
        self.nodes = tuple(n for root in document.nodes for n in root.walk() if n.kind == "image")
        self.current = None
        self.loaded = False
        self.setWindowTitle("图片与图题")
        self.setObjectName("image_settings_dialog")
        self.setStyleSheet('QCheckBox::indicator:unchecked {background: transparent; border: 1px solid #8995a5; border-radius: 2px;}')
        self.resize(540, 340)
        form = QtWidgets.QFormLayout(self)
        self.picker = QtWidgets.QComboBox(self)
        self.picker.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.picker.setMinimumContentsLength(24)
        self.picker.addItem("文档默认（已有独立设置的图片不变）", None)
        for index, node in enumerate(self.nodes, 1):
            self.picker.addItem(
                f"图片 {index} · " + dict(node.attributes).get("src", "") + " · 个性化设置", node.node_id
            )
        form.addRow("应用范围", self.picker)
        self.inherit = QtWidgets.QCheckBox("当前图片恢复沿用文档默认", self)
        form.addRow(self.inherit)
        self.scope_info = QtWidgets.QLabel(self)
        self.scope_info.setWordWrap(True)
        form.addRow(self.scope_info)
        self.info = QtWidgets.QLabel(self)
        self.info.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.info.setWordWrap(True)
        form.addRow(self.info)
        self.import_button = QtWidgets.QPushButton("导入 PNG/JPEG 或单线 SVG…", self)
        self.import_button.clicked.connect(self.choose_file)
        form.addRow(self.import_button)
        self.controls = {}
        self.initial = {}
        self.force_height = False
        self.dimension_mode = QtWidgets.QComboBox(self)
        self.dimension_mode.addItem("按高度，宽度按比例", "height")
        self.dimension_mode.addItem("按宽度，高度按比例", "width")
        self.dimension_mode.setAccessibleName("图片尺寸依据")
        form.addRow("尺寸依据", self.dimension_mode)
        self.convert_height = QtWidgets.QPushButton("将本文旧版图片默认改为按高度 60 mm", self)
        self.convert_height.clicked.connect(self.use_height_default)
        form.addRow(self.convert_height)
        for name, label in (
            ("height_mm", "高度（宽度按原图比例计算）"),
            ("width_mm", "宽度"),
            ("max_height_mm", "最大高度（0 表示不限）"),
            ("caption_gap_mm", "图片与图题间距"),
            ("svg_tolerance_mm", "SVG 曲线容差（最终毫米）"),
        ):
            c = QtWidgets.QDoubleSpinBox(self)
            c.setDecimals(4)
            c.setRange(
                (0.001 if name == "svg_tolerance_mm" else 0.0001 if name in {"width_mm", "height_mm"} else 0),
                (1 if name == "svg_tolerance_mm" else 100 if name == "caption_gap_mm" else 2000),
            )
            c.setSuffix(" mm")
            c.setAccessibleName(label)
            self.controls[name] = c
            form.addRow(label, c)
        self.alignment = QtWidgets.QComboBox(self)
        for text, value in (("左对齐", "left"), ("居中", "center"), ("右对齐", "right")):
            self.alignment.addItem(text, value)
        form.addRow("图片对齐", self.alignment)
        note = QtWidgets.QLabel(
            "独占一段的图片保持长宽比，与图题共同分页；方括号内的替代文字作为图题排版。普通位图仅供参考页面，不能导出写字机 SVG。单线 SVG 经校验后可书写，使用文档笔宽；容差控制曲线离散。没有网络下载或自动描图。",
            self,
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.error = QtWidgets.QLabel(self)
        self.error.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.picker.currentIndexChanged.connect(self.selection_changed)
        self.dimension_mode.currentIndexChanged.connect(self.update_controls)
        self.controls['height_mm'].valueChanged.connect(self.height_edited)
        self.inherit.toggled.connect(self.update_controls)
        self.selection_changed()

    def height_edited(self, *_):
        if self.loaded and self.current is None:
            self.force_height = True

    def use_height_default(self):
        self.force_height = True
        self.dimension_mode.setCurrentIndex(0)
        self.controls['height_mm'].setValue(60)
        self.convert_height.hide()
        self.update_info()

    def height_mode(self):
        return self.current is None or self.dimension_mode.currentData() == 'height'

    def store_current(self):
        if not self.loaded:
            return
        target = self.current.node_id if self.current else None
        if target and self.inherit.isChecked():
            overrides = dict(self.flow.image_overrides)
            overrides.pop(target, None)
            self.flow = replace(self.flow, image_overrides=tuple(overrides.items()))
            return
        changes = {
            key: (None if key == "max_height_mm" and c.value() == 0 else c.value())
            for key, c in self.controls.items()
            if c.value() != self.initial[key]
        }
        if self.height_mode():
            changes.pop('width_mm', None)
            changes.pop('max_height_mm', None)
            # Viewing a legacy document default is a no-op. Conversion is an
            # explicit action, never a silent change to saved image geometry.
            if self.current is not None or self.original.height_mm is not None or self.force_height:
                changes['height_mm'] = (self.original.height_mm
                    if self.controls['height_mm'].value() == self.initial['height_mm']
                    and self.original.height_mm is not None else self.controls['height_mm'].value())
                changes['max_height_mm'] = None
        else:
            changes['height_mm'] = None
        style = replace(
            self.original, align=self.alignment.currentData(), **changes
        )
        if style == self.original:
            return
        if target:
            overrides = dict(self.flow.image_overrides)
            overrides[target] = style
            self.flow = replace(self.flow, image_overrides=tuple(overrides.items()))
        else:
            self.flow = replace(self.flow, image=style)

    def selection_changed(self):
        self.store_current()
        self.loaded = False
        self.force_height = False
        self.current = next((n for n in self.nodes if n.node_id == self.picker.currentData()), None)
        self.import_button.setEnabled(self.current is not None)
        self.inherit.setEnabled(self.current is not None)
        self.inherit.setChecked(False)
        style = self.flow.image_for(self.current.node_id) if self.current else self.flow.image
        self.original = style
        self.dimension_mode.setCurrentIndex(self.dimension_mode.findData(
            'height' if style.height_mm is not None else 'width'))
        for key, c in self.controls.items():
            if key != 'height_mm':
                c.setMinimum(min(c.minimum(), getattr(style, key) or 0))
            c.setValue((getattr(style, key) or 60) if key == 'height_mm' else getattr(style, key) or 0)
            self.initial[key] = c.value()
        self.alignment.setCurrentIndex(self.alignment.findData(style.align))
        self.scope_info.setText("正在编辑文档默认设置" if not self.current else
                                "当前图片：独立设置" if self.current.node_id in dict(self.flow.image_overrides) else
                                "当前图片：沿用文档默认，修改并确定后建立独立设置")
        self.loaded = True
        self.update_controls()
        self.update_info()

    def update_controls(self):
        if not self.loaded:
            return
        enabled = not (self.current and self.inherit.isChecked())
        for control in (*self.controls.values(), self.alignment, self.dimension_mode):
            control.setEnabled(enabled)
        form = self.layout()
        for control, visible in (
            (self.dimension_mode, self.current is not None),
            (self.controls['height_mm'], self.height_mode()),
            (self.controls['width_mm'], self.current is not None and not self.height_mode()),
            (self.controls['max_height_mm'], self.current is not None and not self.height_mode()),
        ):
            control.setVisible(visible)
            field_label = form.labelForField(control)
            if field_label:
                field_label.setVisible(visible)
        self.convert_height.setVisible(self.current is None and self.original.height_mm is None
                                       and not self.force_height)

    def update_info(self):
        source = dict(self.current.attributes).get("src", "") if self.current else ""
        resource = next((r for r in self.flow.images if r.source == source), None)
        self.info.setText(
            f"单线 SVG · 原尺寸 {resource.width_mm:g} × {resource.height_mm:g} mm · SHA-256 {resource.original_sha256}"
            if isinstance(resource, LineSvgResource)
            else f"已嵌入 {resource.width_px} × {resource.height_px} px · 原文件 SHA-256 {resource.original_sha256}"
            if resource
            else "尚未嵌入图片文件"
            if self.current
            else (f"本文旧版默认保留图宽 {self.original.width_mm:g} mm；可明确改为按高度。"
                  if self.original.height_mm is None and not self.force_height else
                  "默认按高度设置，宽度按原图比例计算。用于沿用默认及后续新增图片，不覆盖独立设置。")
        )

    def import_file(self, path):
        if self.current is None:
            return
        source = dict(self.current.attributes).get("src", "")
        resource = import_image_file(Path(path), source)
        self.flow = replace(
            self.flow, images=tuple(r for r in self.flow.images if r.source != source) + (resource,)
        )
        self.update_info()

    def choose_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "导入图片", "", "图片或单线图 (*.png *.jpg *.jpeg *.svg)"
        )
        if path:
            try:
                self.import_file(path)
                self.error.clear()
            except (ValueError, OSError) as error:
                self.error.setText(str(error))

    def configuration(self):
        self.store_current()
        return self.flow

    def accept(self):
        try:
            self.configuration()
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()
