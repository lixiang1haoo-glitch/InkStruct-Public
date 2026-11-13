from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTabletEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from .models import Trajectory, TrajectoryPoint


class TrajectoryCanvas(QWidget):
    """Tablet-only trajectory canvas with incremental, pressure-sensitive ink."""

    # UI state changes at pen-down/up, undo and clear. Motion only affects the ink.
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
        self._render_cache = None
        self._render_key = None
        self._drawn_strokes = []
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
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
            point = self._point(position, pressure)
            self.trajectory.start_stroke(point)
            self.trajectory_changed.emit()
            self._update_ink(point, point)
        elif (
            event_type == QEvent.Type.TabletMove
            and self._pen_down
            and pressure > self.pen_threshold
        ):
            self._append_ink(self._point(position, pressure))
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

    def _update_ink(self, first: TrajectoryPoint, second: TrajectoryPoint) -> None:
        radius = max(self._ink_width(first.pressure), self._ink_width(second.pressure)) / 2 + 2
        dirty = QRectF(QPointF(first.x, first.y), QPointF(second.x, second.y)).normalized()
        self.update(dirty.adjusted(-radius, -radius, radius, radius).toAlignedRect())

    def _append_ink(self, point: TrajectoryPoint) -> None:
        if not self.trajectory.strokes:
            self.trajectory.start_stroke(point)
            self.trajectory_changed.emit()
            self._update_ink(point, point)
            return
        previous = self.trajectory.strokes[-1].points[-1]
        self.trajectory.append_point(point)
        self._update_ink(previous, point)

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
                self._append_ink(release_point)
                appended = True
        self._pen_down = False
        if was_active:
            self.trajectory_changed.emit()
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
        palette = self.palette()
        dpr = self.devicePixelRatioF()
        key = (self.size(), dpr, palette.cacheKey(), self.font().key(),
               self.show_grid, self.grid_scale, self.stroke_width_scale)
        strokes = self.trajectory.strokes
        old = self._drawn_strokes
        # Stroke edits and a change in the render surface require replay. Normal
        # tablet motion only extends the current stroke's already painted prefix.
        rebuild = key != self._render_key or len(old) > len(strokes) or any(
            stroke is not saved or len(stroke.points) < count
            or (count and stroke.points[count - 1] is not last)
            for stroke, (saved, count, last) in zip(strokes, old)
        )
        if rebuild:
            self._render_cache = QPixmap(math.ceil(self.width() * dpr), math.ceil(self.height() * dpr))
            self._render_cache.setDevicePixelRatio(dpr)
            self._render_cache.fill(palette.base().color())
            self._render_key = key
            old = []

        ink = palette.text().color()
        if rebuild or len(old) != len(strokes) or any(
            len(stroke.points) != count for stroke, (_, count, _) in zip(strokes, old)
        ):
            cache_painter = QPainter(self._render_cache)
            cache_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if rebuild:
                cache_painter.setFont(self.font())
                cache_painter.setPen(palette.mid().color())
                cache_painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
                if self.show_grid:
                    self._draw_grid(cache_painter)
            pen = self._ink_pen(ink)
            for i, stroke in enumerate(strokes):
                start = max(1, old[i][1]) if i < len(old) else 1
                points = stroke.points
                for j in range(start, len(points)):
                    first, second = points[j - 1], points[j]
                    pen.setWidthF(self._ink_width((first.pressure + second.pressure) / 2))
                    cache_painter.setPen(pen)
                    cache_painter.drawLine(QPointF(first.x, first.y), QPointF(second.x, second.y))
            cache_painter.end()
            self._drawn_strokes = [(stroke, len(stroke.points), stroke.points[-1] if stroke.points else None)
                                   for stroke in strokes]

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._render_cache)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = self._ink_pen(ink)
        # Keep single-point strokes out of the cache so the first segment can
        # replace the temporary dot without retaining its different width.
        for stroke in strokes:
            if len(stroke.points) == 1:
                point = stroke.points[0]
                pen.setWidthF(self._ink_width(point.pressure))
                painter.setPen(pen)
                painter.drawPoint(QPointF(point.x, point.y))
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
        dark = self.palette().base().color().lightness() < 128
        painter.setPen(QPen(QColor("#69727F" if dark else "#CBD5E1"), 1.2))
        painter.drawRect(box)
        dashed = QPen(QColor("#505965" if dark else "#E2E8F0"), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(dashed)
        painter.drawLine(QPointF(left + side / 2, top), QPointF(left + side / 2, top + side))
        painter.drawLine(QPointF(left, top + side / 2), QPointF(left + side, top + side / 2))
        painter.drawLine(QPointF(left, top), QPointF(left + side, top + side))
        painter.drawLine(QPointF(left + side, top), QPointF(left, top + side))

    def _ink_width(self, pressure: float) -> float:
        return max(1.2, (1.0 + pressure * 4.0) * self.stroke_width_scale)

    @staticmethod
    def _ink_pen(ink: QColor) -> QPen:
        return QPen(ink, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
