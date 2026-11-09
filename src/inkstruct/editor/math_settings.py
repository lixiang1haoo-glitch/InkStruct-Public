"""Category-based mathematical settings with live centreline geometry and guides."""

from dataclasses import replace
from math import ceil, isclose
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..assets.resolver import AssetResolver
from ..document.editing import SourceSession
from ..document.markdown import parse_markdown
from ..math.handwritten import measure_math
from ..math.style import MathStyle
from .math_diagram import info_button
from .math_reference import MathReferenceFont

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
        "x_i^2",
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
        r"连分式逐层缩小；\dfrac 保持当前层字号。横线来源也用于 bar、overline、underline。净间距受笔宽下限约束。",
    ),
    (
        "根式",
        r"\sqrt[3]{12}",
        (("radical_clearance_em", "根式内部净间距"),),
        "采集根号保留钩部写法，横线随内容延长；几何模式使用折线。根指数字号沿用上下标比例。",
    ),
    (
        "积分与大运算符",
        r"\sum\limits_{1}^{3}12",
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
        r"\left / \right 及矩阵括号围绕数学轴适配高度；录制括号保留端部和花括号中腰，伸长中段。宽度有三倍笔宽下限。",
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
        "bar、overline、underline 沿用分式的横线来源，录制模式拉长减号。其他修饰符使用折线，点号使用短线；原字形保持不变。",
    ),
)


EXAMPLES = {
    1: (("函数间距", r"\sin 12"), ("正斜体", r"x+\alpha=\sin x+\log 2+\operatorname{rank} x+\mathrm{d}x")),
    2: (("数字上下标", "12_3^4"),),
    3: (("连分式", r"\frac{12}{\frac{3}{4}}"), ("行间分式", r"\dfrac{12}{3}")),
    5: (("积分", r"\int_{1}^{3}x\,\mathrm{d}x"), ("堆叠上下限", r"\int\limits_{1}^{3}12")),
    6: (
        ("行内小矩阵", r"\begin{smallmatrix}1&2\\3&4\end{smallmatrix}"),
        ("带框线数组", r"\begin{array}{c|c}1&2\\\hline 3&4\end{array}"),
    ),
    8: (("两组等式对齐", r"\begin{aligned}1&=2&3&=4\\5&=6&7&=8\end{aligned}"),),
}

ANNOTATION_CANVAS_HEIGHT = 222

# The default overview includes the rows needed to explain the whole category.
OVERVIEW_EXAMPLES = {1: (1,), 6: (1, 2), 8: (1,)}


class DimensionSpinBox(QtWidgets.QDoubleSpinBox):
    """Keep editing precision without filling every field with trailing zeros."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

    def textFromValue(self, value):
        text = super().textFromValue(value)
        separator = self.locale().decimalPoint()
        return text.rstrip("0").rstrip(separator) if separator in text else text


class MathPreview(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.box = None
        self.guide_rows = ()
        self.dimension_tops = {}
        self.dimension_bottoms = {}
        self.pen_mm = 0.3
        self.setMinimumSize(175, 135)
        self.reference = None
        self.show_actual = False
        self.measurement_tips = []
        self.active_key = None
        self.align = "center"
        self.show_guides = True
        self.annotation_keys = ()
        self.annotation_gutter = 0
        self.annotation_rows = {}
        self.zoom_percent = 200
        self.empty_message = "输入受支持的公式以查看几何预览"

    @property
    def pixels_per_mm(self):
        return 96 / 25.4 * self.zoom_percent / 100

    def vertical_bounds(self):
        points = [y for d in self.box.dimensions if d.key in self.annotation_keys
                  for _, y in (d.start, d.end)]
        return min(-self.box.ascent, -self.box.axis, *points), max(self.box.descent, 0, *points)

    def update_geometry(self):
        if self.box is None:
            self.setMinimumSize(175, 135)
        else:
            top, bottom = self.vertical_bounds()
            height = bottom - top
            readout_height = 32 + len(self.annotation_keys) * (self.actual_row_height() + 4) if self.show_actual else 0
            self.setMinimumSize(
                max(175, ceil(self.box.width * self.pixels_per_mm + 88 + self.actual_label_width())),
                max(135, readout_height, ceil(height * self.pixels_per_mm + 72)),
            )
        self.updateGeometry()
        self.update()

    def set_zoom(self, percent):
        self.zoom_percent = percent
        self.update_geometry()

    def set_boxes(self, boxes):
        self.dimension_tops.clear()
        self.dimension_bottoms.clear()
        if len(boxes) == 1:
            self.box, = boxes
            self.guide_rows = ((self.box, 0, 0),)
            return
        width = max(box.width for box in boxes)
        rows, glyphs, rules, dimensions, diagnostics = [], [], [], [], []
        baseline = 0
        for box in boxes:
            if rows:
                previous = rows[-1][0]
                baseline += previous.descent + box.ascent + 8
            x = 0 if self.align == 'left' else (width - box.width) / 2
            rows.append((box, x, baseline))
            glyphs.extend(replace(g, x_mm=g.x_mm + x, baseline_mm=g.baseline_mm + baseline)
                          for g in box.glyphs)
            rules.extend(replace(rule, points=tuple((a + x, b + baseline) for a, b in rule.points))
                         for rule in box.rules)
            for mark in box.dimensions:
                translated = mark.translated(x, baseline)
                dimensions.append(translated)
                self.dimension_tops[id(translated)] = baseline - box.ascent
                self.dimension_bottoms[id(translated)] = baseline + box.descent
            diagnostics.extend(box.diagnostics)
        self.guide_rows = tuple(rows)
        self.box = replace(boxes[0], width=width, descent=baseline + boxes[-1].descent,
                           glyphs=tuple(glyphs), rules=tuple(rules), dimensions=tuple(dimensions),
                           diagnostics=tuple(diagnostics))

    def origin(self):
        top, bottom = self.vertical_bounds()
        zoom = self.pixels_per_mm
        available = self.width() - (self.annotation_gutter or self.actual_label_width())
        x = 30 if self.align == "left" else (available - self.box.width * zoom) / 2
        y = (self.height() - max(1, bottom - top) * zoom) / 2 - top * zoom
        return x, y

    def annotation_marks(self, key):
        return [mark for mark in self.box.dimensions if mark.key == key][
            :2 if key == "fraction_clearance_em" else 1
        ] if self.box else []

    def horizontal_guide_y(self, mark, number, origin_y):
        if mark.start[1] != mark.end[1] or mark.start[0] == mark.end[0]:
            return None
        top = self.dimension_tops.get(id(mark), -self.box.ascent)
        if mark.key in {'binary_gap_em', 'relation_gap_em'}:
            bottom = self.dimension_bottoms.get(id(mark), self.box.descent)
            return origin_y + max(mark.start[1], bottom) * self.pixels_per_mm + 8 + (number - 2) * 13
        if mark.key == 'operator_gap_em':
            return origin_y + min(mark.start[1], top) * self.pixels_per_mm - 12
        return origin_y + min(mark.start[1], top) * self.pixels_per_mm - 8 - (number - 1) * 13

    def actual_label_width(self):
        if not self.show_actual or not self.box:
            return 0
        metrics = self.fontMetrics()
        return max((metrics.horizontalAdvance(self.actual_readout(number, self.annotation_marks(key)))
                    for number, key in enumerate(self.annotation_keys, 1)), default=0)

    @staticmethod
    def actual_readout(number, marks):
        value = " / ".join(f"{mark.actual:.2f}" for mark in marks) + " mm" if marks else "—"
        return f"{number}  {value}"

    def actual_row_height(self):
        return max(24, self.fontMetrics().height() + 6)

    def record_measurement_tip(self, area, marks):
        details = []
        for mark in marks:
            line = f"{mark.label} · 实测 {mark.actual:.2f} mm"
            if mark.note and not isclose(mark.actual, mark.requested, abs_tol=.0001):
                line += "\n" + mark.note
            details.append(line)
        self.measurement_tips.append((area.adjusted(-5, -5, 5, 5), "\n".join(details)))

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            for area, tip in self.measurement_tips:
                if area.contains(event.pos()):
                    QtWidgets.QToolTip.showText(event.globalPos(), tip, self, area.toAlignedRect())
                    return True
            QtWidgets.QToolTip.hideText()
            event.ignore()
            return True
        return super().event(event)

    def paintEvent(self, event):
        self.measurement_tips.clear()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        paper, ink = palette.base().color(), palette.text().color()
        accent = palette.link().color()
        guide = QtGui.QColor.fromRgbF(*(
            0.7 * foreground + 0.3 * background
            for foreground, background in zip(ink.getRgbF()[:3], paper.getRgbF()[:3])
        ))
        p.fillRect(self.rect(), paper)
        p.setPen(ink)
        if self.box is None:
            p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.empty_message)
            return
        box = self.box
        zoom = self.pixels_per_mm
        ox, oy = self.origin()

        def at(x, y):
            return QtCore.QPointF(ox + x * zoom, oy + y * zoom)

        if self.show_guides:
            for row, x, baseline in self.guide_rows:
                for y, color in ((baseline, guide), (baseline - row.axis, accent)):
                    p.setPen(QtGui.QPen(color, 1, QtCore.Qt.PenStyle.DashLine))
                    p.drawLine(at(x - 2, y), at(x + row.width + 2, y))
        pen = QtGui.QPen(
            ink,
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
            elif g.outline:
                p.save()
                p.translate(at(g.x_mm + g.origin_offset_mm, g.baseline_mm))
                scale = g.em_mm * zoom / 1000
                p.scale(scale, scale)
                p.fillPath(self.reference.paths[g.outline.glyph_index], ink)
                p.restore()
            elif g.status != "space":
                dark = paper.lightness() < 128
                p.setPen(QtGui.QColor("#ffabab" if dark else "#b91c1c"))
                p.setBrush(QtGui.QColor("#47282d" if dark else "#fff1f2"))
                rect = QtCore.QRectF(
                    at(g.x_mm, g.baseline_mm - g.ascent_mm),
                    at(g.x_mm + g.advance_mm, g.baseline_mm + g.descent_mm),
                )
                p.drawRect(rect)
                p.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, g.occurrence.text)
        for rule in box.rules:
            stroke(rule.points)

        def arrow(a, b):
            p.drawLine(a, b)
            if a.y() == b.y():
                left, right = sorted((a.x(), b.x()))
                for x, sign in ((left, 1), (right, -1)):
                    tip = QtCore.QPointF(x, a.y())
                    if right - left < 10:
                        p.drawLine(tip + QtCore.QPointF(0, -3), tip + QtCore.QPointF(0, 3))
                    else:
                        for dy in (-3, 3):
                            p.drawLine(tip, tip + QtCore.QPointF(sign * 5, dy))
            else:
                top, bottom = sorted((a.y(), b.y()))
                for y, sign in ((top, 1), (bottom, -1)):
                    tip = QtCore.QPointF(a.x(), y)
                    if bottom - top < 10:
                        p.drawLine(tip + QtCore.QPointF(-3, 0), tip + QtCore.QPointF(3, 0))
                    else:
                        for dx in (-3, 3):
                            p.drawLine(tip, tip + QtCore.QPointF(dx, sign * 5))

        self.paint_annotations(p, at, arrow, paper, guide, accent)

    def paint_annotations(self, painter, at, arrow, paper, guide, accent):
        rail = at(self.box.width, 0).x()
        for number, key in enumerate(self.annotation_keys, 1):
            marks = self.annotation_marks(key)
            active = key == self.active_key
            color = accent if active else guide
            painter.setPen(QtGui.QPen(color, 1.25 if active else 0.8))
            row = self.annotation_rows.get(key)
            if self.show_actual and row is not None:
                painter.drawText(row, QtCore.Qt.AlignVCenter, self.actual_readout(number, marks))
                if marks:
                    self.record_measurement_tip(QtCore.QRectF(row), marks)
                else:
                    self.measurement_tips.append((QtCore.QRectF(row), "此示例未涉及此尺寸"))
            if not marks:
                continue
            x = rail + 6 + (number - 1) * 9
            mid = []
            for mark in marks:
                a, b = at(*mark.start), at(*mark.end)
                y = self.horizontal_guide_y(mark, number, at(0, 0).y())
                if y is not None:
                    start, end = QtCore.QPointF(a.x(), y), QtCore.QPointF(b.x(), y)
                    painter.drawLine(end if end.x() > start.x() else start, QtCore.QPointF(x, y))
                else:
                    start, end = QtCore.QPointF(x, a.y()), QtCore.QPointF(x, b.y())
                painter.drawLine(a, start)
                painter.drawLine(b, end)
                arrow(start, end)
                self.record_measurement_tip(QtCore.QRectF(start, end).normalized(), [mark])
                mid.append((start.y() + end.y()) / 2)
            anchor = QtCore.QPointF(x, sum(mid) / len(mid))
            if row is None:
                badge = anchor + QtCore.QPointF(10, 0)
                rect = QtCore.QRectF(badge.x() - 7, badge.y() - 7, 14, 14)
                painter.setBrush(paper)
                painter.drawEllipse(rect)
                painter.drawText(rect, QtCore.Qt.AlignCenter, str(number))
                painter.setBrush(QtCore.Qt.NoBrush)
                self.record_measurement_tip(rect, marks)
                continue
            endpoint = QtCore.QPointF(row.left() - 4, row.center().y())
            bend = QtCore.QPointF(endpoint.x() - 7, anchor.y())
            painter.drawLine(anchor, bend)
            painter.drawLine(bend, endpoint)


class MathCategoryDelegate(QtWidgets.QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # Native Windows styles can omit stylesheet padding from the row hint.
        size.setHeight(max(size.height(), option.fontMetrics.height() + 20))
        return size


class CurrentMathPanel(QtWidgets.QStackedWidget):
    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page else super().sizeHint()

    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page else super().minimumSizeHint()


class MathSettingsDialog(QtWidgets.QDialog):
    def __init__(self, style, parent=None, *, resolver=None, stroke_width=0.3,
                 embedded=False, font_path=None):
        super().__init__(parent)
        self.original = style
        resolver = resolver or AssetResolver(builtin_numbers=True)
        self.set_preview_resources(resolver, font_path)
        self.preview_document = None
        self.active_key = None
        self.reference_error = ""
        try:
            self.reference = MathReferenceFont()
        except (OSError, ValueError) as error:
            self.reference = None
            self.reference_error = str(error)
        self.pen_mm = stroke_width
        self.preview_session = None
        self.setWindowTitle("公式字体与样式")
        self.setObjectName("math_settings_dialog")
        if not embedded:
            available = (parent or self).screen().availableGeometry().size()
            width, height = min(1220, available.width() - 40), min(840, available.height() - 64)
            self.setMinimumSize(min(600, width), min(400, height))
            self.resize(width, height)
        self.setStyleSheet("""
            QWidget#math_content, QDialog#math_settings_dialog { background: palette(window); }
            QListWidget { background: palette(base); border: none; border-radius: 8px; padding: 6px; }
            QListWidget::item { padding: 5px 8px; border-radius: 5px; }
            QListWidget::item:selected {
                background: palette(highlight); color: palette(highlighted-text); font-weight: bold;
            }
            QDoubleSpinBox {
                min-height: 20px; background: palette(base); color: palette(text);
                border: 1px solid palette(mid); border-radius: 2px; padding: 1px 3px;
            }
            QDoubleSpinBox[activeMathDimension="true"] { border-color: palette(highlight); }
            QToolButton { padding: 3px; }
            QScrollArea { border: none; background: transparent; }
            QLabel#section_title { font-size: 20px; font-weight: bold; }
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*(0, 0, 0, 0) if embedded else (18, 16, 18, 14))
        layout.setSpacing(12)
        if not embedded:
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
        scroll = self.parameter_scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.viewport().installEventFilter(self)
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
        self.panels = CurrentMathPanel(content)
        self.panels.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.controls, self.initial, self.factors = {}, {}, {}
        self.sources = {}
        self.control_keys = {}
        self.reset_buttons = {}
        self.annotation_cards = {}
        for index, (title, sample, fields, explanation) in enumerate(GROUPS):
            self.categories.addItem(title)
            page = QtWidgets.QWidget(self.panels)
            page_layout = QtWidgets.QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(7)
            options = QtWidgets.QFormLayout()
            options.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
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
                options.addRow("手写分数线" if index == 3 else "手写构件来源", choice)
            for number, (key, label) in enumerate(fields, 1):
                widget = DimensionSpinBox(page)
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
                reset = QtWidgets.QToolButton(page)
                reset.setText("↺")
                reset.setToolTip("恢复“" + label + "”默认值")
                reset.setAccessibleName("恢复" + label + "默认值")
                reset.clicked.connect(lambda checked=False, key=key: self.reset_parameter(key))
                reset.setObjectName("reset_" + key)
                reset.setAutoRaise(True)
                self.reset_buttons[key] = reset
                card = QtWidgets.QWidget(content)
                row = QtWidgets.QHBoxLayout()
                row.addWidget(widget)
                row.addWidget(reset)
                row.addStretch(1)
                title_label = QtWidgets.QLabel(f"{number}  {label}")
                title_label.setBuddy(widget)
                card_layout = QtWidgets.QVBoxLayout(card)
                card_layout.setContentsMargins(5, 1, 4, 1)
                card_layout.setSpacing(1)
                card_layout.addWidget(title_label)
                card_layout.addLayout(row)
                card.hide()
                self.annotation_cards[key] = card
                for target in (widget, widget.lineEdit()):
                    self.control_keys[target] = key
                    target.installEventFilter(self)
            if title == "字号与字形":
                self.points = DimensionSpinBox(page)
                self.points.setDecimals(4)
                self.points.setKeyboardTracking(True)
                self.points.setRange(0.0001, 2000 * 72 / 25.4)
                self.points.setSuffix(" pt")
                self.points.setValue(style.em_mm * 72 / 25.4)
                self.points.setAccessibleName("等效字号")
                for target in (self.points, self.points.lineEdit()):
                    self.control_keys[target] = "em_mm"
                    target.installEventFilter(self)
                options.addRow("等效字号", self.points)
                self.points.valueChanged.connect(self.points_changed)
                self.controls["em_mm"].valueChanged.connect(self.mm_changed)
                self.alignment = QtWidgets.QComboBox(page)
                self.alignment.addItem("居中", "center")
                self.alignment.addItem("左对齐", "left")
                self.alignment.setCurrentIndex(self.alignment.findData(style.display_align))
                options.addRow("独立公式对齐", self.alignment)
                self.spacing_policy = QtWidgets.QComboBox(page)
                self.spacing_policy.setAccessibleName("公式字距")
                self.spacing_policy.addItem("按笔迹紧凑排列（推荐）", "handwriting")
                self.spacing_policy.addItem("保留采集留白与原结构尺寸（旧版）", "capture")
                self.spacing_policy.setCurrentIndex(self.spacing_policy.findData(style.spacing_policy))
                self.spacing_policy.setToolTip("消除公式采集格留白，按实际笔迹布置结构；保留字号、数学轴、显式空格及冻结选样。旧文档仅在明确应用后改变。")
                options.addRow("公式字距", self.spacing_policy)
            self.panels.addWidget(page)
        preview_heading = QtWidgets.QHBoxLayout()
        preview_heading.addWidget(QtWidgets.QLabel("对照预览", content))
        preview_heading.addWidget(
            info_button(
                content,
                "两栏使用相同公式、参数、模式和倍率。灰色虚线是基线，蓝色虚线是数学轴。印刷栏使用 Latin Modern Math 字形与程序构件，手写缺字保留红框。",
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
        source_row = QtWidgets.QHBoxLayout()
        self.example_choice = QtWidgets.QComboBox(content)
        self.example_choice.setAccessibleName("试排示例")
        self.example_choice.setMinimumWidth(110)
        self.example_choice.currentIndexChanged.connect(self.schedule_preview)
        source_row.addWidget(self.example_choice)
        source_row.addStretch(1)
        self.display = QtWidgets.QCheckBox("独立公式", content)
        self.display.setChecked(True)
        source_row.addWidget(self.display)
        centre.addLayout(source_row)
        self.preview_status = QtWidgets.QLabel(content)
        self.preview_status.setWordWrap(True)
        self.preview_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        centre.addWidget(self.preview_status)
        pair = QtWidgets.QGridLayout()
        self.print_preview = MathPreview(content)
        self.print_preview.reference = self.reference
        self.preview = MathPreview(content)
        self.preview.show_actual = True
        self.preview_areas = []
        for column, (pane, title) in enumerate(((self.print_preview, "印刷参考 · Latin Modern Math"),
                                               (self.preview, "手写预览 · 当前字形资源"))):
            pane_title = QtWidgets.QLabel(title, content)
            pane_title.setWordWrap(True)
            pair.addWidget(pane_title, 0, column)
            area = QtWidgets.QScrollArea(content)
            area.setWidgetResizable(True)
            area.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            area.setMinimumWidth(110)
            area.setFixedHeight(175)
            area.setWidget(pane)
            self.preview_areas.append(area)
            area.viewport().installEventFilter(self)
            pair.addWidget(area, 1, column)
            pair.setColumnStretch(column, 1)
            if pane is self.preview:
                self.preview_scroll = area
        self.controls_below = QtWidgets.QWidget(content)
        self.controls_below.setLayout(QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight))
        self.controls_below.layout().setContentsMargins(0, 0, 0, 0)
        self.controls_below.layout().setSpacing(4)
        self.controls_below.hide()
        pair.addWidget(self.controls_below, 2, 0, 1, 2)
        centre.addLayout(pair)
        centre.addWidget(self.panels)
        self.annotation_timer = QtCore.QTimer(self)
        self.annotation_timer.setSingleShot(True)
        self.annotation_timer.timeout.connect(self.position_annotation_controls)
        self.guides.setChecked(True)
        self.preview_zoom.currentIndexChanged.connect(self.zoom_changed)
        units = QtWidgets.QLabel("百分比以当前层公式字号为基准。标线显示实际结果，缺字红框为占位。")
        units.setWordWrap(True)
        centre.addWidget(units)
        centre.addStretch()
        self._example_indices = [0] * len(GROUPS)
        self._last_category = None
        self.error = QtWidgets.QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        if not embedded:
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
        for key, c in self.controls.items():
            c.valueChanged.connect(lambda _value, key=key: self.parameter_changed(key))
            c.lineEdit().textEdited.connect(self.schedule_preview)
            c.editingFinished.connect(self.schedule_preview)
        self.points.lineEdit().textEdited.connect(self.schedule_preview)
        self.points.editingFinished.connect(self.schedule_preview)
        for c in self.sources.values():
            c.currentIndexChanged.connect(self.schedule_preview)
        self.spacing_policy.currentIndexChanged.connect(self.schedule_preview)
        self.alignment.currentIndexChanged.connect(self.schedule_preview)
        self.display.toggled.connect(self.schedule_preview)
        self.categories.currentRowChanged.connect(self.category_changed)
        self.categories.setCurrentRow(0)
        self.refresh_preview()

    def toggle_guides(self, checked):
        for pane in (self.print_preview, self.preview):
            pane.show_guides = checked
            pane.update()

    def zoom_changed(self):
        for pane in (self.print_preview, self.preview):
            pane.set_zoom(self.preview_zoom.currentData())
        self.annotation_timer.start(0)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.FocusIn and watched in self.control_keys:
            self.activate_parameter(self.control_keys[watched])
        if (event.type() == QtCore.QEvent.Resize and hasattr(self, "annotation_timer")
                and (watched is self.parameter_scroll.viewport()
                     or any(watched is area.viewport() for area in self.preview_areas))):
            self.annotation_timer.start(0)
        return super().eventFilter(watched, event)

    def position_annotation_controls(self):
        panes = self.print_preview, self.preview
        keys = self.print_preview.annotation_keys
        if not keys:
            return
        # Reparenting a focused spin box commits its text. Let the user correct
        # intermediate input before moving the controls between layouts.
        if any(self.controls[key].hasFocus() and not self.controls[key].hasAcceptableInput() for key in keys):
            return
        cards = [self.annotation_cards[key] for key in keys]
        width = max(card.sizeHint().width() for card in cards)
        height = max(card.sizeHint().height() for card in cards)
        gutters = width + 22, self.preview.actual_label_width() + 24
        # Keep the same preview scale. A long or tall formula uses the bottom
        # controls as well, so no editable field sits outside the visible canvas.
        viewport = self.parameter_scroll.viewport()
        required_height = max((ceil((pane.vertical_bounds()[1] - pane.vertical_bounds()[0])
                                    * pane.pixels_per_mm + 72) for pane in panes if pane.box), default=0)
        canvas_height = max(ANNOTATION_CANVAS_HEIGHT, 36 + len(cards) * (height + 4), min(460, required_height))
        wide = viewport.height() >= max(395, canvas_height + 130) and all(
            pane.box
            and area.viewport().width() >= gutter + max(140, pane.box.width * pane.pixels_per_mm + 56)
            for pane, area, gutter in zip(panes, self.preview_areas, gutters, strict=True)
        ) and required_height <= canvas_height
        focus = QtWidgets.QApplication.focusWidget()
        keep_focus = focus is not None and any(card.isAncestorOf(focus) for card in cards)
        host = self.print_preview if wide else self.controls_below
        self.controls_below.layout().setDirection(
            QtWidgets.QBoxLayout.LeftToRight if viewport.width() >= len(cards) * (width + 4) + 16
            else QtWidgets.QBoxLayout.TopToBottom
        )
        for key, card in zip(keys, cards, strict=True):
            card.setToolTip("" if self.print_preview.annotation_marks(key) else "此示例未涉及此尺寸，可切换内置示例。")
            if card.parentWidget() is not host:
                self.controls_below.layout().removeWidget(card)
                if wide:
                    card.setParent(host)
                else:
                    host.layout().addWidget(card, 0, QtCore.Qt.AlignLeft)
            card.show()
        self.controls_below.setVisible(not wide)
        if keep_focus and focus is not QtWidgets.QApplication.focusWidget():
            focus.setFocus(QtCore.Qt.OtherFocusReason)
        for pane, area, gutter in zip(panes, self.preview_areas, gutters, strict=True):
            preview_height = canvas_height if wide else min(285, max(156, required_height)) if len(pane.guide_rows) > 1 else 156
            if area.height() != preview_height:
                area.setFixedHeight(preview_height)
            inline = wide or pane.show_actual
            pane.annotation_gutter = gutter if inline else 0
            pane.annotation_rows = {}
            if inline and pane.box:
                left = pane.width() - gutter + 12
                _, oy = pane.origin()
                anchors = {}
                for number, key in enumerate(keys, 1):
                    positions = []
                    for mark in pane.annotation_marks(key):
                        y = pane.horizontal_guide_y(mark, number, oy)
                        if y is None:
                            y = oy + (mark.start[1] + mark.end[1]) * pane.pixels_per_mm / 2
                        positions.append(y)
                    anchors[key] = (sum(positions) / len(positions) if positions
                                    else pane.height() * number / (len(keys) + 1))
                row_height = height if pane is self.print_preview else pane.actual_row_height()
                top = 6
                ordered = keys if self.categories.currentRow() == 1 else sorted(keys, key=anchors.get)
                for index, key in enumerate(ordered):
                    remaining = len(keys) - index
                    latest = pane.height() - 26 - remaining * (row_height + 4)
                    y = max(top, min(latest, round(anchors[key] - row_height / 2)))
                    rect = QtCore.QRect(left, y, gutter - 20, row_height)
                    pane.annotation_rows[key] = rect
                    if pane is self.print_preview:
                        self.annotation_cards[key].setGeometry(rect)
                    top = y + row_height + 4
            pane.update()

    def parameter_changed(self, key):
        self.activate_parameter(key)
        self.schedule_preview()

    def activate_parameter(self, key):
        if key == self.active_key:
            return
        previous = self.active_key
        self.active_key = key
        for field in (previous, key):
            if field in self.controls:
                control = self.controls[field]
                control.setProperty("activeMathDimension", field == key)
                control.style().unpolish(control)
                control.style().polish(control)
        for pane in (self.print_preview, self.preview):
            pane.active_key = key
            pane.update()
        self.annotation_timer.start(0)
    def example_source(self):
        examples = [self.example_choice.currentData()]
        if self.example_choice.currentIndex() == 0:
            examples.extend(self.example_choice.itemData(i)
                            for i in OVERVIEW_EXAMPLES.get(self.categories.currentRow(), ()))
        opening, closing = ("$$\n", "\n$$") if self.display.isChecked() else ("$", "$")
        return "\n\n".join(opening + formula + closing for formula in examples)

    def reset_parameter(self, key):
        default = getattr(MathStyle.handwriting(), key)
        self.original = replace(self.original, **{key: default})
        self.controls[key].setValue(default * self.factors[key])
        self.initial[key] = self.controls[key].value()
        self.parameter_changed(key)

    def mm_changed(self, value):
        with QtCore.QSignalBlocker(self.points):
            self.points.setValue(value * 72 / 25.4)

    def points_changed(self, value):
        self.controls["em_mm"].setValue(value * 25.4 / 72)

    def category_changed(self, index):
        if not 0 <= index < len(GROUPS):
            return
        if self._last_category is not None:
            self._example_indices[self._last_category] = self.example_choice.currentIndex()
        self._last_category = index
        self.panels.setCurrentIndex(index)
        self.panels.updateGeometry()
        keys = tuple(key for key, _ in GROUPS[index][2])
        for card in self.annotation_cards.values():
            card.hide()
        self.controls_below.hide()
        self.panels.setVisible(index in {0, 3, 4, 7})
        for pane, area in zip((self.print_preview, self.preview), self.preview_areas, strict=True):
            pane.annotation_keys = keys
            pane.annotation_rows = {}
            pane.annotation_gutter = 0
            area.setFixedHeight(ANNOTATION_CANVAS_HEIGHT)
        self.category_title.setText(GROUPS[index][0])
        self.explanation.setToolTip(
            GROUPS[index][3]
            + "\n100% 对应当前层公式字号。蓝色标线随所选参数更新。"
        )
        with QtCore.QSignalBlocker(self.example_choice):
            self.example_choice.clear()
            default_name = "参数总览" if index in OVERVIEW_EXAMPLES else "普通分式" if index == 3 else "默认示例"
            self.example_choice.addItem(default_name, GROUPS[index][1])
            for title, source in EXAMPLES.get(index, ()):
                self.example_choice.addItem(title, source)
            self.example_choice.setCurrentIndex(self._example_indices[index])
        self.example_choice.setVisible(self.example_choice.count() > 1)
        self.activate_parameter(GROUPS[index][2][0][0])
        self.schedule_preview()
        self.annotation_timer.start(0)

    def reset_category(self):
        defaults = MathStyle.handwriting()
        if self.categories.currentRow() == 0:
            self.alignment.setCurrentIndex(self.alignment.findData(defaults.display_align))
            self.spacing_policy.setCurrentIndex(self.spacing_policy.findData(defaults.spacing_policy))
        for key, _label in GROUPS[self.categories.currentRow()][2]:
            self.reset_parameter(key)
        key = {3: "fraction_source", 4: "radical_source", 7: "delimiter_source"}.get(
            self.categories.currentRow()
        )
        if key:
            self.sources[key].setCurrentIndex(self.sources[key].findData(getattr(defaults, key)))

    def schedule_preview(self, *args):
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

    def set_preview_resources(self, resolver, font_path=None):
        self.embedded = tuple(g for pool in resolver.pools.values() for g in pool)
        self.preview_seed = resolver.seed
        self.font_path = Path(font_path) if font_path and str(font_path).lower().endswith(".inkfont") else None
        self.preview_resolver = AssetResolver(embedded=self.embedded, seed=self.preview_seed)
        self.font_preview_source = None

    def prepare_handwriting(self, nodes, source):
        if self.font_path is None or self.font_preview_source == source:
            return
        from ..fonts.core import cached_font

        characters = {n.value for node in nodes for n in node.math.walk() if n.kind == "Symbol"} | set("−√()[]{}|‖")
        if "ℏ" in characters:
            characters.update("h-")
        if "．" in characters:
            characters.add(".")
        glyphs = tuple(cached_font(self.font_path).glyphs(characters, reuse=self.embedded))
        # Reuse validated decodes, but never merge another font's pool into the
        # linked font. This draft may target a different default than the document.
        self.preview_resolver = AssetResolver(embedded=glyphs, seed=self.preview_seed, builtin_numbers=True)
        self.font_preview_source = source

    def refresh_preview(self):
        self.timer.stop()
        try:
            style = self.configuration()
            display = self.display.isChecked()
            for pane in (self.print_preview, self.preview):
                pane.align = style.display_align if display else "center"
            source = self.example_source()
            if self.preview_session is None or self.preview_session.source != source:
                self.preview_session = SourceSession(source)
                self.preview_resolver.selections.clear()
                self.preview_document = parse_markdown(self.preview_session)
            document = self.preview_document
            errors = [d.message for d in document.diagnostics if d.severity == "error"]
            nodes = [n for root in document.nodes for n in root.walk() if n.math]
            if errors or not nodes:
                raise ValueError("、".join(errors) or "请输入非空公式")
            args = dict(style=style, stroke_width=self.pen_mm, display=display, inspect=True)
            if self.reference:
                self.print_preview.set_boxes([measure_math(
                    node.math, self.preview_resolver, owner=node.node_id, reference=self.reference.measure, **args
                ) for node in nodes])
            else:
                self.print_preview.empty_message = "印刷参考不可用"
            issues = [d.message for d in self.print_preview.box.diagnostics
                      if d.code == "reference-glyph-missing"] if self.print_preview.box else []
            if self.reference_error:
                issues.append(self.reference_error)
            try:
                self.prepare_handwriting(nodes, source)
                self.preview.set_boxes([measure_math(
                    node.math, self.preview_resolver, owner=node.node_id, **args
                ) for node in nodes])
                missing = sorted({g.occurrence.text for g in self.preview.box.glyphs if g.status == "missing"})
                hand_errors = [d.message for d in self.preview.box.diagnostics if d.severity == "error"]
                if missing:
                    issues.append("手写缺少字形：" + " ".join(missing) + "。红框用于定位。")
                if hand_errors and (not missing or any(
                        d.code != "asset-missing" for d in self.preview.box.diagnostics if d.severity == "error")):
                    issues.append("手写预览：" + hand_errors[-1])
            except (OSError, ValueError) as error:
                self.preview.box = None
                self.preview.empty_message = "手写预览不可用"
                issues.append("手写预览：" + str(error))
            self.preview_status.setText("\n".join(issues))
            self.preview_status.setVisible(bool(issues))
            self.error.clear()
        except (ValueError, TypeError) as error:
            for pane in (self.print_preview, self.preview):
                pane.box = None
                pane.empty_message = "请输入有效参数或公式"
            self.preview_status.setText("无法预览：" + str(error))
            self.preview_status.show()
        for pane in (self.print_preview, self.preview):
            pane.pen_mm = self.pen_mm
            pane.update_geometry()
        self.annotation_timer.start(0)

    def accept(self):
        try:
            self.configuration()
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()
