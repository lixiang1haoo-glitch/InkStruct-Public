"""Private persistent Qt raster process; never owns document or font files."""
import json
import math
import os
import sys
import time
from pathlib import Path

from PySide6 import QtGui

from ..cache import BoundedCache
from ..document.cancellation import LayoutCancelled, check_cancel
from ..renderers.pages import draw_screen_svg
from .preview_backend import CpuRaster, GpuRaster
from .preview_wire import VERSION, read_page

TILE = 512
MAX_IMAGE = 40 * 1024**2


class RasterService:
    def __init__(self, backend='cpu'):
        self.cpu = CpuRaster()
        self.gpu = None
        self.fallback = None
        self.pages = BoundedCache(max_entries=8, max_weight=96 * 1024**2)
        if backend == 'gpu':
            try:
                self.gpu = GpuRaster()
            except Exception as error:  # noqa: BLE001 - optional graphics backend
                self.fallback = str(error)

    def page(self, page_id, directory, cancelled):
        cached = self.pages.get(page_id)
        if cached is not None:
            return cached, True
        page, weight = read_page(directory / f'page-{page_id}.bin', cancelled)
        self.pages.put((page_id,), page, weight)
        return page, False

    def images(self, raw, spec, rectangles):
        raster = self.gpu or self.cpu
        try:
            svg = raster.svg(raw)
            return [raster.image(svg, *spec, *rect) for rect in rectangles]
        except Exception as error:
            if self.gpu is None:
                raise
            self.fallback = str(error)
            try:
                self.gpu.close()
            except Exception as cleanup_error:  # noqa: BLE001 - device loss boundary
                self.fallback += '; cleanup: ' + str(cleanup_error)
            self.gpu = None
            svg = self.cpu.svg(raw)
            return [self.cpu.image(svg, *spec, *rect) for rect in rectangles]


class Cancellation:
    def __init__(self, path):
        self.path = path
        self.next_check = 0.0
        self.cancelled = False

    def is_set(self):
        now = time.perf_counter()
        if not self.cancelled and now >= self.next_check:
            self.next_check = now + .01
            self.cancelled = self.path.exists()
        return self.cancelled


def render(request, directory, service):
    token = request['token']
    page_id, accelerate = request['page'], request['accelerate']
    if any(type(value) is not int or not 1 <= value < 2**63 for value in (token, page_id)):
        raise ValueError('Invalid preview request identity')
    if type(request['version']) is not int or request['version'] != VERSION or type(accelerate) is not bool:
        raise ValueError('Unsupported preview request version or render mode')
    width, height, dpr = request['spec']
    if (any(type(v) is not int or not 1 <= v < 2**24 for v in (width, height))
            or type(dpr) not in (int, float) or not 0 < dpr <= 16):
        raise ValueError('Invalid screen preview dimensions')
    physical_w, physical_h = math.ceil(width * dpr), math.ceil(height * dpr)
    tiles = request['tiles']
    if not isinstance(tiles, list) or not 1 <= len(tiles) <= 32:
        raise ValueError('Preview tile request exceeds limit')
    if [-1, -1] in tiles and len(tiles) != 1:
        raise ValueError('Full page cannot be combined with tiles')
    if any(not isinstance(t, list) or len(t) != 2 or any(type(v) is not int for v in t) for t in tiles):
        raise ValueError('Invalid preview tile')
    if len({tuple(t) for t in tiles}) != len(tiles):
        raise ValueError('Duplicate preview tiles')
    rectangles = []
    for col, row in tiles:
        full = (col, row) == (-1, -1)
        if not full and not (0 <= col < math.ceil(physical_w / TILE)
                             and 0 <= row < math.ceil(physical_h / TILE)):
            raise ValueError('Preview tile outside page')
        x, y = (0, 0) if full else (col * TILE, row * TILE)
        w, h = (physical_w, physical_h) if full else (
            min(TILE, physical_w - x), min(TILE, physical_h - y))
        if w * h * 4 > MAX_IMAGE:
            raise ValueError('Screen preview image exceeds budget')
        rectangles.append((x, y, w, h))
    cancelled = Cancellation(directory / f'{token}.cancel')
    check_cancel(cancelled)
    started = time.perf_counter()
    page, reused = service.page(page_id, directory, cancelled)
    decoded = time.perf_counter()
    raw = draw_screen_svg(page, (width, height, dpr), accelerate=accelerate, cancelled=cancelled).encode()
    if len(raw) > 32 * 1024**2:
        raise ValueError('Preview SVG exceeds limit')
    check_cancel(cancelled)
    assembled = time.perf_counter()
    rendered = service.images(raw, (width, height, dpr), rectangles)
    check_cancel(cancelled)
    images = []
    for (col, row), (_, _, w, h), image in zip(tiles, rectangles, rendered, strict=True):
        output = directory / f'{token}-{col}-{row}.argb'
        with output.open('wb') as f:
            f.write(image.constBits())
        images.append({'tile': [col, row], 'width': w, 'height': h,
                       'stride': image.bytesPerLine(), 'bytes': image.sizeInBytes()})
    return {'token': token, 'images': images, 'raster_seconds': time.perf_counter() - assembled,
            'decode_seconds': decoded - started, 'svg_seconds': assembled - decoded, 'page_reused': reused,
            'backend': 'gpu' if service.gpu is not None else 'cpu', 'gpu_fallback': service.fallback}


def main(directory=None):
    app = QtGui.QGuiApplication([])
    directory = Path(directory or sys.argv[1]).resolve(strict=True)
    service = RasterService(os.environ.get('INKSTRUCT_PREVIEW_BACKEND', 'cpu'))
    for raw in iter(lambda: sys.stdin.buffer.readline(65537), b''):
        response = {'token': None}
        try:
            if len(raw) > 65536:
                raise ValueError('Preview request exceeds limit')
            request = json.loads(raw)
            response['token'] = request.get('token')
            response.update(render(request, directory, service))
        except LayoutCancelled:
            response['cancelled'] = True
        except Exception as error:  # noqa: BLE001 - isolated process boundary
            response['error'] = str(error)
        line = json.dumps(response, ensure_ascii=False) + '\n'
        sys.stdout.buffer.write(line.encode('utf-8'))
        sys.stdout.buffer.flush()
    return 0 if app else 1


if __name__ == '__main__':
    raise SystemExit(main())
