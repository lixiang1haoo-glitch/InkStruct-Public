"""Explicit single-pen SVG subset. No SVG renderer, external resources or tracing."""

import base64
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET

from .svg_geometry import NUMBER, Flattener, multiply, numbers, transform

SCHEMA = "inkstruct_line_svg_v1"
MAX_BYTES = 1_000_000
NS = "{http://www.w3.org/2000/svg}"
PRESENTATION = {
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-miterlimit",
}
SHAPES = {
    "path": {"d"},
    "line": {"x1", "y1", "x2", "y2"},
    "polyline": {"points"},
    "polygon": {"points"},
    "rect": {"x", "y", "width", "height"},
    "circle": {"cx", "cy", "r"},
    "ellipse": {"cx", "cy", "rx", "ry"},
}


def length(value):
    m = re.fullmatch(rf"\s*({NUMBER})(mm|cm|in|pt|pc|px)?\s*", value)
    if not m:
        raise ValueError("SVG root dimensions need absolute units, not percentages")
    n = (
        float(m[1])
        * {
            None: 25.4 / 96,
            "px": 25.4 / 96,
            "mm": 1,
            "cm": 10,
            "in": 25.4,
            "pt": 25.4 / 72,
            "pc": 25.4 / 6,
        }[m[2]]
    )
    if not math.isfinite(n) or not 1e-6 <= n <= 2000:
        raise ValueError("SVG physical size must be within (0, 2000] mm")
    return n


def root_data(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("SVG exceeds the 1 MB resource limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError("SVG must be UTF-8") from error
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)|<\?(?!xml\s)", text, re.IGNORECASE):
        raise ValueError("SVG DTDs, entities and processing instructions are unsupported")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError("Malformed SVG XML") from error
    if root.tag not in {"svg", NS + "svg"}:
        raise ValueError("Expected SVG root")
    if len(list(root.iter())) > 5000:
        raise ValueError("SVG element budget exceeded")
    width, height = length(root.get("width", "")), length(root.get("height", ""))
    view = numbers(root.get("viewBox", f"0 0 {width * 96 / 25.4} {height * 96 / 25.4}"))
    if len(view) != 4 or view[2] <= 0 or view[3] <= 0:
        raise ValueError("Invalid SVG viewBox")
    aspect = root.get("preserveAspectRatio", "xMidYMid meet").strip()
    if aspect not in {"none", "xMidYMid", "xMidYMid meet"}:
        raise ValueError("Only none or xMidYMid meet preserveAspectRatio is supported")
    return root, width, height, view, aspect


def _shape_path(kind, attrs):
    def n(key, default="0"):
        v = numbers(attrs.get(key, default))
        if len(v) != 1:
            raise ValueError("SVG shape coordinates must be unitless numbers")
        return v[0]

    if kind == "path":
        return attrs.get("d", "")
    if kind in {"polyline", "polygon"}:
        v = numbers(attrs.get("points", ""))
        if len(v) < 4 or len(v) % 2:
            raise ValueError("Invalid SVG point list")
        return "M " + " ".join(map(str, v)) + (" Z" if kind == "polygon" else "")
    if kind == "line":
        return f"M {n('x1')} {n('y1')} L {n('x2')} {n('y2')}"
    if kind == "rect":
        x, y, w, h = n("x"), n("y"), n("width"), n("height")
        if w <= 0 or h <= 0:
            raise ValueError("SVG rectangle needs positive dimensions")
        return f"M {x} {y} h {w} v {h} h {-w} Z"
    x, y = n("cx"), n("cy")
    rx, ry = (n("r"), n("r")) if kind == "circle" else (n("rx"), n("ry"))
    if rx <= 0 or ry <= 0:
        raise ValueError("SVG ellipse needs positive radii")
    return f"M {x - rx} {y} A {rx} {ry} 0 1 0 {x + rx} {y} A {rx} {ry} 0 1 0 {x - rx} {y} Z"


@lru_cache(maxsize=8)
def compile_svg(raw, width_mm, height_mm, tolerance_mm=0.05):
    """Return final-mm subpaths, preserving order; unsupported content is an error."""
    root, _, _, view, aspect = root_data(raw)
    if any(not math.isfinite(v) or not 0 < v <= 2000 for v in (width_mm, height_mm)):
        raise ValueError("Invalid SVG target size")
    sx, sy = width_mm / view[2], height_mm / view[3]
    ox = oy = 0
    if aspect != "none":
        sx = sy = min(sx, sy)
        ox, oy = (width_mm - view[2] * sx) / 2, (height_mm - view[3] * sy) / 2
    viewport = (sx, 0, 0, sy, ox - view[0] * sx, oy - view[1] * sy)
    flat = Flattener(tolerance_mm)

    def walk(node, parent, inherited, depth=0):
        if depth > 32:
            raise ValueError("SVG nesting budget exceeded")
        tag = node.tag.removeprefix(NS)
        if tag in {"title", "desc"}:
            if len(node) or set(node.attrib) - {"id"} or (node.tail or "").strip():
                raise ValueError("Unsupported SVG metadata")
            return
        if tag not in {"svg", "g", *SHAPES} or (tag == "svg" and node is not root):
            raise ValueError(f"Unsupported SVG element: {tag}")
        allowed = {"id", "transform", "style"} | PRESENTATION | SHAPES.get(tag, set())
        if node is root:
            allowed |= {"width", "height", "viewBox", "preserveAspectRatio", "version"}
        if set(node.attrib) - allowed:
            raise ValueError(f"Unsupported SVG attributes: {sorted(set(node.attrib) - allowed)}")
        if (node.text or "").strip() or (node.tail or "").strip():
            raise ValueError("Unexpected SVG text")
        style = dict(inherited)
        style.update({k: v.strip() for k, v in node.attrib.items() if k in PRESENTATION})
        for rule in node.get("style", "").split(";"):
            if not rule.strip():
                continue
            pair = rule.split(":")
            if len(pair) != 2 or pair[0].strip() not in PRESENTATION:
                raise ValueError("Unsupported SVG style")
            style[pair[0].strip()] = pair[1].strip()
        matrix = multiply(parent, transform(node.get("transform", "")))
        if tag in SHAPES:
            if len(node):
                raise ValueError("SVG shapes cannot contain child elements")
            if style.get("fill", "black") != "none":
                raise ValueError("Filled SVG shapes and font outlines are not single-line drawings")
            if style.get("stroke", "none").lower() not in {"black", "#000", "#000000", "#111827"}:
                raise ValueError("SVG needs an explicit single black stroke")
            pen = style.get("stroke-width", "1")
            # Source stroke describes display only; actual pen width is the document setting.
            match = re.fullmatch(rf"({NUMBER})(?:mm|cm|in|pt|pc|px)?", pen)
            if not match or not math.isfinite(float(match[1])) or float(match[1]) <= 0:
                raise ValueError("SVG stroke width must be positive")
            if style.get("stroke-linecap", "butt") not in {"butt", "round", "square"}:
                raise ValueError("Unsupported SVG line cap")
            if style.get("stroke-linejoin", "miter") not in {"miter", "round", "bevel"}:
                raise ValueError("Unsupported SVG line join")
            if "stroke-miterlimit" in style:
                value = numbers(style["stroke-miterlimit"])
                if len(value) != 1 or value[0] < 1:
                    raise ValueError("Invalid SVG miter limit")
            flat.path(_shape_path(tag, node.attrib), matrix)
        for child in node:
            walk(child, matrix, style, depth + 1)

    walk(root, viewport, {})
    if not flat.paths:
        raise ValueError("SVG has no drawable centreline paths")
    if any(
        x < -1e-8 or y < -1e-8 or x > width_mm + 1e-8 or y > height_mm + 1e-8
        for path in flat.paths
        for x, y in path
    ):
        raise ValueError("SVG paths escape the viewport; clipping is unsupported")
    return tuple(flat.paths)


@dataclass(frozen=True)
class LineSvgResource:
    source: str
    original_sha256: str
    original_base64: str
    width_mm: float
    height_mm: float
    schema_version: str = SCHEMA

    def __post_init__(self):
        if not isinstance(self.source, str) or not self.source or self.schema_version != SCHEMA:
            raise ValueError("Invalid SVG resource identity")
        if not isinstance(self.original_base64, str) or len(self.original_base64) > 1_400_000:
            raise ValueError("SVG resource exceeds encoded size budget")
        raw = base64.b64decode(self.original_base64, validate=True)
        if sha256(raw).hexdigest() != self.original_sha256:
            raise ValueError("SVG resource hash mismatch")
        _, w, h, _, _ = root_data(raw)
        if (w, h) != (self.width_mm, self.height_mm):
            raise ValueError("SVG dimensions differ from source")
        compile_svg(raw, w, h)

    @classmethod
    def from_file(cls, path, source):
        path = Path(path)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("SVG exceeds the 1 MB resource limit")
        raw = path.read_bytes()
        _, w, h, _, _ = root_data(raw)
        return cls(source, sha256(raw).hexdigest(), base64.b64encode(raw).decode(), w, h)

    @property
    def aspect_ratio(self):
        return self.height_mm / self.width_mm

    def paths(self, width, height, tolerance):
        return compile_svg(
            base64.b64decode(self.original_base64, validate=True), width, height, tolerance
        )
