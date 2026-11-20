"""Compact directional controls for moving a pen or adjusting a glyph."""

from PySide6 import QtCore, QtGui, QtWidgets


class DirectionButton(QtWidgets.QToolButton):
    def __init__(self, title, angle):
        super().__init__()
        self.angle = angle
        self.setAccessibleName(title)
        self.setToolTip(title)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(36, 36)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.translate(QtCore.QRectF(self.rect()).center())
        painter.rotate(self.angle)
        group = QtGui.QPalette.ColorGroup.Active if self.isEnabled() else QtGui.QPalette.ColorGroup.Disabled
        pen = QtGui.QPen(self.palette().color(group, QtGui.QPalette.ColorRole.ButtonText), 2)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QtGui.QPolygonF([
            QtCore.QPointF(-6, 2), QtCore.QPointF(0, -4), QtCore.QPointF(6, 2),
        ]))


class PositionNudge(QtWidgets.QWidget):
    moved = QtCore.Signal(float, float)

    def __init__(self, title, *, unit, minimum, maximum, step=1., decimals=3):
        super().__init__()
        self.setObjectName("position_nudge")
        self.setAccessibleName(title)
        # Keep the three rows at their natural height inside tall scroll areas.
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        group = QtWidgets.QVBoxLayout(self)
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(4)
        group.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        group.addWidget(QtWidgets.QLabel(title))
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        group.addLayout(row)

        pad = QtWidgets.QGridLayout()
        pad.setSpacing(4)
        self.buttons = {}
        for name, vector, angle, y, x in (
            ("上", (0, -1), 0, 0, 1), ("左", (-1, 0), -90, 1, 0),
            ("右", (1, 0), 90, 1, 2), ("下", (0, 1), 180, 2, 1),
        ):
            button = DirectionButton(f"{title} · 向{name}一步", angle)
            button.clicked.connect(lambda _checked=False, v=vector:
                                   self.moved.emit(v[0] * self.step.value(), v[1] * self.step.value()))
            pad.addWidget(button, y, x)
            self.buttons[vector] = button
        center = QtWidgets.QLabel("＋")
        center.setProperty("inkRole", "hint")
        center.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        pad.addWidget(center, 1, 1)
        row.addLayout(pad)

        settings = QtWidgets.QVBoxLayout()
        settings.setSpacing(4)
        caption = QtWidgets.QLabel("步长")
        self.step = QtWidgets.QDoubleSpinBox()
        self.step.setAccessibleName(title + "步长")
        self.step.setDecimals(decimals)
        self.step.setRange(minimum, maximum)
        self.step.setSingleStep(step)
        self.step.setValue(step)
        self.step.setSuffix(f" {unit}")
        caption.setBuddy(self.step)
        settings.addStretch()
        settings.addWidget(caption)
        settings.addWidget(self.step)
        settings.addStretch()
        row.addLayout(settings)
        row.addStretch()
