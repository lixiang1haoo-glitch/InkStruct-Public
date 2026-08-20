from __future__ import annotations

from html import escape
from pathlib import Path

from .schemas import GeneratedGlyph


def render_svg(glyph: GeneratedGlyph, path: Path, size: int = 512) -> None:
    margin = size * 0.05
    scale = size - 2 * margin
    lines: list[str] = []
    for stroke in glyph.strokes:
        points = " ".join(
            f"{margin + point.x * scale:.2f},{margin + point.y * scale:.2f}"
            for point in stroke.points
        )
        lines.append(
            f'<polyline data-order="{stroke.order}" points="{points}" '
            'fill="none" stroke="#111827" stroke-width="4" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" aria-label="{escape(glyph.character)}">\n'
        '<rect width="100%" height="100%" fill="white"/>\n' + "\n".join(lines) + "\n</svg>\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def render_png(glyph: GeneratedGlyph, path: Path, size: int = 512) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("PNG preview requires Pillow") from error
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    margin = size * 0.05
    scale = size - 2 * margin
    for stroke in glyph.strokes:
        points = [(margin + point.x * scale, margin + point.y * scale) for point in stroke.points]
        if len(points) >= 2:
            draw.line(points, fill="#111827", width=max(2, size // 128), joint="curve")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
