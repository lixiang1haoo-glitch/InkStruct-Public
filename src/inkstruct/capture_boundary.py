"""Shared, non-destructive edge guidance for both collector entry points."""

from __future__ import annotations

import math
from collections.abc import Iterable


def capture_edge_status(
    points: Iterable[tuple[float, float]], width: float, height: float
) -> str:
    """Coordinates and canvas dimensions are logical pixels, not device pixels."""
    if not math.isfinite(width) or not math.isfinite(height) or min(width, height) <= 0:
        return "unavailable"
    status = "clear"
    for x, y in points:
        if not math.isfinite(x) or not math.isfinite(y):
            return "invalid"
        if x <= 1 or y <= 1 or x >= width - 1 or y >= height - 1:
            status = "edge"
        elif status == "clear" and min(x / width, y / height, 1 - x / width, 1 - y / height) < 0.075:
            status = "near"
    return status


def install_capture_boundary_guard(owner, QtCore, QtGui, QtWidgets):
    """Attach to the existing canvas without changing its input or stored data."""
    canvas = owner.canvas

    class Guide(QtWidgets.QWidget):
        def __init__(self):
            super().__init__(canvas)
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
            self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        def paintEvent(self, event):
            painter = QtGui.QPainter(self)
            pen = QtGui.QPen(QtGui.QColor(120, 140, 150, 110))
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(QtCore.QRectF(
                self.width() * 0.075, self.height() * 0.075,
                self.width() * 0.85, self.height() * 0.85,
            ))
            painter.end()

    class Guard(QtCore.QObject):
        def __init__(self):
            super().__init__(owner)
            self.guide = Guide()
            self.label = QtWidgets.QLabel(owner)
            self.label.setWordWrap(True)
            owner.layout().addWidget(self.label)
            canvas.installEventFilter(self)
            canvas.trajectory_changed.connect(self.refresh)
            self.refresh()

        def status(self):
            return capture_edge_status(
                ((p.x, p.y) for stroke in canvas.trajectory.strokes for p in stroke.points),
                canvas.width(), canvas.height(),
            )

        def eventFilter(self, watched, event):
            if event.type() in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show):
                self.refresh()
            return False

        def refresh(self):
            self.guide.setGeometry(canvas.rect())
            self.guide.raise_()
            self.guide.show()
            state = self.status()
            messages = {
                "clear": "建议写在虚线框内，四周留白；参考框不限制书写。",
                "near": "笔迹接近画布边缘，建议留出空白，避免末端写出画布。",
                "edge": "笔迹触及画布边缘，可能有末端未采集，请检查后保存或重写。",
                "invalid": "笔迹含无效坐标，请重写当前字。",
                "unavailable": "画布尺寸暂不可用，请调整窗口后重试。",
            }
            self.label.setText(messages[state])
            self.label.setStyleSheet("color: #B45309;" if state != "clear" else "color: #64748B;")

        def allow_save(self):
            state = self.status()
            if state in {"invalid", "unavailable"}:
                QtWidgets.QMessageBox.warning(owner, "无法检查笔迹", self.label.text())
                return False
            if state != "edge":
                return True
            choice = QtWidgets.QMessageBox.question(
                owner, "检查边缘笔迹",
                "当前笔迹触及画布边缘，末端可能未完整采集。\n"
                "确认笔画完整并继续保存？选择“否”可返回检查或重写。",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            return choice == QtWidgets.QMessageBox.StandardButton.Yes

    return Guard()
