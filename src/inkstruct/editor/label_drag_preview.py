"""Temporary display layers for dragging handwritten labels on a raster preview."""
from dataclasses import dataclass, replace
import math

from PySide6 import QtCore, QtGui, QtSvg

from ..renderers.pages import page_draw, draw_screen_svg


def render(page, spec, accelerated, box, *, transparent=False, target=None):
    width, height, dpr = spec
    xml = draw_screen_svg(page, spec, accelerate=accelerated)
    if transparent:
        # Only omit the generated paper rectangle; preserve white ink and artwork.
        xml = xml.replace(f'<rect width="{page.width_mm}" height="{page.height_mm}" fill="white"/>', '', 1)
    if target is None:
        target = QtGui.QImage(box.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        if target.isNull():
            raise ValueError("标注预览图层过大")
        target.fill(QtCore.Qt.GlobalColor.transparent if transparent else QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(target)
    try:
        painter.translate(-box.x(), -box.y())
        renderer = QtSvg.QSvgRenderer(xml.encode())
        renderer.render(painter, QtCore.QRectF(0, 0, width*dpr, height*dpr))
    finally:
        painter.end()
    return target


class LabelPage:
    def __init__(self, snapshot, index, spec, accelerated):
        self.spec, self.accelerated = spec, accelerated
        self.page = page_draw(snapshot, index, not snapshot.exportable)
        self.labels = {}
        for fragment in snapshot.pages[index].fragments:
            if fragment.image_label:
                self.labels.setdefault(fragment.image_label, set()).add(fragment.occurrence_id)
        width, height, dpr = spec
        self.paper = QtCore.QRect(0, 0, math.ceil(width*dpr), math.ceil(height*dpr))
        self.background = replace(self.page, strokes=(), debug=False)
        self.static = None
        if self.paper.width()*self.paper.height()*4 <= 40*1024**2:
            self.static = render(self.background, spec, accelerated, self.paper)
        self.strokes = []
        sx, sy = width*dpr/self.page.width_mm, height*dpr/self.page.height_mm
        for op in self.page.strokes:
            if not op.points:
                continue
            xs, ys = zip(*op.points)
            r = op.width_mm/2
            box = QtCore.QRectF((min(xs)-r)*sx, (min(ys)-r)*sy,
                                (max(xs)-min(xs)+2*r)*sx, (max(ys)-min(ys)+2*r)*sy)
            self.strokes.append((box.toAlignedRect().adjusted(-2,-2,2,2), op))

    def layers(self, label):
        ids = self.labels.get(label, ())
        box = QtCore.QRect()
        ink = []
        for bounds, op in self.strokes:
            if op.occurrence_id in ids:
                box = box.united(bounds)
                ink.append(op)
        box = box.intersected(self.paper)
        if box.isEmpty() or box.width()*box.height()*4 > 40*1024**2:
            return None
        rest = tuple(op for bounds, op in self.strokes if op.occurrence_id not in ids and bounds.intersects(box))
        clean = (self.static.copy(box) if self.static is not None else
                 render(self.background, self.spec, self.accelerated, box))
        layer = replace(self.page, background=None, images=(), strokes=rest)
        render(layer, self.spec, self.accelerated, box, transparent=True, target=clean)
        sprite = render(replace(layer, strokes=tuple(ink), debug=False), self.spec,
                        self.accelerated, box, transparent=True)
        dpr = self.spec[2]
        for image in (clean, sprite):
            image.setDevicePixelRatio(dpr)
        return (QtCore.QRectF(box.x()/dpr, box.y()/dpr, box.width()/dpr, box.height()/dpr),
                clean, sprite)


class Ready(QtCore.QObject):
    result = QtCore.Signal(object, object)


class PrepareLabelPage(QtCore.QRunnable):
    def __init__(self, snapshot, index, key, spec, accelerated):
        super().__init__()
        self.snapshot, self.index, self.key = snapshot, index, key
        self.spec, self.accelerated = spec, accelerated
        self.signals = Ready()

    def run(self):
        try:
            page = LabelPage(self.snapshot, self.index, self.spec, self.accelerated)
        except (ValueError, MemoryError, OverflowError):
            page = None
        self.signals.result.emit(self.key, page)


@dataclass
class DragOverlay:
    index: int
    generation: int
    render_key: tuple
    box: QtCore.QRectF
    clean: QtGui.QImage
    ink: QtGui.QImage
    tiles: dict
    offset: QtCore.QPointF
    accepted: bool = False
    accepted_revision: int | None = None
