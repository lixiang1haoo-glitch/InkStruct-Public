"""Versioned private preview IPC. Only page drawing primitives cross the boundary."""

import math
import re
import struct
from itertools import chain

from ..document.cancellation import check_cancel
from ..document.limits import DEFAULT_LIMITS
from ..renderers.pages import PageDraw, page_draw
from ..scene.schema import PaintOp


VERSION = 1
MAX_PACKET = 64 * 1024**2
MAX_POINTS = DEFAULT_LIMITS.points
MAX_IMAGES = DEFAULT_LIMITS.nodes
MAX_ID_BYTES = 4096
COLOR = re.compile(rb"#[0-9a-fA-F]{3,8}|[a-zA-Z]{1,32}")
BASE64 = re.compile(rb"[A-Za-z0-9+/]*={0,2}")

# Little-endian. Header: magic, version, flags, total bytes, two dimensions,
# background byte count, image count, stroke count. A flag preserves each
# dimension's original int/float spelling in the SVG view box.
HEADER = struct.Struct("<4sBBIddIII")
IMAGE = struct.Struct("<4dI")
STROKE = struct.Struct("<dHBI")
POINT = struct.Struct("<2d")
MAGIC = b"ISPV"


def write_page(path, snapshot, index, cancelled):
    page = page_draw(snapshot, index, not snapshot.exportable)
    background = (page.background or "").encode("ascii")
    flags = int(page.debug) | (type(page.width_mm) is int) << 1 | (type(page.height_mm) is int) << 2
    count = 0
    if len(page.images) > MAX_IMAGES or not all(
        math.isfinite(v) and v > 0 for v in (page.width_mm, page.height_mm)
    ):
        raise ValueError("Invalid page drawing dimensions or image count")
    with path.open("xb", buffering=256 * 1024) as stream:
        stream.write(b"\0" * HEADER.size)
        stream.write(background)
        for bounds, image in page.images:
            check_cancel(cancelled)
            raw = (image or "").encode("ascii")
            if stream.tell() + IMAGE.size + len(raw) > MAX_PACKET:
                raise ValueError("Preview page payload exceeds byte limit")
            stream.write(IMAGE.pack(*bounds, len(raw)))
            stream.write(raw)
        for op in page.strokes:
            check_cancel(cancelled)
            identity = op.occurrence_id.encode("utf-8")
            color = op.color.encode("ascii")
            points = len(op.points)
            count += points
            if (not 0 < len(identity) <= MAX_ID_BYTES or not COLOR.fullmatch(color)
                    or points < 1 or count > MAX_POINTS):
                raise ValueError("Invalid preview stroke")
            if stream.tell() + STROKE.size + len(identity) + len(color) + points * POINT.size > MAX_PACKET:
                raise ValueError("Preview page payload exceeds byte limit")
            stream.write(STROKE.pack(op.width_mm, len(identity), len(color), points))
            stream.write(identity)
            stream.write(color)
            stream.write(struct.pack(f"<{points * 2}d", *chain.from_iterable(op.points)))
        size = stream.tell()
        check_cancel(cancelled)
        if size > MAX_PACKET:
            raise ValueError("Preview page payload exceeds byte limit")
        stream.seek(0)
        stream.write(HEADER.pack(MAGIC, VERSION, flags, size, page.width_mm, page.height_mm,
                                 len(background), len(page.images), len(page.strokes)))
    return size


class PageReader:
    def __init__(self, raw):
        self.raw = memoryview(raw)
        self.offset = 0

    def take(self, size):
        end = self.offset + size
        if end > len(self.raw):
            raise ValueError("Truncated preview page payload")
        chunk = self.raw[self.offset:end]
        self.offset = end
        return chunk

    def fields(self, layout):
        return layout.unpack(self.take(layout.size))

    def image(self, size):
        if not size:
            return None
        raw = self.take(size)
        if size % 4 or raw[:11] != b"iVBORw0KGgo" or not BASE64.fullmatch(raw):
            raise ValueError("Invalid preview PNG data")
        return raw.tobytes().decode("ascii")


def read_page(path, cancelled=None):
    size = path.stat().st_size
    if not HEADER.size <= size <= MAX_PACKET:
        raise ValueError("Preview page payload exceeds byte limit or has no header")
    with path.open("rb") as stream:
        raw = stream.read(size + 1)
    if len(raw) != size:
        raise ValueError("Preview page payload length changed")
    reader = PageReader(raw)
    magic, version, flags, length, w, h, paper, images, strokes = reader.fields(HEADER)
    if (magic != MAGIC or version != VERSION or flags & ~7 or length != size
            or not all(math.isfinite(v) and v > 0 for v in (w, h))
            or (flags & 2 and not w.is_integer()) or (flags & 4 and not h.is_integer())
            or images > MAX_IMAGES or strokes > MAX_POINTS):
        raise ValueError("Invalid preview page payload header")
    background = reader.image(paper)
    pictures, paths = [], []
    for _ in range(images):
        check_cancel(cancelled)
        x0, y0, x1, y1, byte_count = reader.fields(IMAGE)
        if not all(map(math.isfinite, (x0, y0, x1, y1))) or x0 > x1 or y0 > y1:
            raise ValueError("Invalid preview image bounds")
        pictures.append(((x0, y0, x1, y1), reader.image(byte_count)))
    count = 0
    for _ in range(strokes):
        check_cancel(cancelled)
        width, id_bytes, color_bytes, points = reader.fields(STROKE)
        count += points
        if (not math.isfinite(width) or width < 0 or not 0 < id_bytes <= MAX_ID_BYTES
                or not 0 < color_bytes <= 32 or points < 1 or count > MAX_POINTS):
            raise ValueError("Invalid preview stroke header")
        identity = reader.take(id_bytes).tobytes().decode("utf-8")
        color = reader.take(color_bytes)
        if not COLOR.fullmatch(color):
            raise ValueError("Invalid preview color")
        values = tuple(POINT.iter_unpack(reader.take(points * POINT.size)))
        if not all(math.isfinite(x) and math.isfinite(y) for x, y in values):
            raise ValueError("Invalid preview stroke coordinates")
        paths.append(PaintOp(identity, values, width, color.tobytes().decode("ascii")))
    if reader.offset != size:
        raise ValueError("Unexpected trailing preview page data")
    page = PageDraw(int(w) if flags & 2 else w, int(h) if flags & 4 else h, bool(flags & 1),
                    background, tuple(pictures), tuple(paths))
    # Account for Python float pairs, stroke objects and decoded strings.
    return page, size + count * 120 + strokes * 320
