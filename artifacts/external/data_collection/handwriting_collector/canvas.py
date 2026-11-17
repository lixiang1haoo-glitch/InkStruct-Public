from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QEventPoint, QPainter, QPen, QPixmap, QTabletEvent
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from .models import INPUT_MODES, UNMEASURED_PRESSURE, Trajectory, TrajectoryPoint


class TrajectoryCanvas(QWidget):
    """Record one selected input source with incremental ink."""

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
        self._input_mode = "tablet"
        self._touch_id = None
        self.allow_pointer_dot = False
        self._timer = QElapsedTimer()
        self._clock_started = False
        self._render_cache = None
        self._render_key = None
        self._drawn_strokes = []
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(360, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        QApplication.instance().applicationStateChanged.connect(self._application_state_changed)

    def set_input_mode(self, mode: str) -> None:
        if mode not in INPUT_MODES:
            raise ValueError("不支持的录制输入")
        if mode != self._input_mode:
            if self.trajectory.strokes:
                raise ValueError("请先保存或放弃当前笔迹")
            self._input_mode = mode
            self._touch_id = None
            self.setMouseTracking(mode == "mouse")

    def _application_state_changed(self, state) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            self.cancel_active_stroke()

    def set_render_settings(self, stroke_width_scale: float, grid_scale: float) -> None:
        self.stroke_width_scale = float(stroke_width_scale)
        self.grid_scale = float(grid_scale)
        self.update()

    def tabletEvent(self, event: QTabletEvent) -> None:
        event.accept()
        if self._input_mode != "tablet":
            return
        event_type = event.type()
        pressure = float(event.pressure())
        position = event.position()
        if event_type == QEvent.Type.TabletPress and pressure > self.pen_threshold:
            self._start_stroke(position, pressure)
        elif (
            event_type == QEvent.Type.TabletMove
            and self._pen_down
            and pressure > self.pen_threshold
        ):
            self._append_ink(self._point(position, pressure))
        elif event_type == QEvent.Type.TabletRelease:
            self.finish_stroke(position, pressure)

    def event(self, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate,
                    QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            # Accept all touch input on the canvas so Qt won't synthesize a
            # mouse stroke in a different input mode.
            event.accept()
            if self._input_mode == "finger":
                self._touch_event(event)
            return True
        if kind in (QEvent.Type.FocusOut, QEvent.Type.WindowDeactivate,
                    QEvent.Type.Hide, QEvent.Type.UngrabMouse) or (
                    kind == QEvent.Type.EnabledChange and not self.isEnabled()):
            self.cancel_active_stroke()
        return super().event(event)

    def _touch_event(self, event) -> None:
        kind = event.type()
        if kind == QEvent.Type.TouchCancel:
            self.cancel_active_stroke()
            return
        points = event.points()
        if kind == QEvent.Type.TouchBegin:
            primary = next((point for point in points
                            if point.state() == QEventPoint.State.Pressed), None)
            if primary is not None and self._start_stroke(primary.position(), UNMEASURED_PRESSURE):
                self._touch_id = primary.id()
            return
        for point in points:
            if point.id() != self._touch_id:
                continue
            if point.state() == QEventPoint.State.Released:
                self.finish_stroke(point.position(), UNMEASURED_PRESSURE)
                self._touch_id = None
            elif point.state() == QEventPoint.State.Updated and self._pen_down:
                self._append_pointer_ink(point.position())
            break
        if kind == QEvent.Type.TouchEnd:
            self.cancel_active_stroke()

    def mousePressEvent(self, event) -> None:
        event.accept()
        if (self._input_mode == "mouse" and event.button() == Qt.MouseButton.LeftButton
                and event.source() != Qt.MouseEventSource.MouseEventSynthesizedByQt):
            self.cancel_active_stroke()
            self._start_stroke(event.position(), UNMEASURED_PRESSURE)

    def mouseDoubleClickEvent(self, event) -> None:
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        event.accept()
        if self._input_mode == "mouse" and self._pen_down:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._append_pointer_ink(event.position())
            else:
                self.cancel_active_stroke()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
        if self._input_mode == "mouse" and event.button() == Qt.MouseButton.LeftButton:
            self.finish_stroke(event.position(), UNMEASURED_PRESSURE)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._pen_down:
            self.cancel_active_stroke()
            event.accept()
            return
        super().keyPressEvent(event)

    def _start_stroke(self, position: QPointF, pressure: float) -> bool:
        if self._pen_down or not QRectF(self.rect()).contains(position):
            return False
        if not self._clock_started:
            self._timer.start()
            self._clock_started = True
        self._pen_down = True
        self.trajectory.input_type = self._input_mode
        point = self._point(position, pressure)
        self.trajectory.start_stroke(point)
        self._update_ink(point, point)
        self.trajectory_changed.emit()
        return True

    def _append_pointer_ink(self, position: QPointF) -> None:
        self._append_if_moved(self._point(position, UNMEASURED_PRESSURE))

    def _append_if_moved(self, point: TrajectoryPoint) -> bool:
        previous = self.trajectory.strokes[-1].points[-1]
        if math.hypot(point.x - previous.x, point.y - previous.y) < self.release_distance_threshold:
            return False
        self._append_ink(point)
        return True

    def cancel_active_stroke(self) -> None:
        self._touch_id = None
        if self._pen_down:
            self._pen_down = False
            self.undo_last_stroke()

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
            appended = self._append_if_moved(self._point(position, pressure))
            if (self._input_mode != "tablet" and not self.allow_pointer_dot
                    and len(self.trajectory.strokes[-1].points) == 1):
                self.cancel_active_stroke()
                return False
        self._pen_down = False
        if was_active:
            self.trajectory_changed.emit()
        return appended

    def undo_last_stroke(self) -> None:
        if self._pen_down:
            self.cancel_active_stroke()
            return
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
        self._touch_id = None
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
