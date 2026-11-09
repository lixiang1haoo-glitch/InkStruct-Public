from __future__ import annotations

import base64
import io
import json
import math
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path

from ..document.limits import validate_snapshot
from ..scene.schema import LayoutSnapshot

PREVIEW_VERSION = "page-svg-preview-v1"


@dataclass(frozen=True)
class _PreviewKey:
    # Keep full immutable content for equality; hash collisions never imply a hit.
    content: tuple
    _hash: int = field(init=False, compare=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "_hash", hash(self.content))

    def __hash__(self):
        return self._hash


def preview_key(snapshot, page_index, *, debug=False):
    """Current page content, independent of request revision or overlay marks."""
    _export_gate(snapshot, debug)
    return _PreviewKey(
        (PREVIEW_VERSION, repr(snapshot.page_profile), snapshot.pages[page_index], bool(debug))
    )


def _export_gate(snapshot: LayoutSnapshot, debug: bool) -> None:
    validate_snapshot(snapshot)
    if not snapshot.exportable and not debug:
        raise ValueError("Unresolved document errors block finished export")


def page_svg(snapshot: LayoutSnapshot, page_index: int, *, debug: bool = False) -> str:
    _export_gate(snapshot, debug)
    p = snapshot.page_profile
    page = snapshot.pages[page_index]
    lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{p.width_mm}mm" '
            f'height="{p.height_mm}mm" viewBox="0 0 {p.width_mm} {p.height_mm}">'
        ),
        f'<rect width="{p.width_mm}" height="{p.height_mm}" fill="white"/>',
    ]
    if page.background:
        lines.append(
            f'<image x="0" y="0" width="{p.width_mm}" height="{p.height_mm}" '
            f'preserveAspectRatio="none" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'xlink:href="data:image/png;base64,{page.background.png_base64}"/>'
        )
    for reference in page.images:
        x, y, right, bottom = reference.bounds
        width, height = right - x, bottom - y
        if reference.png_base64:
            lines.append(
                f'<image x="{x:.6f}" y="{y:.6f}" width="{width:.6f}" height="{height:.6f}" '
                f'preserveAspectRatio="none" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'data-plotter-ready="false" xlink:href="data:image/png;base64,{reference.png_base64}"/>'
            )
        else:
            lines.append(
                f'<rect x="{x:.6f}" y="{y:.6f}" width="{width:.6f}" height="{height:.6f}" fill="#fff1f2" stroke="#dc2626" stroke-width="0.2"/>'
            )
    if page.images:
        lines.append(
            '<text x="2" y="4" font-size="2.3" fill="#9a3412">RASTER REFERENCE PAGE - NOT PLOTTER READY</text>'
        )
    for op in (*page.preview_ops, *page.paint_ops):
        attrs = (
            f'fill="none" stroke="{escape(op.color, quote=True)}" '
            f'stroke-width="{op.width_mm:.6f}" stroke-linecap="round" '
            f'stroke-linejoin="round" data-occurrence="{escape(op.occurrence_id, quote=True)}"'
        )
        if len(op.points) == 1:
            x, y = op.points[0]
            lines.append(
                f'<circle cx="{x:.6f}" cy="{y:.6f}" r="{op.width_mm / 2:.6f}" '
                f'fill="{op.color}" data-occurrence="{escape(op.occurrence_id, quote=True)}"/>'
            )
        else:
            points = " ".join(map("%.6f,%.6f".__mod__, op.points))
            lines.append(f'<polyline points="{points}" {attrs}/>')
    if debug:
        lines.append(
            '<text x="2" y="4" font-size="3" fill="#dc2626">'
            "DEBUG PREVIEW - NOT A FINISHED EXPORT</text>"
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def page_png(snapshot: LayoutSnapshot, page_index: int, *, dpi: float = 144, debug: bool = False):
    from PIL import Image, ImageDraw

    _export_gate(snapshot, debug)
    if not math.isfinite(dpi) or dpi <= 0:
        raise ValueError("DPI must be finite and positive")
    scale = dpi / 25.4
    profile = snapshot.page_profile
    if profile.width_mm * profile.height_mm * scale * scale > 40_000_000:
        raise ValueError("PNG exceeds the 40 million pixel page budget; lower DPI")
    width, height = math.ceil(profile.width_mm * scale), math.ceil(profile.height_mm * scale)
    if width * height > 40_000_000:
        raise ValueError("PNG exceeds the 40 million pixel page budget; lower DPI")
    image = Image.new("RGB", (width, height), "white")
    page = snapshot.pages[page_index]
    if page.background:
        with Image.open(io.BytesIO(page.background.png_bytes())) as reference:
            reference = reference.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
            image.paste(reference, (0, 0), reference)
    draw = ImageDraw.Draw(image)
    for reference in page.images:
        x, y, right, bottom = reference.bounds
        box = (round(x * scale), round(y * scale), round(right * scale), round(bottom * scale))
        if reference.png_base64:
            size = (max(1, box[2] - box[0]), max(1, box[3] - box[1]))
            if size[0] * size[1] > 40_000_000:
                raise ValueError("Image render exceeds pixel budget")
            with Image.open(io.BytesIO(base64.b64decode(reference.png_base64))) as reference_image:
                raster = reference_image.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
                image.paste(raster, box[:2], raster)
        else:
            draw.rectangle(box, fill="#fff1f2", outline="#dc2626")
    for op in (*page.preview_ops, *page.paint_ops):
        points = [(x * scale, y * scale) for x, y in op.points]
        stroke_width = max(1, round(op.width_mm * scale))
        if len(points) > 1:
            draw.line(points, fill=op.color, width=stroke_width, joint="curve")
        radius = stroke_width / 2
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=op.color)
    if debug:
        draw.text((8, 8), "DEBUG PREVIEW - NOT A FINISHED EXPORT", fill="#dc2626")
    elif page.images:
        draw.text((8, 8), "RASTER REFERENCE PAGE - NOT PLOTTER READY", fill="#9a3412")
    return image


def export_pages(
    snapshot: LayoutSnapshot,
    output: Path,
    *,
    png: bool = True,
    dpi: float = 144,
    debug: bool = False,
) -> Path:
    """Publish a complete new directory. A failed export never damages old output."""
    _export_gate(snapshot, debug)
    if output.exists():
        raise FileExistsError(f"Use a new output directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".inkstruct-pages-", dir=output.parent))
    try:
        for page in snapshot.pages:
            stem = f"{'debug-' if debug else ''}page-{page.index + 1:03d}"
            (staging / f"{stem}.svg").write_text(
                page_svg(snapshot, page.index, debug=debug), encoding="utf-8"
            )
            if png:
                page_png(snapshot, page.index, dpi=dpi, debug=debug).save(
                    staging / f"{stem}.png", dpi=(dpi, dpi)
                )
        report = {
            "kind": "debug-preview"
            if debug
            else "reference-pages"
            if not snapshot.plotter_exportable
            else "finished-pages",
            "exportable": snapshot.exportable,
            "plotter_exportable": snapshot.plotter_exportable,
            "snapshot": asdict(snapshot),
        }
        (staging / "layout.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output
