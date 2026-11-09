"""Virtual continuous pages with bounded, asynchronous screen rasterization.

Only the viewport and a small neighbour region request images. Screen pixels
are derived display data; document geometry and vector exports stay unchanged.
"""
import math
import threading
import time
from collections import OrderedDict

from PySide6 import QtCore, QtGui, QtWidgets

from ..cache import BoundedCache
from ..document.limits import validate_snapshot
from ..renderers.pages import page_svg
from .preview_process import PreviewProcess

FULL = (-1, -1)
TILE = 512  # Device pixels, independent of Windows display scaling.
MAX_PAGE_IMAGE = 40 * 1024**2
COLORS = {"good": "#24845c", "bad": "#c34444", "review": "#bb841b"}


class PreviewScrollArea(QtWidgets.QScrollArea):
    zoom_requested = QtCore.Signal(int, QtCore.QPointF)

    def __init__(self):
        super().__init__()
        self.wheel_remainder = 0

    def wheelEvent(self, event):
        if not event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            self.wheel_remainder = 0
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y() or event.pixelDelta().y() * 3
        self.wheel_remainder += delta
        steps, remainder = divmod(abs(self.wheel_remainder), 120)
        sign = 1 if self.wheel_remainder >= 0 else -1
        self.wheel_remainder = sign * remainder
        if steps:
            self.zoom_requested.emit(sign * steps, event.position())
        event.accept()


class RasterSignals(QtCore.QObject):
    finished = QtCore.Signal(object)


class RasterWorker(QtCore.QRunnable):
    def __init__(self, snapshot, generation, index, spec, tiles, token, path):
        super().__init__()
        self.snapshot, self.generation, self.index = snapshot, generation, index
        self.spec, self.tiles = spec, tuple(tiles)
        self.token, self.path = token, path
        self.cancelled = threading.Event()
        self.signals = RasterSignals()

    def run(self):
        result = {'generation': self.generation, 'index': self.index, 'spec': self.spec,
                  'images': [], 'svg_seconds': 0.0, 'raster_seconds': 0.0,
                  'token': self.token, 'tiles': self.tiles, 'cancel_event': self.cancelled}
        try:
            if self.cancelled.is_set():
                return
            start = time.perf_counter()
            raw = page_svg(self.snapshot, self.index, debug=not self.snapshot.exportable).encode()
            self.path.write_bytes(raw)
            result['svg_seconds'] = time.perf_counter() - start
        except Exception as error:  # noqa: BLE001 - transport render failures to GUI
            result['error'] = str(error)
        finally:
            result['cancelled'] = self.cancelled.is_set()
            self.signals.finished.emit(result)


class ContinuousPageCanvas(QtWidgets.QWidget):
    selected = QtCore.Signal(object)
    task_activated = QtCore.Signal(object)
    first_page_painted = QtCore.Signal(object)
    margin = 12
    gap = 24

    def __init__(self):
        super().__init__()
        self.setObjectName('page_canvas')
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.snapshot = None
        self.page_index = 0
        self.scale = 3.0
        self.reviews, self.selected_id, self.show_marks = {}, None, True
        # Keys contain an epoch, not a page/snapshot: cached pixels never retain
        # old documents or their potentially large trajectory catalogs.
        self.preview_cache = BoundedCache(max_entries=256, max_weight=96 * 1024**2)
        self._generation = 0
        self._first_painted_generation = -1
        self._startup_background = None
        self._page_tokens = []
        self._next_page_token = 0
        self._job = None
        self._process = PreviewProcess(self)
        self._process.completed.connect(self._completed)
        self._closed = False
        self._rects = OrderedDict()
        self._errors = {}
        self._direction = 1
        self._previous_top = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._launch)
        self.render_jobs = self.cancelled_jobs = self.painted_pages = 0
        self.svg_seconds = self.raster_seconds = 0.0
        self.setFixedSize(300, 400)

    def page_size(self):
        p = self.snapshot.page_profile
        return round(p.width_mm * self.scale), round(p.height_mm * self.scale)

    def page_rect(self, index):
        width, height = self.page_size()
        return QtCore.QRectF(self.margin, self.margin + index * (height + self.gap), width, height)

    def page_at(self, y):
        if not self.snapshot:
            return 0
        height = self.page_size()[1]
        return max(0, min(len(self.snapshot.pages) - 1,
                          int((y - self.margin) // (height + self.gap))))

    def pages_in_rect(self, rect):
        if not self.snapshot or rect.isEmpty():
            return ()
        return range(self.page_at(rect.top()), self.page_at(rect.bottom()) + 1)

    def viewport_rect(self):
        viewport = self.parentWidget()
        if viewport is None:
            return QtCore.QRectF(self.rect())
        return QtCore.QRectF(QtCore.QRect(self.mapFrom(viewport, QtCore.QPoint()), viewport.size()))

    def clear_document(self):
        if self._job:
            self._job.cancelled.set()
        self._generation += 1
        self._page_tokens = []
        self._rects.clear()
        self._errors.clear()
        self._startup_background = None
        self.snapshot = self.selected_id = None
        self.page_index = 0
        self.setFixedSize(1, 1)
        self.update()

    def load_page(self, snapshot, index, *, startup_image=None):
        if snapshot is not self.snapshot:
            validate_snapshot(snapshot)
            first = snapshot.pages[0] if snapshot.pages else None
            if startup_image is not None:
                self._startup_background = (first, startup_image)
            elif (self._startup_background and
                  (first is not self._startup_background[0] or not snapshot.exportable)):
                self._startup_background = None
            old = self.snapshot
            reusable = {}
            if (old is not None and repr(old.page_profile) == repr(snapshot.page_profile)
                    and old.exportable == snapshot.exportable):
                reusable = {id(p): (p, token) for p, token in zip(old.pages, self._page_tokens)}
            tokens = []
            for page in snapshot.pages:
                previous = reusable.get(id(page))
                if previous is not None and previous[0] is page:
                    tokens.append(previous[1])
                else:
                    self._next_page_token += 1
                    tokens.append(self._next_page_token)
            self._page_tokens = tokens
            self._generation += 1
            if self._job:
                self._job.cancelled.set()
            self._rects.clear()
            self._errors.clear()
        self.margin = 24 if any(p.source_layout for p in snapshot.pages) else 12
        self.snapshot, self.page_index = snapshot, index
        self.resize_page()

    def resize_page(self):
        if self._job:
            self._job.cancelled.set()
        self._rects.clear()
        if self.snapshot:
            width, height = self.page_size()
            self.setFixedSize(width + 2 * self.margin,
                              2 * self.margin + len(self.snapshot.pages) * (height + self.gap) - self.gap)
        self.update()
        self._queue()

    def rect_for(self, fragment):
        p = self.snapshot.page_profile
        page = self.page_rect(fragment.page_index)
        x0, y0, x1, y1 = fragment.selection_bounds
        return QtCore.QRectF(page.left() + x0 * page.width() / p.width_mm,
                             page.top() + y0 * page.height() / p.height_mm,
                             (x1 - x0) * page.width() / p.width_mm,
                             (y1 - y0) * page.height() / p.height_mm)

    def _geometry(self, index):
        if index not in self._rects:
            if len(self._rects) >= 4:
                self._rects.popitem(last=False)
            self._rects[index] = tuple((f, self.rect_for(f)) for f in self.snapshot.pages[index].fragments)
        self._rects.move_to_end(index)
        return self._rects[index]

    def _spec(self):
        return (*self.page_size(), self.devicePixelRatioF())

    def _tiles(self, index, rect):
        width, height, dpr = self._spec()
        page = self.page_rect(index)
        visible = page.intersected(rect)
        if visible.isEmpty():
            return ()
        if math.ceil(width * dpr) * math.ceil(height * dpr) * 4 <= MAX_PAGE_IMAGE:
            return (FULL,)
        left = max(0, int((visible.left() - page.left()) * dpr // TILE))
        top = max(0, int((visible.top() - page.top()) * dpr // TILE))
        right = min(math.ceil(width * dpr / TILE) - 1,
                    math.ceil((visible.right() - page.left()) * dpr / TILE) - 1)
        bottom = min(math.ceil(height * dpr / TILE) - 1,
                     math.ceil((visible.bottom() - page.top()) * dpr / TILE) - 1)
        return tuple((col, row) for row in range(top, bottom + 1) for col in range(left, right + 1))

    def _key(self, index, tile):
        return (self._page_tokens[index], self._spec(), tile)

    def _tile_bytes(self, tile):
        width, height, dpr = self._spec()
        w, h = math.ceil(width * dpr), math.ceil(height * dpr)
        if tile != FULL:
            w, h = min(TILE, w - tile[0] * TILE), min(TILE, h - tile[1] * TILE)
        return w * h * 4 + 128

    def viewport_ready(self):
        if not self.snapshot:
            return True
        visible = self.viewport_rect()
        return all(self.preview_cache.get(self._key(index, tile)) is not None
                   for index in self.pages_in_rect(visible)
                   if index != 0 or self._startup_background is None
                   for tile in self._tiles(index, visible))

    def viewport_changed(self, *_):
        visible = self.viewport_rect()
        if visible.top() != self._previous_top:
            self._direction = 1 if visible.top() > self._previous_top else -1
            self._previous_top = visible.top()
        indices = tuple(self.pages_in_rect(visible))
        if self._job and self._job.index not in indices:
            adjacent = bool(indices) and min(indices) - 1 <= self._job.index <= max(indices) + 1
            if not adjacent or not self.viewport_ready():
                self._job.cancelled.set()
        self._queue()

    def _queue(self):
        if not self._closed and self.snapshot and not self._timer.isActive():
            self._timer.start(0)

    def _launch(self):
        if self._closed or self._job or not self.snapshot or not self.isVisible():
            return
        visible = self.viewport_rect()
        indices = sorted(self.pages_in_rect(visible), key=lambda i: abs(i - self.page_at(visible.center().y())))
        requests = [(i, visible) for i in indices]
        # At most one neighbouring page, in the direction of scrolling. Avoid
        # endlessly swapping two prefetched neighbours under a bounded budget.
        if indices:
            neighbour = (max(indices) + 1) if self._direction > 0 else (min(indices) - 1)
            if 0 <= neighbour < len(self.snapshot.pages):
                page = self.page_rect(neighbour)
                edge = QtCore.QRectF(page.left(), page.top() if self._direction > 0 else page.bottom() - 160,
                                     page.width(), min(160, page.height()))
                protected = tuple(t for i in indices for t in self._tiles(i, visible))
                candidate = self._tiles(neighbour, edge)
                # Prefetch may evict old pages, but never the visible working
                # set. Otherwise two large visible pages and a third neighbour
                # can cause an endless render/evict loop at high zoom.
                if (sum(self._tile_bytes(t) for t in (*protected, *candidate)) <= self.preview_cache.max_weight
                        and len(protected) + len(candidate) <= self.preview_cache.max_entries):
                    requests.append((neighbour, edge))
        for index, rect in requests:
            if index == 0 and self._startup_background is not None:
                continue
            if (index, self._spec()) in self._errors:
                continue
            tiles = tuple(t for t in self._tiles(index, rect)
                          if self.preview_cache.get(self._key(index, t)) is None)
            if not tiles:
                continue
            tiles = tiles[:32]
            token, path = self._process.prepare_path()
            self._job = RasterWorker(self.snapshot, self._generation, index, self._spec(), tiles, token, path)
            self._job.signals.finished.connect(self._prepared)
            self.render_jobs += 1
            QtCore.QThreadPool.globalInstance().start(self._job)
            break

    @QtCore.Slot(object)
    def _prepared(self, result):
        if (self._closed or result['cancelled'] or 'error' in result
                or result['generation'] != self._generation or result['spec'] != self._spec()):
            (self._process.directory / f"{result['token']}.svg").unlink(missing_ok=True)
            self._completed(result)
            return
        self._process.render(result, result['tiles'])

    @QtCore.Slot(object)
    def _completed(self, result):
        result['cancelled'] = result['cancel_event'].is_set()
        self._job = None
        if self._closed:
            return
        if result['cancelled']:
            self.cancelled_jobs += 1
        if result['generation'] == self._generation and result['spec'] == self._spec():
            index = result['index']
            if 'error' in result:
                self._errors[index, result['spec']] = result['error']
            elif not result['cancelled']:
                for tile, image in result['images']:
                    self.preview_cache.put((self._key(index, tile),), image, image.sizeInBytes() + 128)
            self.svg_seconds += result['svg_seconds']
            self.raster_seconds += result['raster_seconds']
            self.update(self.page_rect(index).toAlignedRect())
        self._queue()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        dirty = QtCore.QRectF(event.rect())
        painter.fillRect(event.rect(), QtGui.QColor('#e7ebf0'))
        if not self.snapshot:
            return
        dpr = self.devicePixelRatioF()
        first_painted = False
        for index in self.pages_in_rect(dirty):
            page = self.page_rect(index)
            if not page.adjusted(-3, -3, 4, 4).intersects(dirty):
                continue
            self.painted_pages += 1
            painter.fillRect(page.translated(3, 3), QtGui.QColor('#c7cdd5'))
            painter.fillRect(page, QtCore.Qt.GlobalColor.white)
            if origin := self.snapshot.pages[index].source_layout:
                painter.setPen(QtGui.QColor('#475569'))
                painter.drawText(QtCore.QRectF(page.left(),page.top()-20,page.width(),18),
                                 QtCore.Qt.AlignmentFlag.AlignLeft,f'第 {index+1} 页 · 来源版式：{origin}')
            painted = False
            if index == 0 and self._startup_background is not None:
                painter.save()
                painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawImage(page, self._startup_background[1])
                painter.restore()
                painted = True
            else:
                for tile in self._tiles(index, dirty):
                    image = self.preview_cache.get(self._key(index, tile))
                    if image is not None:
                        x, y = (0, 0) if tile == FULL else (tile[0] * TILE / dpr, tile[1] * TILE / dpr)
                        painter.drawImage(QtCore.QPointF(page.left() + x, page.top() + y), image)
                        painted = True
            if not painted:
                painter.setPen(QtGui.QColor('#64748b'))
                message = self._errors.get((index, self._spec()), f'正在绘制第 {index + 1} 页…')
                painter.drawText(page, QtCore.Qt.AlignmentFlag.AlignCenter, message)
            elif index == 0 and self._first_painted_generation != self._generation:
                first_painted = not page.intersected(dirty).intersected(self.viewport_rect()).isEmpty()
            for fragment, rect in self._geometry(index):
                if not rect.adjusted(-3, -3, 3, 3).intersects(dirty):
                    continue
                record = self.reviews.get(fragment.asset_id)
                if record and self.show_marks:
                    color = QtGui.QColor(COLORS[record.rating]); color.setAlpha(30)
                    painter.fillRect(rect, color)
                    painter.setPen(QtGui.QPen(QtGui.QColor(COLORS[record.rating]), 2))
                    painter.drawLine(rect.bottomLeft(), rect.bottomRight())
                if fragment.status in ('missing', 'failed', 'unsupported'):
                    painter.setPen(QtGui.QColor('#b43d3d'))
                    font = painter.font(); font.setPixelSize(max(9, round(rect.height() * .55)))
                    painter.setFont(font)
                    painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, fragment.text)
                if fragment.occurrence_id == self.selected_id:
                    painter.setPen(QtGui.QPen(QtGui.QColor('#3c6bd9'), 2))
                    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                    painter.drawRect(rect.adjusted(-2, -2, 2, 2))
        painter.end()
        if first_painted:
            self._first_painted_generation = self._generation
            self.first_page_painted.emit(self.snapshot)
        self._queue()

    def mousePressEvent(self, event):
        if not self.snapshot or not self.isEnabled():
            return
        index = self.page_at(event.position().y())
        if not self.page_rect(index).contains(event.position()):
            return
        for fragment, rect in self._geometry(index):
            if fragment.status not in ('space', 'line-break') and rect.contains(event.position()):
                self.selected.emit(fragment)
                if event.button() == QtCore.Qt.MouseButton.LeftButton and fragment.status in {
                    'task-checked', 'task-unchecked'
                }:
                    self.task_activated.emit(fragment)
                return

    def statistics(self):
        return {'raster_cache': self.preview_cache.statistics(), 'render_jobs': self.render_jobs,
                'cancelled_jobs': self.cancelled_jobs, 'painted_pages': self.painted_pages,
                'svg_seconds': self.svg_seconds, 'raster_seconds': self.raster_seconds}

    def stop_rendering(self):
        self._closed = True
        self._timer.stop()
        if self._job:
            self._job.cancelled.set()
        self._process.close()
