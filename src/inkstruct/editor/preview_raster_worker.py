"""Private persistent Qt raster process; never owns document or font files."""
import json
import math
import os
import sys
import time
from pathlib import Path

from PySide6 import QtGui

from .preview_backend import CpuRaster, GpuRaster

TILE = 512
MAX_IMAGE = 40 * 1024**2


class RasterService:
    def __init__(self, backend='cpu'):
        self.cpu = CpuRaster()
        self.gpu = None
        self.fallback = None
        if backend == 'gpu':
            try:
                self.gpu = GpuRaster()
            except Exception as error:  # noqa: BLE001 - optional graphics backend
                self.fallback = str(error)

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


def render(request, directory, service=None):
    token = request['token']
    if type(token) is not int or token < 1:
        raise ValueError('Invalid preview request identity')
    path = directory / f'{token}.svg'
    if path.stat().st_size > 32 * 1024**2:
        raise ValueError('Preview SVG exceeds limit')
    width, height, dpr = request['spec']
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
           for v in (width, height, dpr)) or dpr > 16:
        raise ValueError('Invalid screen preview dimensions')
    physical_w, physical_h = math.ceil(width * dpr), math.ceil(height * dpr)
    tiles = request['tiles']
    if not isinstance(tiles, list) or not 1 <= len(tiles) <= 32:
        raise ValueError('Preview tile request exceeds limit')
    if [-1, -1] in tiles and len(tiles) != 1:
        raise ValueError('Full page cannot be combined with tiles')
    if any(not isinstance(t, list) or len(t) != 2 for t in tiles):
        raise ValueError('Invalid preview tile')
    if len({tuple(t) for t in tiles}) != len(tiles):
        raise ValueError('Duplicate preview tiles')
    rectangles = []
    for col, row in tiles:
        if type(col) is not int or type(row) is not int:
            raise ValueError('Invalid preview tile')
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
    start = time.perf_counter()
    service = service or RasterService()
    rendered = service.images(path.read_bytes(), (width, height, dpr), rectangles)
    images = []
    for (col, row), (_, _, w, h), image in zip(tiles, rectangles, rendered, strict=True):
        output = directory / f'{token}-{col}-{row}.argb'
        with output.open('wb') as f:
            f.write(image.constBits())
        images.append({'tile': [col, row], 'width': w, 'height': h,
                       'stride': image.bytesPerLine(), 'bytes': image.sizeInBytes()})
    return {'token': token, 'images': images, 'raster_seconds': time.perf_counter() - start,
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
        except Exception as error:  # noqa: BLE001 - isolated process boundary
            response['error'] = str(error)
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
        sys.stdout.flush()
    return 0 if app else 1


if __name__ == '__main__':
    raise SystemExit(main())
