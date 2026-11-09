from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTabletEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from .models import Trajectory, TrajectoryPoint


class TrajectoryCanvas(QWidget):
    """Tablet-only trajectory canvas shared by single and line modes."""

    trajectory_changed = Signal()

    def __init__(
        self,
        *,
        show_grid: bool = False,
        stroke_width_scale: float = 2.0,
        grid_scale: float = 0.72,
        parent=None,
    ):
        super().__init__(parent)
        self.trajectory = Trajectory()
        self.show_grid = show_grid
        self.stroke_width_scale = stroke_width_scale
        self.grid_scale = grid_scale
        self.char_ends: list[int] = []
        self.pen_threshold = 0.01
        self.release_distance_threshold = 0.5
        self._pen_down = False
        self._timer = QElapsedTimer()
        self._clock_started = False
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "TrajectoryCanvas { background: white; border: 1px solid #CBD5E1; }"
        )
        self.setMinimumSize(360, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_render_settings(self, stroke_width_scale: float, grid_scale: float) -> None:
        self.stroke_width_scale = float(stroke_width_scale)
        self.grid_scale = float(grid_scale)
        self.update()

    def tabletEvent(self, event: QTabletEvent) -> None:
        event_type = event.type()
        pressure = float(event.pressure())
        position = event.position()
        if event_type == QEvent.Type.TabletPress and pressure > self.pen_threshold:
            if not self._clock_started:
                self._timer.start()
                self._clock_started = True
            self._pen_down = True
            self.trajectory.start_stroke(self._point(position, pressure))
            self.trajectory_changed.emit()
            self.update()
        elif (
            event_type == QEvent.Type.TabletMove
            and self._pen_down
            and pressure > self.pen_threshold
        ):
            self.trajectory.append_point(self._point(position, pressure))
            self.trajectory_changed.emit()
            self.update()
        elif event_type == QEvent.Type.TabletRelease:
            self.finish_stroke(position, pressure)
        event.accept()

    def _point(self, position: QPointF, pressure: float) -> TrajectoryPoint:
        return TrajectoryPoint(
            x=min(max(float(position.x()), 0.0), float(self.width())),
            y=min(max(float(position.y()), 0.0), float(self.height())),
            pressure=min(max(pressure, 0.0), 1.0),
            t_ms=self._timer.elapsed(),
        )

    def finish_stroke(self, position: QPointF, pressure: float = 0.0) -> bool:
        """Finish an active stroke and preserve a distinct release position."""
        was_active = self._pen_down
        appended = False
        if self._pen_down and self.trajectory.strokes:
            release_point = self._point(position, pressure)
            previous = self.trajectory.strokes[-1].points[-1]
            distance = math.hypot(
                release_point.x - previous.x, release_point.y - previous.y
            )
            if distance >= self.release_distance_threshold:
                self.trajectory.append_point(release_point)
                appended = True
        self._pen_down = False
        if was_active:
            self.trajectory_changed.emit()
            self.update()
        return appended

    def undo_last_stroke(self) -> None:
        old_count = self.trajectory.point_count
        if self.trajectory.undo_last_stroke():
            self.char_ends = [end for end in self.char_ends if end <= self.trajectory.point_count]
            if old_count != self.trajectory.point_count:
                self.trajectory_changed.emit()
                self.update()

    def clear(self) -> None:
        self.trajectory.clear()
        self.char_ends.clear()
        self._pen_down = False
        self._clock_started = False
        self.trajectory_changed.emit()
        self.update()

    @property
    def pen_down(self) -> bool:
        return self._pen_down

    def mark_char_end(self) -> bool:
        if self._pen_down:
            return False
        count = self.trajectory.point_count
        if count and (not self.char_ends or self.char_ends[-1] != count):
            self.char_ends.append(count)
            self.trajectory_changed.emit()
            self.update()
            return True
        return False

    def undo_char_end(self) -> bool:
        if not self.char_ends:
            return False
        self.char_ends.pop()
        self.trajectory_changed.emit()
        self.update()
        return True

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        if self.show_grid:
            self._draw_grid(painter)
        for stroke in self.trajectory.strokes:
            self._draw_stroke(painter, stroke.points)
        if self.char_ends:
            painter.setPen(QPen(QColor("#16A34A"), 3.0))
            flat_points = list(self.trajectory.iter_points())
            for end in self.char_ends:
                if 1 <= end <= len(flat_points):
                    point = flat_points[end - 1]
                    painter.drawEllipse(QPointF(point.x, point.y), 5.0, 5.0)

    def _draw_grid(self, painter: QPainter) -> None:
        side = min(self.width(), self.height()) * self.grid_scale
        left = (self.width() - side) / 2
        top = (self.height() - side) / 2
        box = QRectF(left, top, side, side)
        painter.setPen(QPen(QColor("#CBD5E1"), 1.2))
        painter.drawRect(box)
        dashed = QPen(QColor("#E2E8F0"), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(dashed)
        painter.drawLine(QPointF(left + side / 2, top), QPointF(left + side / 2, top + side))
        painter.drawLine(QPointF(left, top + side / 2), QPointF(left + side, top + side / 2))
        painter.drawLine(QPointF(left, top), QPointF(left + side, top + side))
        painter.drawLine(QPointF(left + side, top), QPointF(left, top + side))

    def _draw_stroke(self, painter: QPainter, points: list[TrajectoryPoint]) -> None:
        if not points:
            return
        if len(points) == 1:
            point = points[0]
            width = max(1.2, (1.0 + point.pressure * 4.0) * self.stroke_width_scale)
            painter.setPen(
                QPen(
                    QColor("#111827"),
                    width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPoint(QPointF(point.x, point.y))
            return
        for first, second in zip(points, points[1:]):
            width = max(
                1.2,
                (1.0 + (first.pressure + second.pressure) * 2.0)
                * self.stroke_width_scale,
            )
            painter.setPen(
                QPen(
                    QColor("#111827"),
                    width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawLine(QPointF(first.x, first.y), QPointF(second.x, second.y))
