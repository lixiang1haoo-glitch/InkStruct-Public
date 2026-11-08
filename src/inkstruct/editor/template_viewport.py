"""View-only zoom, scrolling and physical-paper rulers for template authoring."""

import math

from PySide6 import QtCore, QtGui, QtSvgWidgets, QtWidgets


class FitSvgPreview(QtSvgWidgets.QSvgWidget):
    """Paper size determines aspect ratio; the surrounding view determines scale."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)

    def sizeHint(self):
        return QtCore.QSize(320, 240)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 0)

    def show_svg(self, svg):
        self.load(svg)
        self.renderer().setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self.update()
        return self.renderer().isValid()

    def clear(self):
        self.load(QtCore.QByteArray())
        self.update()


class TemplateRuler(QtWidgets.QWidget):
    def __init__(self, view, axis):
        super().__init__(view)
        self.view, self.axis = view, axis
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

    def tick_positions(self):
        canvas = self.view.canvas
        if canvas.template is None:
            return ()
        rect = canvas.paper_rect()
        origin = canvas.mapTo(self.view.viewport(), QtCore.QPoint(0, 0))
        size = canvas.template.width_mm if self.axis == 0 else canvas.template.height_mm
        pixels = rect.width() if self.axis == 0 else rect.height()
        scale = pixels / size
        if not math.isfinite(scale) or scale <= 0:
            return ()
        offset = origin.x() + rect.x() if self.axis == 0 else origin.y() + rect.y()
        visible = self.width() if self.axis == 0 else self.height()
        target = 38 / scale
        power = 10 ** math.floor(math.log10(target))
        major = next(v * power for v in (1, 2, 5, 10) if v * power >= target)
        minor = major / 5
        lo = max(0, math.ceil(-offset / scale / minor))
        hi = min(math.floor(size / minor), math.floor((visible - offset) / scale / minor))
        return tuple((i * minor, offset + i * minor * scale, i % 5 == 0) for i in range(lo, hi + 1))

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#f1f5f9"))
        painter.setPen(QtGui.QColor("#475569"))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for value, pixel, major in self.tick_positions():
            pixel = round(pixel)
            length = 7 if major else 3
            if self.axis == 0:
                painter.drawLine(pixel, self.height() - 1, pixel, self.height() - length)
                if major:
                    label = f"{value:g}"
                    label_width = metrics.horizontalAdvance(label)
                    x = max(0, min(self.width() - label_width, pixel - label_width // 2))
                    painter.drawText(x, self.height() - 9, label)
            else:
                painter.drawLine(self.width() - 1, pixel, self.width() - length, pixel)
                if major:
                    baseline = max(
                        metrics.ascent(),
                        min(self.height() - metrics.descent(), pixel + metrics.ascent() // 2),
                    )
                    painter.drawText(2, baseline, f"{value:g}")
        painter.end()


class TemplateViewport(QtWidgets.QScrollArea):
    zoom_changed = QtCore.Signal(float)

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.zoom = 1.0
        self.rulers_visible = True
        self._resizing = False
        self._panning = None
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setWidgetResizable(False)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setWidget(canvas)
        self.setMinimumSize(180, 180)
        self.rulers = (TemplateRuler(self, 0), TemplateRuler(self, 1))
        self.corner = QtWidgets.QLabel("mm", self)
        self.corner.setAlignment(QtCore.Qt.AlignCenter)
        self.corner.setStyleSheet("background: #f1f5f9; color: #475569;")
        self.setViewportMargins(38, 24, 0, 0)
        for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            bar.valueChanged.connect(self.refresh_rulers)
        canvas.installEventFilter(self)
        self.viewport().installEventFilter(self)
        canvas.view_changed.connect(self.resize_canvas)

    def refresh_rulers(self):
        rect = self.viewport().geometry()
        self.rulers[0].setGeometry(rect.x(), 0, rect.width(), 24)
        self.rulers[1].setGeometry(0, rect.y(), 38, rect.height())
        self.corner.setGeometry(0, 0, 38, 24)
        for ruler in self.rulers:
            ruler.setVisible(self.rulers_visible)
            ruler.update()
        self.corner.setVisible(self.rulers_visible)

    def resize_canvas(self):
        if self._resizing:
            return
        self._resizing = True
        try:
            available = self.maximumViewportSize()
            width, height = available.width(), available.height()
            if self.canvas.template is not None:
                paper = self.canvas.template
                scale = min(width / paper.width_mm, height / paper.height_mm)
                width, height = paper.width_mm * scale, paper.height_mm * scale
            self.canvas.resize(
                max(1, round(width * self.zoom)),
                max(1, round(height * self.zoom)),
            )
            self.refresh_rulers()
        finally:
            self._resizing = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "rulers"):
            self.canvas.cancel_gesture()
            self.resize_canvas()

    def set_zoom(self, value, anchor=None):
        value = float(value)
        if not math.isfinite(value):
            return
        value = max(0.5, min(6.0, value))
        self.canvas.cancel_gesture()
        self._panning = None
        self.canvas.unsetCursor()
        anchor = anchor or QtCore.QPoint(
            self.viewport().width() // 2, self.viewport().height() // 2
        )
        previous = self.canvas.mapFrom(self.viewport(), anchor)
        point = self.canvas.to_mm(previous) if self.canvas.template else None
        self.zoom = value
        self.resize_canvas()
        if point is not None:
            current = self.canvas.to_widget(point)
            origin = self.canvas.mapTo(self.viewport(), QtCore.QPoint(0, 0))
            self.horizontalScrollBar().setValue(
                round(self.horizontalScrollBar().value() + origin.x() + current.x() - anchor.x())
            )
            self.verticalScrollBar().setValue(
                round(self.verticalScrollBar().value() + origin.y() + current.y() - anchor.y())
            )
        self.refresh_rulers()
        self.zoom_changed.emit(value)

    def fit_page(self):
        self.set_zoom(1.0)
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def show_rulers(self, visible):
        self.rulers_visible = bool(visible)
        self.setViewportMargins(38 if visible else 0, 24 if visible else 0, 0, 0)
        self.resize_canvas()

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Wheel and event.modifiers() & (
            QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier
        ):
            delta = event.angleDelta().y()
            if delta:
                anchor = watched.mapTo(self.viewport(), event.position().toPoint())
                self.set_zoom(self.zoom * (1.2 if delta > 0 else 1 / 1.2), anchor)
            event.accept()
            return True
        if (
            event.type() == QtCore.QEvent.MouseButtonPress
            and event.button() == QtCore.Qt.MiddleButton
        ):
            self.canvas.cancel_gesture()
            self.canvas.setFocus()
            self._panning = (
                event.globalPosition(),
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
            self.canvas.setCursor(QtCore.Qt.ClosedHandCursor)
            return True
        if event.type() == QtCore.QEvent.MouseMove and self._panning:
            start, x, y = self._panning
            delta = event.globalPosition() - start
            self.horizontalScrollBar().setValue(round(x - delta.x()))
            self.verticalScrollBar().setValue(round(y - delta.y()))
            return True
        if (
            event.type() == QtCore.QEvent.MouseButtonRelease
            and event.button() == QtCore.Qt.MiddleButton
        ):
            self._panning = None
            self.canvas.unsetCursor()
            return True
        if (
            event.type() == QtCore.QEvent.KeyPress
            and event.key() == QtCore.Qt.Key_Escape
            and self._panning
        ):
            _, x, y = self._panning
            self.horizontalScrollBar().setValue(x)
            self.verticalScrollBar().setValue(y)
            self._panning = None
            self.canvas.unsetCursor()
            return True
        return super().eventFilter(watched, event)
