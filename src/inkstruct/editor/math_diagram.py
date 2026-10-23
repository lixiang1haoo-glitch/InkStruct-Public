"""Compact formula illustrations with nearby dimensions and hover explanations."""

from PySide6 import QtCore, QtGui, QtWidgets

# Fixed logical positions keep glyphs, dimension arrows and editors together when
# the window grows. Each entry is (editor x/y, arrow start/end), in field order.
LAYOUTS = (
    (((115, 106), (265, 111, 265, 149)),),
    (
        ((86, 82), (230, 100, 230, 112)),
        ((238, 22), (280, 77, 291, 77)),
        ((327, 128), (337, 113, 348, 113)),
        ((215, 210), (305, 192, 315, 192)),
    ),
    (
        ((337, 40), (340, 100, 340, 119)),
        ((126, 96), (270, 119, 270, 150)),
        ((280, 197), (337, 150, 337, 173)),
    ),
    (
        ((117, 77), (263, 92, 263, 115)),
        ((340, 100), (326, 115, 326, 126)),
    ),
    (((333, 62), (320, 116, 320, 128)),),
    (
        ((119, 103), (264, 104, 264, 158)),
        ((330, 158), (317, 157, 317, 172)),
        ((331, 35), (317, 81, 317, 96)),
    ),
    (
        ((113, 90), (260, 111, 260, 124)),
        ((280, 22), (305, 79, 319, 79)),
        ((125, 198), (270, 210, 270, 224)),
        ((359, 131), (335, 155, 345, 155)),
    ),
    (
        ((115, 95), (260, 125, 274, 125)),
        ((327, 183), (325, 169, 339, 169)),
    ),
    (
        ((94, 94), (240, 115, 240, 131)),
        ((310, 179), (329, 161, 349, 161)),
    ),
    (
        ((367, 90), (355, 117, 355, 138)),
        ((246, 183), (310, 160, 330, 160)),
    ),
    (
        ((114, 104), (260, 119, 260, 132)),
        ((340, 80), (326, 110, 326, 126)),
    ),
)


def info_button(parent, text="", name="说明"):
    button = QtWidgets.QToolButton(parent)
    button.setText("i")
    button.setObjectName("info_button")
    button.setAccessibleName(name)
    button.setToolTip(text)
    button.setFixedSize(19, 19)
    button.setCursor(QtCore.Qt.CursorShape.WhatsThisCursor)
    button.setStyleSheet(
        "QToolButton { color: #64748b; border: 1px solid #b7c4d2; "
        "border-radius: 9px; background: transparent; font: italic 12px Georgia; padding: 0; }"
        "QToolButton:hover, QToolButton:focus { color: #1269c7; border-color: #1269c7; }"
    )
    # Hover is the primary action; click/keyboard access exposes the same help.
    button.clicked.connect(
        lambda: QtWidgets.QToolTip.showText(
            button.mapToGlobal(QtCore.QPoint(0, button.height())), button.toolTip(), button
        )
    )
    return button


class StructureDiagram(QtWidgets.QWidget):
    parameterFocused = QtCore.Signal(str)

    def __init__(self, index, fields, parent=None):
        super().__init__(parent)
        self.index, self.fields = index, fields
        self.cards = {}
        self.active_key = fields[0][0]
        self.dimensions = {}
        self.leaders = {}
        self.setMinimumWidth(600)
        self.setFixedHeight(270)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.setObjectName("structure_diagram_" + str(index))

    def add_control(self, key, label, spin, reset):
        card = QtWidgets.QFrame(self)
        card.setObjectName("dimension_card")
        card.setProperty("active", key == self.active_key)
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        title = QtWidgets.QLabel(label, card)
        title.setStyleSheet("font-size: 11px; color: #475569;")
        layout.addWidget(title)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        spin.setFixedWidth(87)
        spin.setFixedHeight(25)
        spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        row.addWidget(spin)
        # Retain per-field reset without the old large card and extra text row.
        reset.setObjectName("reset_" + key)
        reset.setFixedSize(19, 19)
        reset.setAutoRaise(True)
        row.addWidget(reset)
        hint = info_button(card, name=label + "说明")
        row.addWidget(hint)
        layout.addLayout(row)
        for widget in (spin, spin.lineEdit(), card, title, hint):
            widget.setProperty("parameter_key", key)
            widget.installEventFilter(self)
        self.cards[key] = (card, hint)
        self.position_cards()

    def eventFilter(self, watched, event):
        if event.type() in (QtCore.QEvent.Type.FocusIn, QtCore.QEvent.Type.Enter):
            self.set_active(watched.property("parameter_key"))
        return super().eventFilter(watched, event)

    def set_active(self, key):
        if key not in self.cards or (
            key == self.active_key and self.cards[key][0].property("active")
        ):
            return
        self.active_key = key
        for current, (card, _) in self.cards.items():
            card.setProperty("active", current == key)
            card.style().unpolish(card)
            card.style().polish(card)
        self.parameterFocused.emit(key)
        self.update()

    def update_values(self, style):
        for key, label in self.fields:
            value = getattr(style, key)
            detail = (
                f"以毫米设置公式字号，等效 {value * 72 / 25.4:.2f} pt。"
                if key == "em_mm"
                else f"相对于当前层公式字号的百分比。按主字号估算为 {value * style.em_mm:.2f} mm；"
                "嵌套缩放和笔宽下限会影响实际尺寸。"
            )
            spin = self.cards[key][0].findChild(QtWidgets.QDoubleSpinBox)
            limits = f"允许范围：{spin.minimum():g}–{spin.maximum():g}{spin.suffix().strip()}。"
            self.cards[key][1].setToolTip(label + "\n" + limits + "\n" + detail)

    def position_cards(self):
        offset = (self.width() - 600) / 2
        for (key, _), (position, _) in zip(self.fields, LAYOUTS[self.index], strict=True):
            if key in self.cards:
                self.cards[key][0].setGeometry(round(offset + position[0]), position[1], 134, 46)

    def resizeEvent(self, event):
        self.position_cards()
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#ffffff"))
        offset = (self.width() - 600) / 2

        def point(x, y):
            return QtCore.QPointF(offset + x, y)

        def line(x1, y1, x2, y2, color="#253448", dashed=False, width=1.6):
            p.setPen(
                QtGui.QPen(
                    QtGui.QColor(color),
                    width,
                    QtCore.Qt.PenStyle.DashLine if dashed else QtCore.Qt.PenStyle.SolidLine,
                )
            )
            p.drawLine(point(x1, y1), point(x2, y2))

        def text(x, baseline, value, size=32):
            font = QtGui.QFont("Times New Roman")
            font.setPixelSize(size)
            font.setItalic(False)
            p.setFont(font)
            p.setPen(QtGui.QColor("#253448"))
            p.drawText(point(x, baseline), value)

        def box(x, y, w=20, h=22):
            p.setPen(QtGui.QPen(QtGui.QColor("#78a8da"), 1))
            p.setBrush(QtGui.QColor("#e4f0fc"))
            p.drawRect(QtCore.QRectF(point(x, y), QtCore.QSizeF(w, h)))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        idx = self.index
        if idx == 0:
            text(279, 149, "12.50", 42)
            line(274, 150, 379, 150, "#b6c4d3", True, 1)
        elif idx == 1:
            text(245, 112, "1 + 2 = 3", 32)
            line(240, 112, 375, 112, "#b6c4d3", True, 1)
            line(240, 100, 375, 100, "#c1d7ee", True, 1)
            text(267, 181, "sin 1", 30)
        elif idx == 2:
            text(286, 150, "x", 42)
            text(310, 119, "2", 24)
            text(310, 173, "1", 24)
            line(281, 150, 343, 150, "#b6c4d3", True, 1)
            line(306, 120, 343, 120, "#b6c4d3", True, 1)
        elif idx == 3:
            text(277, 115, "12", 32)
            line(273, 127, 316, 127)
            text(286, 158, "3", 32)
        elif idx == 4:
            for a, b in [
                ((253, 145), (260, 141)),
                ((260, 141), (268, 158)),
                ((268, 158), (280, 116)),
                ((280, 116), (330, 116)),
            ]:
                line(*a, *b)
            text(286, 151, "12", 32)
            text(254, 125, "3", 18)
        elif idx == 5:
            text(276, 151, "∑", 59)
            text(292, 96, "3", 21)
            text(292, 187, "1", 21)
            text(326, 141, "x", 32)
        elif idx == 6:
            for y in (89, 124):
                for x in (285, 319):
                    box(x, y)
            line(278, 83, 278, 153)
            line(345, 83, 345, 153)
            box(283, 210, 12, 14)
            box(303, 210, 12, 14)
        elif idx == 7:
            text(248, 157, "(", 78)
            text(324, 157, ")", 78)
            text(285, 112, "1", 30)
            text(285, 153, "2", 30)
            line(276, 124, 309, 124)
        elif idx == 8:
            text(255, 112, "1 = 2", 27)
            text(351, 112, "3 = 4", 27)
            text(255, 151, "5 = 6", 27)
            text(351, 151, "7 = 8", 27)
        elif idx == 9:
            text(231, 140, "12.50", 32)
            text(330, 138, "(1)", 26)
        else:
            text(276, 158, "AB", 38)
            line(274, 118, 318, 118)
            line(318, 118, 310, 110)
            line(318, 118, 310, 126)

        # Short local leaders, never a line from the edges of the panel.
        self.dimensions.clear()
        self.leaders.clear()
        for (key, _), (_, coords) in zip(self.fields, LAYOUTS[idx], strict=True):
            a, b = point(*coords[:2]), point(*coords[2:])
            self.dimensions[key] = (a, b)
            color = "#1269c7" if key == self.active_key else "#8ab5df"
            p.setPen(QtGui.QPen(QtGui.QColor(color), 1.5 if key == self.active_key else 1))
            p.drawLine(a, b)
            vector = b - a
            length = (vector.x() ** 2 + vector.y() ** 2) ** 0.5
            if length:
                u = vector / length
                n = QtCore.QPointF(-u.y(), u.x())
                for tip, sign in ((a, 1), (b, -1)):
                    p.drawLine(tip, tip + u * (3 * sign) + n * 2)
                    p.drawLine(tip, tip + u * (3 * sign) - n * 2)
                    p.drawLine(tip - n * 3, tip + n * 3)
            center = (a + b) / 2
            rect = self.cards[key][0].geometry()
            start = QtCore.QPointF(
                min(max(center.x(), rect.left()), rect.right()),
                min(max(center.y(), rect.top()), rect.bottom()),
            )
            self.leaders[key] = (start, center)
            p.drawLine(start, center)
        p.end()
