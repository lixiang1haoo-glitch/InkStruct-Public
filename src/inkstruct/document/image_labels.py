"""Source-backed labels for individual, standalone Markdown images."""

import re
from dataclasses import dataclass, replace

from .schema import Diagnostic


PREFIX = "<!-- inkstruct-image-label "
_NUMBER = r"\d{1,3}(?:\.\d{1,6})?"
PATTERN = re.compile(
    re.escape(PREFIX) + rf"(?P<position>(?P<x>{_NUMBER}) (?P<y>{_NUMBER})) "
    rf"(?P<size>auto|{_NUMBER}) \| (?P<text>.+?) -->"
)
MAX_LABEL_LENGTH = 300


@dataclass(frozen=True)
class ImageLabel:
    x: float
    y: float
    em_mm: float | None = None

    @classmethod
    def from_fields(cls, x, y, size):
        return cls(float(x), float(y), None if size == "auto" else float(size))

    @classmethod
    def from_node(cls, node):
        attrs = dict(node.attributes)
        return cls.from_fields(attrs["x"], attrs["y"], attrs["size"])

    def __post_init__(self):
        if not (0 <= self.x <= 100 and 0 <= self.y <= 100):
            raise ValueError("图片标注位置须在图片范围内。")
        if self.em_mm is not None and not 1 <= self.em_mm <= 100:
            raise ValueError("图片标注字号须为 1–100 mm。")

    @property
    def position(self):
        return f"{self.x:.6f} {self.y:.6f}"

    def source_line(self, text):
        text = text.strip()
        validate_label_text(text)
        size = "auto" if self.em_mm is None else f"{self.em_mm:.6f}"
        return f"{PREFIX}{self.position} {size} | {text} -->"


def validate_label_text(text):
    if not text or len(text) > MAX_LABEL_LENGTH or any(ord(char) < 32 for char in text):
        raise ValueError(f"图片标注须为 1–{MAX_LABEL_LENGTH} 个字符的单行文字。")
    if "<!--" in text or "-->" in text:
        raise ValueError("图片标注不能包含 HTML 注释起止符。")


def bind_image_labels(nodes, diagnostics):
    """Collect adjacent labels under their image while preserving their source spans."""
    result = []
    index = 0
    while index < len(nodes):
        node = nodes[index]
        index += 1
        if node.kind == "image_label":
            diagnostics.append(Diagnostic("image-label-orphan", "图片标注须紧跟独占一段的图片。", node.span))
            continue
        children = node.children
        image = None
        if node.kind == "paragraph" and len(children) == 1 and children[0].kind == "inline":
            inline = children[0]
            if len(inline.children) == 1 and inline.children[0].kind == "image":
                image = inline.children[0]
        if image is not None:
            labels = []
            while index < len(nodes) and nodes[index].kind == "image_label":
                labels.append(nodes[index])
                index += 1
            if labels:
                image = replace(image, children=(*image.children, *labels))
                node = replace(node, children=(replace(inline, children=(image,)),))
        elif children:
            node = replace(node, children=bind_image_labels(children, diagnostics))
        result.append(node)
    return tuple(result)
