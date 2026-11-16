"""Capture-space drawings and the shared view for the sample library."""

import math

from PySide6 import QtCore, QtGui, QtWidgets

from .sample_library import metadata
from .symbol_capture import FRAME


Qt = QtCore.Qt


def guide_numbers(record, *names):
    try:
        values = tuple(float(record[name]) for name in names)
    except (KeyError, TypeError, ValueError, OverflowError):
        return ()
    return values if all(map(math.isfinite, values)) else ()


def symbol_frame(guides):
    em, x, y = (guides[key] for key in ('em_px', 'origin_x_px', 'baseline_y_px'))
    return QtCore.QRectF(-x / em, -y / em, guides['canvas_width'] / em, guides['canvas_height'] / em)


def fit_scale(bounds, size, margin):
    return min(max(1, size.width() - 2 * margin) / bounds.width(),
               max(1, size.height() - 2 * margin) / bounds.height())


def centered_transform(scale, target, source):
    return QtGui.QTransform(scale, 0, 0, scale, target.x() - scale * source.x(), target.y() - scale * source.y())


class SampleDrawing:
    def __init__(self, value):
        capture = metadata(value, 'capture')
        guides = metadata(value, 'guides')
        calibration = guide_numbers(guides, 'em_px', 'origin_x_px', 'baseline_y_px')
        canvas = guide_numbers(capture, 'canvas_width', 'canvas_height')
        self.calibrated = bool(calibration and calibration[0] > 0)
        self.canvas_only = not self.calibrated and bool(canvas and min(canvas) > 0)
        self.missing_scale = not (self.calibrated or self.canvas_only)
        strokes = [s['points'] for s in value['strokes'] if s['points']]
        if self.calibrated:
            unit, x, y = calibration
            self.bounds = symbol_frame(FRAME)
            dimensions = guide_numbers(guides, 'canvas_width', 'canvas_height') or canvas
            if dimensions and min(dimensions) > 0:
                recorded = (-x / unit, -y / unit, *(v / unit for v in dimensions))
                if all(map(math.isfinite, recorded)):
                    self.bounds = self.bounds.united(QtCore.QRectF(*recorded))
        elif self.canvas_only:
            w, h = canvas
            unit, x, y = min(w, h), w / 2, h / 2
            self.bounds = QtCore.QRectF(-x / unit, -y / unit, w / unit, h / unit)
        else:
            points = [p for stroke in strokes for p in stroke]
            xs = [float(p['x']) for p in points] or [0]
            ys = [float(p['y']) for p in points] or [0]
            unit = 160
            x, y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            w, h = max(1, (max(xs) - min(xs)) / unit), max(1, (max(ys) - min(ys)) / unit)
            self.bounds = QtCore.QRectF(-w / 2, -h / 2, w, h)

        self.ink = QtGui.QPainterPath()
        self.dots = QtGui.QPolygonF()
        for stroke in strokes:
            path = QtGui.QPainterPath()
            first = stroke[0]
            start = QtCore.QPointF((float(first['x']) - x) / unit, (float(first['y']) - y) / unit)
            path.moveTo(start)
            for point in stroke[1:]:
                path.lineTo((float(point['x']) - x) / unit, (float(point['y']) - y) / unit)
            if path.isEmpty():
                self.dots.append(start)
            else:
                self.ink.addPath(path)

    def paint(self, painter, transform, palette, *, guides=False, width=2.2):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        ink = palette.text().color()
        if guides and not self.missing_scale:
            guide = QtGui.QColor(ink)
            guide.setAlpha(85)
            painter.setPen(QtGui.QPen(guide, 1))
            painter.drawRect(transform.mapRect(self.bounds))
            if self.calibrated:
                cap = FRAME['cap_height_em']
                descender = FRAME['descender_em']
                painter.drawRect(transform.mapRect(QtCore.QRectF(0, -cap, 1, cap + descender)))
                baseline = palette.link().color()
                baseline.setAlpha(175)
                painter.setPen(QtGui.QPen(baseline, 1))
                painter.drawLine(transform.map(QtCore.QLineF(self.bounds.left(), 0, self.bounds.right(), 0)))
            else:
                painter.drawLine(transform.map(QtCore.QLineF(self.bounds.left(), 0, self.bounds.right(), 0)))
                painter.drawLine(transform.map(QtCore.QLineF(0, self.bounds.top(), 0, self.bounds.bottom())))
        painter.setPen(QtGui.QPen(ink, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(transform.map(self.ink))
        if self.dots:
            painter.drawPoints(transform.map(self.dots))

    def paint_thumbnail(self, painter, rect, palette):
        scale = fit_scale(self.bounds, rect.size(), 3)
        self.paint(painter, centered_transform(scale, rect.center(), self.bounds.center()), palette, width=1.5)


class SampleView(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bounds = QtCore.QRectF(-0.5, -0.5, 1, 1)
        self.center = self.bounds.center()
        self.zoom = 1.0

    def frame(self, drawings, *, reset):
        if drawings:
            bounds = QtCore.QRectF(drawings[0].bounds)
            for drawing in drawings[1:]:
                bounds = bounds.united(drawing.bounds)
            changed = self.bounds != bounds
            self.bounds = bounds
            if changed and self.zoom == 1:
                reset = True
        if reset:
            self.reset()

    def reset(self):
        self.zoom = 1.0
        self.center = self.bounds.center()
        self.changed.emit()

    def scale(self, size, margin):
        return self.zoom * fit_scale(self.bounds, size, margin)

    def transform(self, rect, margin):
        return centered_transform(self.scale(rect.size(), margin), rect.center(), self.center)

    def zoom_at(self, rect, margin, position, steps):
        zoom = max(.5, min(8., self.zoom * 1.2 ** max(-20, min(20, steps))))
        if zoom != self.zoom:
            offset = position - rect.center()
            anchor = self.center + offset / self.scale(rect.size(), margin)
            self.zoom = zoom
            self.center = anchor - offset / self.scale(rect.size(), margin)
            self.changed.emit()

    def pan(self, delta, rect, margin):
        self.center -= delta / self.scale(rect.size(), margin)
        self.changed.emit()


class SamplePreview(QtWidgets.QWidget):
    margin = 14

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.value = self.drawing = self.drag_position = None
        self.guides = False
        self.setToolTip('Ctrl + 滚轮缩放 · 放大后拖动')
        self.view.changed.connect(self.view_changed)

    def set_sample(self, value):
        if self.value is not value:
            self.value = value
            self.drawing = SampleDrawing(value) if value is not None else None
        self.drag_position = None
        self.view_changed()

    def view_changed(self):
        if self.drawing is None or self.view.zoom <= 1:
            self.drag_position = None
            self.unsetCursor()
        else:
            self.setCursor(Qt.ClosedHandCursor if self.drag_position is not None else Qt.OpenHandCursor)
        self.update()

    def drawing_transform(self):
        return self.view.transform(QtCore.QRectF(self.rect()), self.margin)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        if self.drawing is not None:
            self.drawing.paint(painter, self.drawing_transform(), palette, guides=self.guides)

    def wheelEvent(self, event):
        if not self.drawing or not (event.modifiers() & Qt.ControlModifier):
            event.ignore()
            return
        steps = event.pixelDelta().y() / 80 or event.angleDelta().y() / 120
        if steps:
            self.view.zoom_at(QtCore.QRectF(self.rect()), self.margin, event.position(), steps)
        event.accept()

    def mousePressEvent(self, event):
        if self.drawing is not None and self.view.zoom > 1 and event.button() == Qt.LeftButton:
            self.drag_position = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_position is not None and event.buttons() & Qt.LeftButton:
            delta = event.position() - self.drag_position
            self.drag_position = event.position()
            self.view.pan(delta, QtCore.QRectF(self.rect()), self.margin)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag_position is not None and event.button() == Qt.LeftButton:
            self.drag_position = None
            self.view_changed()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
