from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass

from ..assets.glyph_provider import GlyphAsset, GlyphProvider, is_han
from ..document.schema import Diagnostic, Document, Occurrence, SourceSpan, digest, new_id
from ..document.source import SEGMENTATION_VERSION
from ..scene.schema import Fragment, LayoutSnapshot, Page, PaintOp

LAYOUT_VERSION = "plain-greedy-kinsoku-subset-v1"
OPENING = frozenset("（［｛〈《「『【〔〖〘〚([{“‘")
CLOSING = frozenset("）］｝〉》」』】〕〗〙〛)]}”’、。，．：；？！,.:;?!%％")
BREAKS = ("\r", "\n", "\r\n")
SPACES = (" ", "\t", "\u3000", "\u00a0")


@dataclass(frozen=True)
class Measured:
    occurrence: Occurrence
    advance: float
    ascent: float
    descent: float
    asset: GlyphAsset | None
    status: str


def legal_break(left: str, right: str) -> bool:
    if left in OPENING or right in CLOSING or "\u00a0" in (left, right):
        return False
    if left in (" ", "\t", "\u3000"):
        return True
    # Keep Latin words and numeric/unit runs atomic. This intentionally supports
    # only a documented subset, not every Unicode line-break class.
    if all(len(t) == 1 and (t.isascii() and (t.isalnum() or t in "_./-")) for t in (left, right)):
        return False
    return not (left.isdecimal() and (right.isalpha() or right in ("%", "％", "°")))


def _measure(document: Document, provider: GlyphProvider):
    em, radius = document.style.em_mm, document.style.stroke_width_mm / 2
    result, diagnostics = {}, []
    for o in document.occurrences:
        asset = provider.assets.get(o.text)
        ascent, descent = 0.88 * em + radius, 0.12 * em + radius
        status, advance = "ready", em
        if o.text in BREAKS:
            status, advance = "line-break", 0.0
        elif o.text in SPACES:
            status = "space"
            advance = em * {" ": 0.5, "\u00a0": 0.5, "\t": 2, "\u3000": 1}[o.text]
        elif (
            len(o.text) != 1
            or unicodedata.category(o.text)[0] in "CM"
            or unicodedata.bidirectional(o.text) in ("R", "AL", "AN")
            or not (is_han(o.text) or o.text.isascii() or o.text in OPENING | CLOSING)
        ):
            status, asset = "unsupported", None
            diagnostics.append(
                Diagnostic(
                    "unsupported-cluster",
                    f"This text cluster/script is not supported: {o.text!r}",
                    o.span,
                )
            )
        elif asset:
            m = asset.metrics
            advance = m.advance * em
            ascent = max(m.ascent, m.baseline - asset.centerline_bounds[1]) * em + radius
            descent = max(m.descent, asset.centerline_bounds[3] - m.baseline) * em + radius
        else:
            status = "failed" if o.text in provider.failures else "missing"
            diagnostics.append(
                Diagnostic(
                    "asset-" + status,
                    provider.failures.get(o.text, f"No trajectory asset for {o.text!r}"),
                    o.span,
                )
            )
        result[o.occurrence_id] = Measured(o, advance, ascent, descent, asset, status)
    return result, diagnostics


def _lines(items: list[Measured], width: float):
    if not items:
        yield []
        return
    start = 0
    while start < len(items):
        used = 0.0
        last_fit = None
        end = start
        while end < len(items):
            used += items[end].advance
            end += 1
            legal = (
                end == len(items)
                or items[end].occurrence.text in BREAKS
                or legal_break(items[end - 1].occurrence.text, items[end].occurrence.text)
            )
            if used <= width + 1e-9 and legal:
                last_fit = end
            if used > width + 1e-9:
                if last_fit is not None:
                    end = last_fit
                    break
                if legal:
                    break  # Consume the overwide atomic run once; never retry an empty page.
        # Attach a hard break to the previous line even at exact content width.
        if end < len(items) and items[end].occurrence.text in BREAKS:
            end += 1
        yield items[start:end]
        start = end


def layout_document(
    document: Document, provider: GlyphProvider, *, request_id: str | None = None
) -> LayoutSnapshot:
    measurements, diagnostics = _measure(document, provider)
    profile, style = document.page, document.style
    margin, radius = profile.margin_mm, style.stroke_width_mm / 2
    width = profile.width_mm - 2 * margin - 2 * radius
    if width <= 0:
        raise ValueError("The brush leaves no usable page width")
    page_fragments: list[list[Fragment]] = [[]]
    page_ops: list[list[PaintOp]] = [[]]
    y, line_index, lines_on_page = margin, 0, 0
    for node in document.nodes:
        items = [measurements[o.occurrence_id] for o in node.occurrences]
        for line in _lines(items, width):
            ascent = max([0.88 * style.em_mm + radius] + [m.ascent for m in line])
            descent = max([0.12 * style.em_mm + radius] + [m.descent for m in line])
            height = max(style.line_height_mm, ascent + descent)
            span = (
                SourceSpan(line[0].occurrence.span.start, line[-1].occurrence.span.end)
                if line
                else node.span
            )
            if y + height > profile.height_mm - margin + 1e-9 and lines_on_page:
                page_fragments.append([])
                page_ops.append([])
                y, lines_on_page = margin, 0
            if height > profile.height_mm - 2 * margin + 1e-9:
                diagnostics.append(
                    Diagnostic(
                        "line-height-overflow", "The line is taller than an empty page", span
                    )
                )
            if sum(m.advance for m in line) > width + 1e-9:
                diagnostics.append(
                    Diagnostic(
                        "line-width-overflow", "An unbreakable run exceeds the content width", span
                    )
                )
            visible = [m for m in line if m.occurrence.text not in BREAKS + SPACES]
            if visible and (
                visible[0].occurrence.text in CLOSING or visible[-1].occurrence.text in OPENING
            ):
                diagnostics.append(
                    Diagnostic(
                        "forbidden-line-boundary",
                        "A hard boundary leaves opening/closing punctuation in a forbidden position",
                        span,
                    )
                )
            baseline = y + (height - ascent - descent) / 2 + ascent
            x = margin + radius
            page_index = len(page_fragments) - 1
            for m in line:
                o, asset = m.occurrence, m.asset
                ink = None
                if asset:
                    top = baseline - asset.metrics.baseline * style.em_mm
                    bounds = asset.centerline_bounds
                    ink = (
                        x + bounds[0] * style.em_mm - radius,
                        top + bounds[1] * style.em_mm - radius,
                        x + bounds[2] * style.em_mm + radius,
                        top + bounds[3] * style.em_mm + radius,
                    )
                    if (
                        ink[0] < margin - 1e-9
                        or ink[1] < margin - 1e-9
                        or ink[2] > profile.width_mm - margin + 1e-9
                        or ink[3] > profile.height_mm - margin + 1e-9
                    ):
                        diagnostics.append(
                            Diagnostic(
                                "ink-overflow", "Ink extends outside the page content area", o.span
                            )
                        )
                    for stroke in asset.strokes:
                        page_ops[-1].append(
                            PaintOp(
                                o.occurrence_id,
                                tuple(
                                    (x + p.x * style.em_mm, top + p.y * style.em_mm) for p in stroke
                                ),
                                style.stroke_width_mm,
                            )
                        )
                elif m.status in ("missing", "failed", "unsupported"):
                    # Explicit red debug placeholder; it can never pass the export gate.
                    top = baseline - 0.88 * style.em_mm
                    points = (
                        (x, top),
                        (x + m.advance, top),
                        (x + m.advance, top + style.em_mm),
                        (x, top + style.em_mm),
                        (x, top),
                    )
                    page_ops[-1].append(PaintOp(o.occurrence_id, points, 0.2, "#dc2626"))
                page_fragments[-1].append(
                    Fragment(
                        new_id(),
                        o.occurrence_id,
                        o.node_id,
                        o.span,
                        o.text,
                        page_index,
                        line_index,
                        x,
                        baseline,
                        m.advance,
                        (x, baseline - m.ascent, x + m.advance, baseline + m.descent),
                        ink,
                        asset.asset_id if asset else None,
                        m.status,
                    )
                )
                x += m.advance
            y += height
            lines_on_page += 1
            line_index += 1
    pages = tuple(
        Page(i, tuple(fs), tuple(ops))
        for i, (fs, ops) in enumerate(zip(page_fragments, page_ops, strict=True))
    )
    covered = tuple(f.occurrence_id for p in pages for f in p.fragments)
    if covered != tuple(o.occurrence_id for o in document.occurrences):
        raise RuntimeError("Layout coverage invariant violated")
    job_key = digest(
        {
            "document": asdict(document),
            "resources": provider.resource_key,
            "segmentation": SEGMENTATION_VERSION,
            "layout": LAYOUT_VERSION,
            "request_id": request_id or new_id(),
        }
    )
    return LayoutSnapshot(
        new_id(),
        job_key,
        document.document_id,
        document.revision,
        profile,
        pages,
        tuple(diagnostics),
        provider.resource_key,
        LAYOUT_VERSION,
    )
