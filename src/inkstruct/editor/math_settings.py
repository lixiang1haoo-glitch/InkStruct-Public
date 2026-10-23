"""Category-based mathematical settings with live centreline geometry and guides."""

from dataclasses import replace
from math import ceil

from PySide6 import QtCore, QtGui, QtWidgets

from ..assets.resolver import AssetResolver
from ..document.editing import SourceSession
from ..document.markdown import parse_markdown
from ..math.handwritten import measure_math
from ..math.style import MathStyle
from .math_diagram import StructureDiagram, info_button

GROUPS = (
    (
        "字号与字形",
        "12.50",
        (("em_mm", "公式字号"),),
        "字号独立于正文与表格。字形使用当前项目资源；普通字体不作为缺失手写字形的替代。",
    ),
    (
        "间距与数学轴",
        "12+3=15",
        (
            ("axis_em", "数学轴高度"),
            ("binary_gap_em", "二元运算符间距"),
            ("relation_gap_em", "关系符间距"),
            ("operator_gap_em", "函数与标点间距"),
        ),
        "虚线表示基线和数学轴。运算符根据采集参考线对齐；参数百分比相对于当前层公式字号。",
    ),
    (
        "上标与下标",
        "12_3^4",
        (
            ("script_scale", "上下标字号"),
            ("superscript_raise_em", "上标最小上移"),
            ("subscript_drop_em", "下标最小下移"),
        ),
        "普通上下标按层级缩小。程序根据实际笔迹边界和笔宽自动留白，并在必要时扩大位移以避免碰撞；水平留白独立于上移、下移设置。大运算符的上下限字号在对应分类单独设置。",
    ),
    (
        "分式",
        r"\frac{12}{3}",
        (("fraction_scale", "分子分母字号"), ("fraction_clearance_em", "分数线净间距")),
        r"连分式逐层缩小；\dfrac 保持当前层字号。净间距受笔宽下限约束，不能将两层压在一起。",
    ),
    (
        "根式",
        r"\sqrt[3]{12}",
        (("radical_clearance_em", "根式内部净间距"),),
        "采集根号保留钩部写法，横线随内容延长；几何模式使用折线。根指数字号沿用上下标比例。",
    ),
    (
        "积分与大运算符",
        r"\sum_{1}^{3}12",
        (
            ("large_operator_scale", "运算符字号"),
            ("limits_clearance_em", "上下限净间距"),
            ("limits_scale", "上下限字号"),
        ),
        r"运算符和上下限的字号比例独立设置，均相对于当前层公式字号。上下限比例同时作用于侧置与堆叠上下限；内部嵌套上下标仍使用普通上下标比例。上下限位置由独立/行内模式与 \limits、\nolimits 决定。",
    ),
    (
        "矩阵与向量",
        r"\begin{bmatrix}1&2\\3&4\end{bmatrix}",
        (
            ("matrix_row_gap_em", "矩阵行间距"),
            ("matrix_col_gap_em", "矩阵列间距"),
            ("small_matrix_scale", "行内小矩阵字号"),
            ("array_rule_clearance_em", "数组框线净间距"),
        ),
        "矩阵列按最宽内容分配；array 可指定各列对齐及分隔线。小矩阵按比例缩小；向量箭头使用修饰与向量设置。",
    ),
    (
        "括号与定界符",
        r"\left(\frac{12}{3}\right)",
        (("delimiter_clearance_em", "括号与内容净间距"), ("delimiter_width_em", "括号构件宽度")),
        r"\left / \right 及矩阵括号可缩放录制字形。高度由内容适配，宽度有三倍笔宽下限；几何模式使用折线。",
    ),
    (
        "多行对齐",
        r"\begin{aligned}12&=3+9\\123&=120+3\end{aligned}",
        (("alignment_row_gap_em", "对齐行净间距"), ("alignment_pair_gap_em", "等式组间距")),
        "& 指定对齐点，双反斜杠显式换行。多行公式整体分页，超宽或超高会诊断；使用非星号 align/gather 可逐行编号。",
    ),
    (
        "公式编号",
        r"12.50\tag{1}",
        (("tag_scale", "编号字号"), ("tag_gap_em", "公式与编号净间距")),
        "equation、align、gather 自动编号；tag 指定编号，notag 取消该行编号。编号位于有效公式区域右侧。",
    ),
    (
        "修饰与向量",
        r"\vec{12}\quad\widehat{34}\quad\ddot{5}",
        (("accent_clearance_em", "标记与内容净间距"), ("accent_height_em", "标记构件高度")),
        "箭头、横线、帽号、波浪和点号使用独立折线构件。原字形保持不变，尺寸受笔宽下限约束；点号使用短线绘制。",
    ),
)


EXAMPLES = {
    1: (("函数间距", r"\sin 12"),),
    3: (("连分式", r"\frac{12}{\frac{3}{4}}"), ("行间分式", r"\dfrac{12}{3}")),
    5: (("积分", r"\int_{1}^{3}12"), ("堆叠上下限", r"\int\limits_{1}^{3}12")),
    6: (
        ("行内小矩阵", r"\begin{smallmatrix}1&2\\3&4\end{smallmatrix}"),
        ("带框线数组", r"\begin{array}{c|c}1&2\\\hline 3&4\end{array}"),
    ),
    8: (("两组等式对齐", r"\begin{aligned}1&=2&3&=4\\5&=6&7&=8\end{aligned}"),),
}


class DimensionSpinBox(QtWidgets.QDoubleSpinBox):
    """Keep editing precision without filling every field with trailing zeros."""

    def textFromValue(self, value):
        text = super().textFromValue(value)
        separator = self.locale().decimalPoint()
        return text.rstrip("0").rstrip(separator) if separator in text else text


class MathPreview(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.box = None
        self.pen_mm = 0.3
        self.setMinimumSize(380, 140)
        self.show_guides = True
        self.zoom_percent = 200
        self.empty_message = "输入受支持的公式以查看几何预览"

    @property
    def pixels_per_mm(self):
        return 96 / 25.4 * self.zoom_percent / 100

    def update_geometry(self):
        if self.box is None:
            self.setMinimumSize(380, 140)
        else:
            height = self.box.descent + max(self.box.ascent, self.box.axis)
            self.setMinimumSize(
                max(380, ceil(self.box.width * self.pixels_per_mm + 110)),
                max(140, ceil(height * self.pixels_per_mm + 70)),
            )
        self.updateGeometry()
        self.update()

    def set_zoom(self, percent):
        self.zoom_percent = percent
        self.update_geometry()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#ffffff"))
        if self.box is None:
            p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.empty_message)
            return
        box = self.box
        top = -max(box.ascent, box.axis)
        height = max(1, box.descent - top)
        zoom = self.pixels_per_mm
        ox = (self.width() - box.width * zoom) / 2
        oy = (self.height() - height * zoom) / 2 - top * zoom

        def at(x, y):
            return QtCore.QPointF(ox + x * zoom, oy + y * zoom)

        if self.show_guides:
            for y, color in ((0, "#64748b"), (-box.axis, "#2563eb")):
                p.setPen(QtGui.QPen(QtGui.QColor(color), 1, QtCore.Qt.PenStyle.DashLine))
                p.drawLine(at(-2, y), at(box.width + 2, y))
            p.setPen(QtGui.QColor("#475569"))
            p.drawText(12, 23, "虚线：灰色基线 · 蓝色数学轴")
        pen = QtGui.QPen(
            QtGui.QColor("#111827"),
            max(0.2, self.pen_mm * zoom),
            QtCore.Qt.PenStyle.SolidLine,
            QtCore.Qt.PenCapStyle.RoundCap,
            QtCore.Qt.PenJoinStyle.RoundJoin,
        )

        def stroke(points):
            p.setPen(pen)
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            polygon = QtGui.QPolygonF([at(x, y) for x, y in points])
            if len(points) == 1:
                p.drawPoint(polygon[0])
            else:
                p.drawPolyline(polygon)

        for g in box.glyphs:
            if g.glyph:
                for points in g.glyph.strokes:
                    stroke(
                        tuple(
                            (
                                g.x_mm + g.origin_offset_mm + x * g.em_mm,
                                g.baseline_mm + (y - g.glyph.metrics.baseline) * g.em_mm,
                            )
                            for x, y in points
                        )
                    )
            elif g.status != "space":
                p.setPen(QtGui.QColor("#b91c1c"))
                p.setBrush(QtGui.QColor("#fff1f2"))
                rect = QtCore.QRectF(
                    at(g.x_mm, g.baseline_mm - g.ascent_mm),
                    at(g.x_mm + g.advance_mm, g.baseline_mm + g.descent_mm),
                )
                p.drawRect(rect)
                p.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, g.occurrence.text)
        for rule in box.rules:
            stroke(rule.points)
        p.setPen(QtGui.QPen(QtGui.QColor("#2563eb"), 1))

        def arrow(a, b):
            p.drawLine(a, b)
            if a.y() == b.y():
                for x, sign in ((a.x(), 1), (b.x(), -1)):
                    p.drawLine(QtCore.QPointF(x, a.y()), QtCore.QPointF(x + sign * 5, a.y() - 3))
                    p.drawLine(QtCore.QPointF(x, a.y()), QtCore.QPointF(x + sign * 5, a.y() + 3))
            else:
                for y, sign in ((a.y(), 1), (b.y(), -1)):
                    p.drawLine(QtCore.QPointF(a.x(), y), QtCore.QPointF(a.x() - 3, y + sign * 5))
                    p.drawLine(QtCore.QPointF(a.x(), y), QtCore.QPointF(a.x() + 3, y + sign * 5))

        arrow(at(0, box.descent + 10 / zoom), at(box.width, box.descent + 10 / zoom))
        arrow(at(-10 / zoom, -box.ascent), at(-10 / zoom, box.descent))
        p.drawText(
            12,
            self.height() - 14,
            f"宽 {box.width:.2f} mm   高 {box.ascent + box.descent:.2f} mm   数学轴 {box.axis:.2f} mm",
        )


class MathCategoryDelegate(QtWidgets.QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # Native Windows styles can omit stylesheet padding from the row hint.
        size.setHeight(max(size.height(), option.fontMetrics.height() + 20))
        return size


class MathSettingsDialog(QtWidgets.QDialog):
    def __init__(self, style, parent=None, *, resolver=None, stroke_width=0.3):
        super().__init__(parent)
        self.original = style
        resolver = resolver or AssetResolver(builtin_numbers=True)
        self.preview_resolver = AssetResolver(
            embedded=tuple(g for pool in resolver.pools.values() for g in pool), seed=resolver.seed
        )
        self.pen_mm = stroke_width
        self.preview_session = None
        self.setWindowTitle("公式字体与样式")
        self.setObjectName("math_settings_dialog")
        self.resize(980, 740)
        self.setMinimumSize(880, 620)
        self.setStyleSheet("""
            QWidget#math_content { background: #f5f7fa; }
            QDialog#math_settings_dialog { background: #f5f7fa; }
            QDialog#math_settings_dialog QLabel, QDialog#math_settings_dialog QCheckBox { color: #334155; }
            QListWidget { background: #edf1f6; border: none; border-radius: 8px; padding: 6px; }
            QListWidget::item { padding: 10px 8px; border-radius: 5px; color: #334155; }
            QListWidget::item:selected { background: #dbeafe; color: #155dad; font-weight: bold; }
            QFrame#dimension_card { background: transparent; border: none; }
            QFrame#dimension_card[active="true"] QDoubleSpinBox { border: 1px solid #267bd1; }
            QDoubleSpinBox { min-height: 20px; background: white; color: #1e293b; border: 1px solid #b7c4d2; border-radius: 2px; padding: 1px 3px; }
            QToolButton { padding: 3px; }
            QScrollArea { border: none; background: transparent; }
            QLabel#section_title { font-size: 20px; font-weight: bold; color: #1e293b; }
            QLabel#muted { color: #64748b; }
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        heading = QtWidgets.QLabel("公式设置", self)
        heading.setObjectName("section_title")
        heading_row = QtWidgets.QHBoxLayout()
        heading_row.addWidget(heading)
        heading_row.addWidget(
            info_button(
                self,
                "设置应用于当前文档的全部公式；点击“应用设置”后生效，取消不改变项目。",
                "公式设置说明",
            )
        )
        heading_row.addStretch()
        layout.addLayout(heading_row)
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        layout.addLayout(body, 1)
        self.categories = QtWidgets.QListWidget(self)
        self.categories.setItemDelegate(MathCategoryDelegate(self.categories))
        self.categories.setUniformItemSizes(True)
        self.categories.setFixedWidth(max(166, max(
            self.categories.fontMetrics().horizontalAdvance(group[0]) for group in GROUPS
        ) + 36))
        self.categories.setAccessibleName("公式结构分类")
        body.addWidget(self.categories)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        body.addWidget(scroll, 1)
        content = QtWidgets.QWidget()
        content.setObjectName("math_content")
        scroll.setWidget(content)
        centre = QtWidgets.QVBoxLayout(content)
        centre.setContentsMargins(0, 0, 8, 0)
        centre.setSpacing(6)
        self.category_title = QtWidgets.QLabel(content)
        self.category_title.setObjectName("section_title")
        category_heading = QtWidgets.QHBoxLayout()
        category_heading.addWidget(self.category_title)
        self.explanation = info_button(content, name="当前结构说明")
        category_heading.addWidget(self.explanation)
        category_heading.addStretch()
        centre.addLayout(category_heading)
        self.panels = QtWidgets.QStackedWidget(content)
        centre.addWidget(self.panels)
        self.controls, self.initial, self.factors = {}, {}, {}
        self.sources = {}
        self.diagrams = []
        for index, (title, sample, fields, explanation) in enumerate(GROUPS):
            self.categories.addItem(title)
            page = QtWidgets.QWidget(self.panels)
            page_layout = QtWidgets.QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(7)
            diagram = StructureDiagram(index, fields, page)
            self.diagrams.append(diagram)
            page_layout.addWidget(diagram)
            options = QtWidgets.QHBoxLayout()
            page_layout.addLayout(options)
            source_key = {
                "分式": "fraction_source",
                "根式": "radical_source",
                "括号与定界符": "delimiter_source",
            }.get(title)
            if source_key:
                choice = QtWidgets.QComboBox(page)
                choice.setObjectName(source_key)
                choice.addItem("几何构件", "geometric")
                choice.addItem("字体减号 −（横向拉伸，默认）" if source_key == "fraction_source" else "录制字形（缩放适配）", "sample")
                choice.setCurrentIndex(choice.findData(getattr(style, source_key)))
                choice.setToolTip(
                    "分数线使用减号 −，根号使用 √，括号使用对应字符。缺样本时显示诊断。"
                )
                self.sources[source_key] = choice
                options.addWidget(QtWidgets.QLabel("构件来源", page))
                options.addWidget(choice)
            for key, label in fields:
                widget = DimensionSpinBox(diagram)
                widget.setObjectName(key)
                widget.setAccessibleName(label)
                widget.setDecimals(4)
                widget.setKeyboardTracking(True)
                factor = 1 if key == "em_mm" else 100
                low, high = (
                    (0.0001, 2000)
                    if key == "em_mm"
                    else (50, 300)
                    if key == "large_operator_scale"
                    else (50, 100)
                    if key
                    in {
                        "script_scale",
                        "limits_scale",
                        "fraction_scale",
                        "tag_scale",
                        "small_matrix_scale",
                    }
                    else (0, 200)
                )
                widget.setRange(min(low, getattr(style, key) * factor), high)
                widget.setSuffix(" mm" if key == "em_mm" else " %")
                widget.setSingleStep(0.5 if key == "em_mm" else 1)
                widget.setValue(getattr(style, key) * factor)
                widget.setToolTip(
                    label + "：" + ("毫米" if key == "em_mm" else "相对于当前层公式字号的百分比")
                    + ("。紧凑策略按样本比例和括号类型计算宽度，此值控制基础宽度上限，仍受笔宽保护；旧版为固定构件宽度。"
                       if key == "delimiter_width_em" else "")
                )
                self.controls[key] = widget
                self.initial[key] = widget.value()
                self.factors[key] = factor
                reset = QtWidgets.QToolButton(diagram)
                reset.setText("↺")
                reset.setToolTip("恢复“" + label + "”默认值")
                reset.setAccessibleName("恢复" + label + "默认值")
                reset.clicked.connect(lambda checked=False, key=key: self.reset_parameter(key))
                diagram.add_control(key, label, widget, reset)
            if title == "字号与字形":
                self.points = DimensionSpinBox(page)
                self.points.setDecimals(4)
                self.points.setKeyboardTracking(True)
                self.points.setRange(0.0001, 2000 * 72 / 25.4)
                self.points.setSuffix(" pt")
                self.points.setValue(style.em_mm * 72 / 25.4)
                self.points.setAccessibleName("等效字号")
                options.addWidget(QtWidgets.QLabel("等效字号", page))
                options.addWidget(self.points)
                self.points.valueChanged.connect(self.points_changed)
                self.controls["em_mm"].valueChanged.connect(self.mm_changed)
                self.alignment = QtWidgets.QComboBox(page)
                self.alignment.addItem("居中", "center")
                self.alignment.addItem("左对齐", "left")
                self.alignment.setCurrentIndex(self.alignment.findData(style.display_align))
                options.addSpacing(16)
                options.addWidget(QtWidgets.QLabel("独立公式对齐", page))
                options.addWidget(self.alignment)
                policy_row = QtWidgets.QHBoxLayout()
                self.spacing_policy = QtWidgets.QComboBox(page)
                self.spacing_policy.setAccessibleName("公式字距")
                self.spacing_policy.addItem("按笔迹紧凑排列（推荐）", "handwriting")
                self.spacing_policy.addItem("保留采集留白与原结构尺寸（旧版）", "capture")
                self.spacing_policy.setCurrentIndex(self.spacing_policy.findData(style.spacing_policy))
                self.spacing_policy.setToolTip("消除公式采集格留白，按实际笔迹布置结构；保留字号、数学轴、显式空格及冻结选样。旧文档仅在明确应用后改变。")
                policy_row.addWidget(QtWidgets.QLabel("公式字距", page))
                policy_row.addWidget(self.spacing_policy)
                policy_row.addStretch()
                page_layout.addLayout(policy_row)
            options.addStretch()
            self.panels.addWidget(page)
        preview_heading = QtWidgets.QHBoxLayout()
        preview_heading.addWidget(QtWidgets.QLabel("实际字形预览", content))
        preview_heading.addWidget(
            info_button(
                content,
                f"当前项目可用字符：{len(resolver.pools)} 种。上方仅为固定比例结构示意；此处使用实际可用笔迹。"
                "缺字显示红框，不使用印刷字形代替。示例不会插入正文；尺寸以实际预览为准。",
                "实际字形预览说明",
            )
        )
        preview_heading.addStretch()
        self.preview_zoom = QtWidgets.QComboBox(content)
        self.preview_zoom.setAccessibleName("预览倍率")
        for percent in (50, 100, 150, 200, 300, 400):
            self.preview_zoom.addItem(f"{percent}%", percent)
        self.preview_zoom.setCurrentIndex(self.preview_zoom.findData(200))
        self.preview_zoom.setToolTip(
            "固定预览倍率，修改参数不会自动缩放。超出范围可滚动查看或调低倍率；屏幕尺寸不作为纸面校准。"
        )
        preview_heading.addWidget(QtWidgets.QLabel("倍率", content))
        preview_heading.addWidget(self.preview_zoom)
        self.guides = QtWidgets.QCheckBox("显示辅助线", content)
        self.guides.toggled.connect(self.toggle_guides)
        preview_heading.addWidget(self.guides)
        centre.addLayout(preview_heading)
        self.preview = MathPreview(content)
        self.guides.setChecked(True)
        self.preview_scroll = QtWidgets.QScrollArea(content)
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFixedHeight(170)
        self.preview_scroll.setWidget(self.preview)
        centre.addWidget(self.preview_scroll)
        self.preview_zoom.currentIndexChanged.connect(
            lambda: self.preview.set_zoom(self.preview_zoom.currentData())
        )
        source_row = QtWidgets.QHBoxLayout()
        self.example_choice = QtWidgets.QComboBox(content)
        self.example_choice.setAccessibleName("试排示例")
        self.example_choice.setMinimumWidth(110)
        self.example_choice.activated.connect(self.choose_example)
        source_row.addWidget(self.example_choice)
        self.formula = QtWidgets.QLineEdit(content)
        self.formula.setAccessibleName("自定义试排公式")
        self.formula.setPlaceholderText("输入 LaTeX 公式内容，无需定界符")
        source_row.addWidget(self.formula, 1)
        example_reset = QtWidgets.QToolButton(content)
        example_reset.setText("重置示例")
        example_reset.clicked.connect(
            lambda: self.formula.setText(GROUPS[self.categories.currentRow()][1])
        )
        source_row.addWidget(example_reset)
        self.display = QtWidgets.QCheckBox("独立公式", content)
        self.display.setChecked(True)
        source_row.addWidget(self.display)
        centre.addLayout(source_row)
        self.preview_status = QtWidgets.QLabel(content)
        self.preview_status.setWordWrap(True)
        self.preview_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        centre.addWidget(self.preview_status)
        centre.addStretch()
        self._examples = [group[1] for group in GROUPS]
        self._last_category = None
        self.error = QtWidgets.QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        footer = QtWidgets.QHBoxLayout()
        layout.addLayout(footer)
        restore = QtWidgets.QPushButton("当前分类恢复默认", self)
        restore.clicked.connect(self.reset_category)
        footer.addWidget(restore)
        footer.addStretch()
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("应用设置")
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh_preview)
        for c in self.controls.values():
            c.valueChanged.connect(self.schedule_preview)
            c.lineEdit().textEdited.connect(self.schedule_preview)
            c.editingFinished.connect(self.schedule_preview)
        self.points.lineEdit().textEdited.connect(self.schedule_preview)
        self.points.editingFinished.connect(self.schedule_preview)
        for c in self.sources.values():
            c.currentIndexChanged.connect(self.schedule_preview)
        self.spacing_policy.currentIndexChanged.connect(self.schedule_preview)
        self.formula.textChanged.connect(self.schedule_preview)
        self.display.toggled.connect(self.schedule_preview)
        self.categories.currentRowChanged.connect(self.category_changed)
        self.categories.setCurrentRow(0)
        self.refresh_preview()

    def choose_example(self, index):
        self.formula.setText(self.example_choice.itemData(index))

    def toggle_guides(self, checked):
        self.preview.show_guides = checked
        self.preview.update()

    def reset_parameter(self, key):
        self.controls[key].setValue(getattr(MathStyle.handwriting(), key) * self.factors[key])

    def mm_changed(self, value):
        with QtCore.QSignalBlocker(self.points):
            self.points.setValue(value * 72 / 25.4)

    def points_changed(self, value):
        self.controls["em_mm"].setValue(value * 25.4 / 72)

    def category_changed(self, index):
        if self._last_category is not None:
            self._examples[self._last_category] = self.formula.text()
        self._last_category = index
        self.panels.setCurrentIndex(index)
        self.category_title.setText(GROUPS[index][0])
        self.explanation.setToolTip(
            GROUPS[index][3]
            + "\n结构图为固定比例示意，数值变化请查看下方实际字形预览。\n100% = 当前层公式字号；单项尺寸及毫米估算可悬停其旁的 i 查看。"
        )
        self.example_choice.clear()
        self.example_choice.addItem("默认示例", GROUPS[index][1])
        for title, source in EXAMPLES.get(index, ()):
            self.example_choice.addItem(title, source)
        self.formula.setText(self._examples[index])
        self.sync_example_choice()
        self.schedule_preview()

    def reset_category(self):
        defaults = MathStyle.handwriting()
        if self.categories.currentRow() == 0:
            self.alignment.setCurrentIndex(self.alignment.findData(defaults.display_align))
            self.spacing_policy.setCurrentIndex(self.spacing_policy.findData(defaults.spacing_policy))
        for key, label in GROUPS[self.categories.currentRow()][2]:
            self.controls[key].setValue(getattr(defaults, key) * self.factors[key])
        key = {3: "fraction_source", 4: "radical_source", 7: "delimiter_source"}.get(
            self.categories.currentRow()
        )
        if key:
            self.sources[key].setCurrentIndex(self.sources[key].findData(getattr(defaults, key)))

    def sync_example_choice(self):
        index = self.example_choice.findData(self.formula.text())
        self.example_choice.setCurrentIndex(index)
        self.example_choice.setPlaceholderText("自定义公式")

    def schedule_preview(self, *args):
        self.sync_example_choice()
        self.timer.start()

    def configuration(self):
        for widget in (*self.controls.values(), self.points):
            if not widget.hasAcceptableInput():
                raise ValueError(
                    f"{widget.accessibleName()}需在 {widget.minimum():g}–{widget.maximum():g}"
                    f"{widget.suffix().strip()} 内；当前输入尚未生效。"
                )
        changes = {
            key: c.value() / self.factors[key]
            for key, c in self.controls.items()
            if c.value() != self.initial[key]
        }
        changes.update({key: widget.currentData() for key, widget in self.sources.items()})
        return replace(self.original, **changes, display_align=self.alignment.currentData(),
                       spacing_policy=self.spacing_policy.currentData())

    def refresh_preview(self):
        self.timer.stop()
        try:
            style = self.configuration()
            for diagram in self.diagrams:
                diagram.update_values(style)
            source = (
                "$$\n" + self.formula.text() + "\n$$"
                if self.display.isChecked()
                else "$" + self.formula.text() + "$"
            )
            if self.preview_session is None or self.preview_session.source != source:
                self.preview_session = SourceSession(source)
                self.preview_resolver.selections.clear()
            document = parse_markdown(self.preview_session)
            errors = [d.message for d in document.diagnostics if d.severity == "error"]
            node = next((n for root in document.nodes for n in root.walk() if n.math), None)
            if errors or node is None:
                raise ValueError("; ".join(errors) or "请输入非空公式")
            box = measure_math(
                node.math,
                self.preview_resolver,
                owner=node.node_id,
                style=style,
                stroke_width=self.pen_mm,
                display=self.display.isChecked(),
            )
            self.preview.box = box
            self.preview.pen_mm = self.pen_mm
            missing = sorted({g.occurrence.text for g in box.glyphs if g.status == "missing"})
            issues = [d.message for d in box.diagnostics if d.severity == "error"]
            message = (
                ("缺少字形：" + " ".join(missing) + "；红框仅用于定位，不能用于机器输出。")
                if missing
                else ("预览存在不可书写问题：" + issues[0])
                if issues
                else ""
            )
            self.preview_status.setText(message)
            self.preview_status.setVisible(bool(message))
            self.error.clear()
        except (ValueError, TypeError) as error:
            self.preview.box = None
            self.preview.empty_message = "请检查下方提示，输入有效参数或公式"
            self.preview_status.setText("无法预览：" + str(error))
            self.preview_status.show()
        self.preview.update_geometry()

    def accept(self):
        try:
            self.configuration()
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()
