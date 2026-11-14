"""Measured Markdown inline boxes, shared by paragraphs and future cells."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..assets.glyph_provider import is_han
from ..assets.resolver import AssetResolver
from ..assets.symbol_provider import ResolvedGlyph
from ..document.break_commands import FLOW_BREAK_KINDS
from ..document.cancellation import (
    LayoutCancelled,  # noqa: F401 - compatibility re-export
    check_cancel,
)
from ..document.markdown import SemanticNode
from ..document.schema import Diagnostic, Occurrence, StyleProfile
from ..math.handwritten import MathBox, MathGlyph, measure_math
from ..math.schema import MathNode
from .measurement_cache import cached_measurement
from .plain import legal_break
from .punctuation import punctuation_bearings


@dataclass(frozen=True)
class InlineRun:
    occurrence: Occurrence
    kind: str = "text"
    underline: bool = False
    strike: bool = False
    role: str = "content"
    math: MathNode | None = None
    footnote: tuple[Occurrence, ...] = ()


@dataclass(frozen=True)
class InlineBox:
    run: InlineRun
    advance: float
    ascent: float
    descent: float
    em: float
    origin_offset: float
    glyph: ResolvedGlyph | None
    status: str
    math: MathBox | None = None


def inline_runs(node: SemanticNode, *, underline=False, strike=False):
    underline = underline or node.kind in {"em", "strong"}
    strike = strike or node.kind == "s"
    if node.kind == "break_command_error":
        return []
    if node.kind in FLOW_BREAK_KINDS:
        attrs = dict(node.attributes)
        if attrs.get("blocked") == "true" or attrs.get("strength", "4") != "4":
            return []
        return [InlineRun(Occurrence(node.node_id, node.node_id, node.span, "\f"), node.kind)]
    if node.kind == "footnote_reference" and node.occurrences:
        occurrence = Occurrence(node.node_id + ":reference", node.node_id, node.span, "\ufffc")
        return [InlineRun(occurrence, "footnote_reference", footnote=node.occurrences)]
    if node.kind in {"math_inline", "math_block"} and node.math:
        occurrence = Occurrence(node.node_id + ":math", node.node_id, node.span, "\ufffc")
        return [InlineRun(occurrence, node.kind, underline, strike, math=node.math)]
    if node.kind in {
        "text",
        "text_special",
        "code_inline",
        "softbreak",
        "hardbreak",
        "break_hint",
        "wiki_link",
        "wiki_embed",
    }:
        return [InlineRun(o, node.kind, underline, strike) for o in node.occurrences]
    if node.kind in {"inline", "em", "strong", "s", "link"}:
        return [
            r
            for child in node.children
            for r in inline_runs(child, underline=underline, strike=strike)
        ]
    # Retain an actionable placeholder for every unsupported inline element.
    occurrence = Occurrence(
        node.node_id + ":unsupported", node.node_id, node.span, node.raw_content[:24] or node.kind
    )
    return [InlineRun(occurrence, "unsupported")]


@cached_measurement
def measure_runs(
    runs,
    resolver: AssetResolver,
    style: StyleProfile,
    *,
    scale=1,
    cancelled=None,
    character_em=None,
    math_style=None,
    math_width=None,
    footnote_style=None,
    latin_spacing="capture",
    punctuation_spacing="capture",
    han_spacing="full",
    digits_follow_latin=False,
    han_variation=None,
):
    boxes, diagnostics = [], []
    em, radius = style.em_mm * scale, style.stroke_width_mm / 2
    for index, run in enumerate(runs):
        check_cancel(cancelled)
        o = run.occurrence
        if run.footnote:
            from ..document.footnote_style import FootnoteStyle

            note_style = footnote_style or FootnoteStyle()
            # One unbreakable raised box, using selected centreline digits. The
            # composite shares the math-box placement contract, not math syntax
            # or the separately configurable formula font size.
            children, issues = measure_runs(
                [InlineRun(o) for o in run.footnote],
                resolver,
                style,
                scale=scale * note_style.reference_scale,
                cancelled=cancelled,
                latin_spacing=latin_spacing,
                punctuation_spacing=punctuation_spacing,
                han_spacing=han_spacing,
            )
            reference_em = style.em_mm * scale * note_style.reference_scale
            rise = style.em_mm * scale * note_style.reference_raise_em
            if reference_em < style.stroke_width_mm * 6:
                issues.append(
                    Diagnostic(
                        "footnote-size-limit",
                        "Footnote reference is too small for the selected pen width",
                        o.span,
                    )
                )
            glyphs, x = [], 0
            for child in children:
                glyphs.append(
                    MathGlyph(
                        child.run.occurrence,
                        child.glyph,
                        x,
                        -rise,
                        child.em,
                        child.advance,
                        child.origin_offset,
                        child.ascent,
                        child.descent,
                        child.status,
                    )
                )
                x += child.advance
            measured = MathBox(
                x,
                max(b.ascent + rise for b in children),
                max(0, max(b.descent - rise for b in children)),
                0,
                tuple(glyphs),
                diagnostics=tuple(issues),
            )
            diagnostics.extend(issues)
            boxes.append(
                InlineBox(
                    run,
                    measured.width,
                    measured.ascent,
                    measured.descent,
                    reference_em,
                    0,
                    None,
                    "ready" if measured.ready else "unsupported",
                    measured,
                )
            )
            continue
        if run.math:
            measured = measure_math(
                run.math,
                resolver,
                owner=o.node_id,
                style=math_style,
                stroke_width=style.stroke_width_mm,
                scale=scale,
                cancel_check=lambda: check_cancel(cancelled),
                display=run.kind == "math_block",
                available_width=math_width if run.kind == "math_block" else None,
            )
            diagnostics.extend(measured.diagnostics)
            boxes.append(
                InlineBox(
                    run,
                    measured.width,
                    measured.ascent,
                    measured.descent + (style.stroke_width_mm + 0.5 if run.underline else 0),
                    (math_style.em_mm if math_style else 6) * scale,
                    0,
                    None,
                    "ready" if measured.ready else "unsupported",
                    measured,
                )
            )
            continue
        em = (
            (character_em or {}).get(o.text, style.em_mm) * scale
            if run.kind != "code_inline"
            else style.em_mm * scale
        )
        glyph, status, advance, offset = None, "ready", em, radius
        ascent, descent = 0.88 * em + radius, 0.12 * em + radius
        if run.kind == "break_hint":
            status, advance = "break-hint", 0
        elif run.kind == "hardbreak":
            status, advance = "line-break", 0
        elif run.kind == "softbreak":
            cjk = (
                0 < index < len(runs) - 1
                and is_han(runs[index - 1].occurrence.text)
                and is_han(runs[index + 1].occurrence.text)
            )
            status, advance = "space", 0 if cjk else em * 0.5
        elif o.text.isspace():
            status = "space"
            advance = em * (1 if o.text == "\u3000" else 2 if o.text == "\t" else 0.5)
        elif run.kind == "unsupported":
            status = "unsupported"
            diagnostics.append(
                Diagnostic("unsupported-inline", "Inline layout is not implemented", o.span)
            )
        else:
            try:
                glyph = resolver.resolve(o)
                bounds, metrics = glyph.layout_bounds, glyph.layout_metrics
                offset = radius + max(0, -bounds[0] * em)
                advance = max(metrics.advance, bounds[2]) * em + offset + radius
                compact_latin = (latin_spacing == "handwriting" and len(o.text) == 1 and o.text.isascii()
                                 and (o.text.isalpha() or (digits_follow_latin and o.text.isdigit())))
                compact_han = han_spacing == "handwriting" and is_han(o.text)
                if run.kind != "code_inline" and (compact_latin or compact_han):
                    # Retain size and baseline, placing the pen envelope with
                    # 0.04 em clearance on each side.
                    # Use the frozen optical frame so saved ink corrections do
                    # not get normalized away or applied a second time.
                    offset = radius + (0.04 - bounds[0]) * em
                    advance = (bounds[2] - bounds[0] + 0.08) * em + 2 * radius
                if punctuation_spacing == "handwriting" and run.kind != "code_inline":
                    bearings = punctuation_bearings(o.text, bounds, em, radius)
                    if bearings is not None:
                        advance, offset = bearings
                ascent = max(metrics.ascent, metrics.baseline - bounds[1]) * em + radius
                descent = max(metrics.descent, bounds[3] - metrics.baseline) * em + radius
                if glyph.machine_capability != "centerline":
                    diagnostics.append(
                        Diagnostic(
                            "point-adaptation-required",
                            "A source dot needs explicit machine adaptation",
                            o.span,
                        )
                    )
            except ValueError as error:
                status = "missing"
                diagnostics.append(Diagnostic("asset-missing", str(error), o.span))
        if run.underline:
            descent += style.stroke_width_mm + 0.5
        boxes.append(InlineBox(run, advance, ascent, descent, em, offset, glyph, status))
    # One fixed advance per inline-code node, including all spaces and wide glyphs.
    widths = {}
    for box in boxes:
        if box.run.kind == "code_inline":
            key = box.run.occurrence.node_id
            widths[key] = max(widths.get(key, box.em * 0.65), box.advance)
    from .han_variation import natural_metrics

    return natural_metrics([
        replace(b, advance=widths[b.run.occurrence.node_id]) if b.run.kind == "code_inline" else b
        for b in boxes
    ], han_variation, radius), diagnostics


def box_occurrences(box):
    return tuple(g.occurrence for g in box.math.glyphs) if box.math else (box.run.occurrence,)


def break_lines(boxes: list[InlineBox], width: float, *, first_width=None, cancelled=None):
    """Greedy legal breaks; overwide atomic runs consume input and are diagnosed later."""
    if not boxes:
        return [[]]
    result, start = [], 0
    while start < len(boxes):
        check_cancel(cancelled)
        limit = first_width if first_width is not None and start == 0 else width
        used, last_fit, end = 0, None, start
        while end < len(boxes):
            check_cancel(cancelled)
            box = boxes[end]
            used += box.advance
            end += 1
            if box.status == "line-break":
                break
            right = boxes[end] if end < len(boxes) else None
            legal = (
                right is None
                or box.status == "break-hint"
                or right.status in {"line-break", "break-hint"}
                or (
                    right.run.kind != "footnote_reference"
                    and legal_break(box.run.occurrence.text, right.run.occurrence.text)
                )
            )
            if used <= limit + 1e-9 and legal:
                last_fit = end
            if used > limit + 1e-9:
                if last_fit is not None:
                    end = last_fit
                    break
                if legal:
                    break
        if (
            end < len(boxes)
            and boxes[end].status == "line-break"
            and boxes[end - 1].status != "line-break"
        ):
            end += 1
        result.append(boxes[start:end])
        start = end
    if boxes[-1].status == "line-break":
        result.append([])
    return result
