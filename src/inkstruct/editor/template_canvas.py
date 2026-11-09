"""Interactive overlay on the exact same millimetre template reference SVG."""

import math

from PySide6 import QtCore, QtGui, QtSvgWidgets, QtWidgets

from ..document.template import Anchor, Region, TemplateRule
from ..document.template_authoring import geometry_preview
from .template_geometry import (
    add_element,
    edit_element,
    element_at,
    element_bounds,
    element_items,
    move_element,
    move_selection,
    move_vertex,
    resize_region,
)


class TemplateCanvas(QtSvgWidgets.QSvgWidget):
    selected = QtCore.Signal(object)
    selection_changed = QtCore.Signal(object)
    committed = QtCore.Signal(object, object)
    status = QtCore.Signal(str)
    view_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.template = None
        self.face_name = "first"
        self.selection = None
        self.selections = ()
        self.tool = "select"
        self.grid_mm = 1.0
        self.snap = True
        self.grid_visible = True
        self.link_body_width = True
        self.background_opacity = 0.4
        self._gesture = None
        self._candidate = None
        self._candidate_key = None
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)

    def set_template(self, template, face_name):
        self.cancel_gesture()
        self.selection = None
        self.selections = ()
        self.template, self.face_name = template, face_name
        self.load(
            geometry_preview(
                template, face_name, background_opacity=self.background_opacity
            ).encode("utf-8")
        )
        self.renderer().setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self.update()
        self.view_changed.emit()

    def set_background_opacity(self, value):
        self.cancel_gesture()
        self.background_opacity = value
        if self.template is not None:
            self.load(
                geometry_preview(self.template, self.face_name, background_opacity=value).encode(
                    "utf-8"
                )
            )
            self.renderer().setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self.update()

    def set_selection(self, key):
        self.set_selections((key,) if key is not None else ())

    def set_selections(self, keys, *, notify=False):
        self.selections = tuple(dict.fromkeys(keys))
        self.selection = self.selections[-1] if self.selections else None
        if notify:
            self.selected.emit(self.selection)
        self.selection_changed.emit(self.selections)
        self.update()

    def paper_rect(self):
        if self.template is None:
            return QtCore.QRectF()
        scale = min(self.width() / self.template.width_mm, self.height() / self.template.height_mm)
        w, h = self.template.width_mm * scale, self.template.height_mm * scale
        return QtCore.QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def to_widget(self, point):
        rect = self.paper_rect()
        scale = rect.width() / self.template.width_mm
        return QtCore.QPointF(
            rect.x() + (point[0] + self.template.offset_x_mm) * scale,
            rect.y() + (point[1] + self.template.offset_y_mm) * scale,
        )

    def to_mm(self, point):
        rect = self.paper_rect()
        scale = rect.width() / self.template.width_mm
        return (
            (point.x() - rect.x()) / scale - self.template.offset_x_mm,
            (point.y() - rect.y()) / scale - self.template.offset_y_mm,
        )

    def handles(self, element):
        if isinstance(element, Region):
            l, t, r, b = element.bounds
            return [("tl", (l, t)), ("tr", (r, t)), ("bl", (l, b)), ("br", (r, b))]
        if isinstance(element, TemplateRule):
            return list(enumerate(element.points))
        return []

    def hit(self, position):
        if self.selection and len(self.selections) == 1:
            item = element_at(self.template, self.face_name, self.selection)
            for handle, point in self.handles(item):
                if (self.to_widget(point) - position).manhattanLength() <= 10:
                    return self.selection, handle
        face = getattr(self.template, self.face_name)
        point = self.to_mm(position)
        tolerance = 6 * self.template.width_mm / self.paper_rect().width()
        for index, item in reversed(list(enumerate(face.anchors))):
            if math.hypot(item.x_mm - point[0], item.y_mm - point[1]) <= tolerance:
                return ("anchors", index), None
        for index, item in reversed(list(enumerate(face.rules))):
            for a, b in zip(item.points, item.points[1:]):
                vx, vy = b[0] - a[0], b[1] - a[1]
                t = max(
                    0,
                    min(
                        1,
                        ((point[0] - a[0]) * vx + (point[1] - a[1]) * vy)
                        / (vx * vx + vy * vy or 1),
                    ),
                )
                if math.hypot(point[0] - a[0] - t * vx, point[1] - a[1] - t * vy) <= tolerance:
                    return ("rules", index), None
        for key, item in [
            *((("reserved", i), r) for i, r in reversed(list(enumerate(face.reserved)))),
            (("body", None), face.body),
        ]:
            l, t, r, b = item.bounds
            if l <= point[0] <= r and t <= point[1] <= b:
                return key, None
        return None, None

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.template is None:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setClipRect(self.paper_rect())
        if self.grid_visible:
            # Keep grid spacing usable and bounded on tiny or huge paper.
            spacing = max(self.grid_mm, 5)
            while spacing * self.paper_rect().width() / self.template.width_mm < 10:
                spacing *= 2
            painter.setPen(QtGui.QPen(QtGui.QColor(140, 150, 170, 45), 1))
            max_x = self.template.width_mm - self.template.offset_x_mm
            max_y = self.template.height_mm - self.template.offset_y_mm
            for axis, end in ((0, max_x), (1, max_y)):
                start = -getattr(self.template, ("offset_x_mm", "offset_y_mm")[axis])
                for i in range(math.ceil(start / spacing), math.floor(end / spacing) + 1):
                    a = (
                        (i * spacing, -self.template.offset_y_mm)
                        if axis == 0
                        else (-self.template.offset_x_mm, i * spacing)
                    )
                    b = (i * spacing, max_y) if axis == 0 else (max_x, i * spacing)
                    painter.drawLine(self.to_widget(a), self.to_widget(b))
        for key in self.selections:
            self.draw_element(
                painter,
                element_at(self.template, self.face_name, key),
                "#1d4ed8",
                handles=len(self.selections) == 1,
            )
        if self._candidate:
            keys = self._gesture["keys"] if self._gesture.get("group") else (self._candidate_key,)
            for key in keys:
                self.draw_element(
                    painter, element_at(self._candidate, self.face_name, key), "#16a34a"
                )
        elif self._gesture and self._gesture.get("end"):
            painter.setPen(QtGui.QPen(QtGui.QColor("#dc2626"), 2, QtCore.Qt.DashLine))
            start, end = (
                self.to_widget(self._gesture["start"]),
                self.to_widget(self._gesture["end"]),
            )
            if self._gesture.get("box"):
                painter.setPen(QtGui.QPen(QtGui.QColor("#2563eb"), 1, QtCore.Qt.DashLine))
                painter.setBrush(QtGui.QColor(37, 99, 235, 25))
                painter.drawRect(QtCore.QRectF(start, end).normalized())
            else:
                painter.drawLine(start, end)
        painter.end()

    def draw_element(self, painter, item, color, handles=False):
        painter.setPen(QtGui.QPen(QtGui.QColor(color), 2, QtCore.Qt.DashLine))
        painter.setBrush(QtCore.Qt.NoBrush)
        if isinstance(item, Region):
            l, t, r, b = item.bounds
            painter.drawRect(QtCore.QRectF(self.to_widget((l, t)), self.to_widget((r, b))))
        elif isinstance(item, Anchor):
            painter.drawEllipse(self.to_widget((item.x_mm, item.y_mm)), 6, 6)
        else:
            painter.drawPolyline(QtGui.QPolygonF([self.to_widget(p) for p in item.points]))
        if handles:
            painter.setBrush(QtGui.QColor("white"))
            for _, point in self.handles(item):
                p = self.to_widget(point)
                painter.drawRect(QtCore.QRectF(p.x() - 4, p.y() - 4, 8, 8))

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or self.template is None:
            return super().mousePressEvent(event)
        if not self.paper_rect().contains(event.position()):
            return
        self.setFocus()
        key, handle = self.hit(event.position()) if self.tool == "select" else (None, None)
        box = self.tool == "marquee" or (self.tool == "select" and key is None)
        additive = bool(event.modifiers() & QtCore.Qt.ShiftModifier)
        if self.tool == "select" and key is not None:
            if additive:
                keys = (
                    tuple(k for k in self.selections if k != key)
                    if key in self.selections
                    else (*self.selections, key)
                )
                self.set_selections(keys, notify=True)
                event.accept()
                return
            if key not in self.selections:
                self.set_selections((key,), notify=True)
        self._gesture = {
            "start": self.to_mm(event.position()),
            "pixel": event.position(),
            "key": key,
            "handle": handle,
            "active": False,
            "keys": self.selections,
            "group": self.tool == "select" and not box and len(self.selections) > 1,
            "box": box,
            "additive": additive,
        }
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._gesture is None:
            return super().mouseMoveEvent(event)
        self.propose(event.position(), event.modifiers())
        event.accept()

    def propose(self, position, modifiers):
        g = self._gesture
        if (
            not g["active"]
            and (position - g["pixel"]).manhattanLength()
            < QtWidgets.QApplication.startDragDistance()
        ):
            return
        g["active"] = True
        g["end"] = self.to_mm(position)
        if g["box"]:
            self.status.emit("框选完全包含的元素；按住 Shift 可追加选中，Esc 取消。")
            self.update()
            return
        step = self.grid_mm if self.snap and not (modifiers & QtCore.Qt.AltModifier) else 0
        self._candidate = None
        try:
            if self.tool != "select":
                candidate, key = add_element(
                    self.template, self.face_name, self.tool, g["start"], g["end"], step
                )
            elif g["group"]:
                key = self.selection
                candidate = move_selection(
                    self.template,
                    self.face_name,
                    g["keys"],
                    g["end"][0] - g["start"][0],
                    g["end"][1] - g["start"][1],
                    step,
                )
            else:
                key = g["key"]
                item = element_at(self.template, self.face_name, key)
                if g["handle"] is None:
                    item = move_element(
                        item, g["end"][0] - g["start"][0], g["end"][1] - g["start"][1], step
                    )
                elif isinstance(item, Region):
                    item = resize_region(item, g["handle"], g["end"], step)
                else:
                    item = move_vertex(item, g["handle"], g["end"], step)
                candidate = edit_element(
                    self.template, self.face_name, key, item, link_body_width=self.link_body_width
                )
            self._candidate, self._candidate_key = candidate, key
            self.status.emit("松开应用；Esc 取消；按住 Alt 暂停吸附。")
        except (ValueError, TypeError) as error:
            self.status.emit(f"不能放置：{error}。松开将保留原页面版式。")
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or self._gesture is None:
            return super().mouseReleaseEvent(event)
        g = self._gesture
        if g["box"]:
            if g["active"]:
                end = self.to_mm(event.position())
                left, right = sorted((g["start"][0], end[0]))
                top, bottom = sorted((g["start"][1], end[1]))
                keys = []
                for key, item in element_items(self.template, self.face_name):
                    l, t, r, b = element_bounds(item)
                    if left <= l and top <= t and right >= r and bottom >= b:
                        keys.append(key)
            else:
                keys = []
            self.set_selections((*g["keys"], *keys) if g["additive"] else keys, notify=True)
            self.cancel_gesture()
            self.status.emit(f"已选中 {len(self.selections)} 个元素。")
            event.accept()
            return
        if self.tool == "anchors" and not g["active"]:
            g["active"] = True
        if g["active"]:
            self.propose(event.position(), event.modifiers())
        candidate, key = self._candidate, self._candidate_key
        self._gesture = None
        self._candidate = None
        if candidate and candidate != self.template:
            self.committed.emit(candidate, key)
        self.update()
        event.accept()

    def cancel_gesture(self):
        self._gesture = None
        self._candidate = None
        self._candidate_key = None
        self.update()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape and self._gesture is not None:
            self.cancel_gesture()
            self.status.emit("已取消画布操作，页面版式未改变。")
            event.accept()
            return
        super().keyPressEvent(event)
