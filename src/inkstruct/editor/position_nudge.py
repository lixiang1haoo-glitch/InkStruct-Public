"""Compact directional controls for moving a pen or adjusting a glyph."""

from PySide6 import QtCore, QtGui, QtWidgets


STEP_PRESETS = (.1, .5, 1, 2, 5, 10, 20, 50, 100)
FEED_PRESETS = (200, 500, 1000, 2000, 2500, 3500, 5000)


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

    def __init__(self, title, *, unit, minimum, maximum, step=1., decimals=3, plotter=False):
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
            button.clicked.connect(lambda _checked=False, v=vector: self.move_one_step(v))
            pad.addWidget(button, y, x)
            self.buttons[vector] = button
        center = QtWidgets.QLabel("＋")
        center.setProperty("inkRole", "hint")
        center.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        pad.addWidget(center, 1, 1)
        row.addLayout(pad)

        settings = QtWidgets.QVBoxLayout()
        settings.setSpacing(4)
        settings.addStretch()
        if plotter:
            self.step = QtWidgets.QComboBox()
            for value in STEP_PRESETS:
                self.step.addItem(f"{value:g} mm", value)
            self.step.setCurrentIndex(STEP_PRESETS.index(step))
            self.add_setting(settings, "点动步长", self.step)
            self.feed = QtWidgets.QComboBox()
            self.feed.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
            for value in FEED_PRESETS:
                self.feed.addItem(f"{value} mm/min", value)
            self.feed.setToolTip("保存到当前设备，点动、空走和书写共用此速度。")
            self.add_setting(settings, "运动速度", self.feed)
        else:
            self.step = QtWidgets.QDoubleSpinBox()
            self.step.setDecimals(decimals)
            self.step.setRange(minimum, maximum)
            self.step.setSingleStep(step)
            self.step.setValue(step)
            self.step.setSuffix(f" {unit}")
            self.add_setting(settings, "步长", self.step)
            self.step.setAccessibleName(title + "步长")
        settings.addStretch()
        row.addLayout(settings)
        row.addStretch()

    @staticmethod
    def add_setting(layout, title, control):
        caption = QtWidgets.QLabel(title)
        caption.setBuddy(control)
        control.setAccessibleName(title)
        layout.addWidget(caption)
        layout.addWidget(control)

    def move_one_step(self, direction):
        distance = self.step.currentData() if isinstance(self.step, QtWidgets.QComboBox) else self.step.value()
        self.moved.emit(direction[0] * distance, direction[1] * distance)

    def show_motion_settings(self, feed, *, can_move, can_edit):
        self.setEnabled(can_move or can_edit)
        for button in self.buttons.values():
            button.setEnabled(can_move)
        self.step.setEnabled(can_move)
        self.feed.setEnabled(can_edit)
        with QtCore.QSignalBlocker(self.feed):
            if self.feed.count() > len(FEED_PRESETS) and self.feed.itemData(len(FEED_PRESETS)) != feed:
                self.feed.removeItem(len(FEED_PRESETS))
            index = self.feed.findData(feed)
            if index < 0:
                self.feed.addItem(f"{feed} mm/min（当前值）", feed)
                index = self.feed.count() - 1
            self.feed.setCurrentIndex(index)
