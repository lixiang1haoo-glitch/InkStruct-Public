"""Measure handwriting in a baseline-relative frame; no outlines or substitutions."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..assets.glyph_provider import is_han
from ..assets.symbol_provider import ResolvedGlyph
from ..document.schema import Diagnostic, Occurrence, SourceSpan, digest
from ..layout.measurement_cache import cached_measurement
from .constructions import accent_geometry, array_geometry
from .delimiters import delimiter_frame, delimiter_paths, node_delimiters
from .parser import BINARY, OPERATORS, RELATION
from .sample_constructions import (
    delimiter_sample_paths,
    fraction_paths,
    radical_sample_paths,
    sample_occurrence,
)
from .style import MathStyle

MATH_LAYOUT_VERSION = "handwritten-math-m5-constructions-v1/sample-constructions-v2/auto-scripts-v1/compact-digit-floor-v1/latex-arguments-v2/sampled-accents-v1/axis-delimiters-v3/break-commands-v1"


@dataclass(frozen=True)
class MathOutline:
    glyph_index: int
    character: str
    bounds: tuple[float, float, float, float]
    advance: float
    axis: float


@dataclass(frozen=True)
class MathDimension:
    key: str
    start: tuple[float, float]
    end: tuple[float, float]
    em: float
    requested: float | None = None
    label: str = ""
    note: str = ""

    @property
    def actual(self):
        return math.dist(self.start, self.end)

    def translated(self, x, y):
        return replace(self, start=(self.start[0] + x, self.start[1] + y),
                       end=(self.end[0] + x, self.end[1] + y))


@dataclass(frozen=True)
class MathGlyph:
    occurrence: Occurrence
    glyph: ResolvedGlyph | None
    x_mm: float
    baseline_mm: float
    em_mm: float
    advance_mm: float
    origin_offset_mm: float
    ascent_mm: float
    descent_mm: float
    status: str = "ready"
    outline: MathOutline | None = None


@dataclass(frozen=True)
class MathRule:
    occurrence_id: str
    span: SourceSpan
    points: tuple[tuple[float, float], ...]
    asset_id: str | None = None
    sample_id: str | None = None
    transform: str | None = None


@dataclass(frozen=True)
class MathBox:
    width: float
    ascent: float
    descent: float
    axis: float
    glyphs: tuple[MathGlyph, ...] = ()
    rules: tuple[MathRule, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    version: str = MATH_LAYOUT_VERSION
    dimensions: tuple[MathDimension, ...] = ()

    @property
    def ready(self):
        return not any(d.severity == "error" for d in self.diagnostics)


def ink_bounds(box, stroke_width):
    """Actual trajectory envelope including pen radius; metrics only for missing ink."""
    radius = stroke_width / 2
    bounds = []
    for g in box.glyphs:
        if g.glyph:
            left, top, right, bottom = g.glyph.bounds
            origin = g.x_mm + g.origin_offset_mm
            baseline = g.baseline_mm - g.glyph.metrics.baseline * g.em_mm
            bounds.append(
                (
                    origin + left * g.em_mm - radius,
                    baseline + top * g.em_mm - radius,
                    origin + right * g.em_mm + radius,
                    baseline + bottom * g.em_mm + radius,
                )
            )
        elif g.outline:
            left, top, right, bottom = g.outline.bounds
            origin = g.x_mm + g.origin_offset_mm
            bounds.append((origin + left * g.em_mm, g.baseline_mm + top * g.em_mm,
                           origin + right * g.em_mm, g.baseline_mm + bottom * g.em_mm))
        elif g.status != "space":
            bounds.append(
                (
                    g.x_mm,
                    g.baseline_mm - g.ascent_mm,
                    g.x_mm + g.advance_mm,
                    g.baseline_mm + g.descent_mm,
                )
            )
    for rule in box.rules:
        if rule.points:
            xs, ys = zip(*rule.points, strict=True)
            bounds.append((min(xs) - radius, min(ys) - radius, max(xs) + radius, max(ys) + radius))
    if not bounds:
        return (0, -box.ascent, box.width, box.descent)
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )


@cached_measurement
def measure_math(
    root,
    resolver,
    *,
    owner,
    style=None,
    stroke_width=0.3,
    scale=1,
    cancel_check=None,
    display=False,
    available_width=None,
    inspect=False,
    reference=None,
):
    style = style or MathStyle()
    if reference:
        style = replace(style, fraction_source="geometric", radical_source="geometric",
                        delimiter_source="geometric")
    compact = style.spacing_policy == "handwriting"
    em = style.em_mm * scale
    if not math.isfinite(em) or em <= 0 or not math.isfinite(stroke_width) or stroke_width <= 0:
        raise ValueError("Math em and stroke width must be finite and positive")
    if available_width is not None and (not math.isfinite(available_width) or available_width <= 0):
        raise ValueError("Available math width must be finite and positive")
    radius = stroke_width / 2
    duplicates = {}

    def empty(em, width=0):
        return MathBox(width, 0, 0, style.axis_em * em)

    def measured(box, *values):
        return replace(box, dimensions=(*values, *box.dimensions)) if inspect and values else box

    # Carry semantic style through the AST, without transforming recorded paths.
    style_requests = {}
    def styles_for(node, inherited="italic"):
        requested = ("upright" if node.kind in {"Operator", "Text"} or
                     dict(node.attributes).get("style") in {"mathrm", "text", "operatorname"} else inherited)
        style_requests[id(node)] = requested
        for child in node.children:
            styles_for(child, requested)
    styles_for(root)

    def symbol(node, em):
        count = duplicates.get(node.span, 0)
        duplicates[node.span] = count + 1
        identity = node.occurrence_id or digest(
            [owner, node.span.start, node.span.end, count, node.value]
        )
        occurrence = Occurrence(identity, owner, node.span, node.value)
        advance, offset, baseline = em, radius, 0
        ascent, descent = 0.88 * em + radius, 0.25 * em + radius
        glyph, outline, issues, status = None, None, [], "ready"
        if not reference and em < stroke_width * style.min_em_stroke_ratio:
            issues.append(
                Diagnostic(
                    "math-size-limit",
                    "Math symbol is too small for the selected pen width",
                    node.span,
                )
            )
        if node.value.isspace():
            advance, status = em * 0.5, "space"
        elif reference:
            try:
                outline = reference(node.value, style_requests[id(node)])
                left, top, right, bottom = outline.bounds
                if node.value in BINARY | RELATION | OPERATORS or node.value == "∘":
                    baseline = (outline.axis - style.axis_em) * em
                offset = max(0, -left * em)
                advance = max(outline.advance, right) * em + offset
                ascent, descent = max(0, -top * em), max(0, bottom * em)
            except ValueError as error:
                status = "missing"
                issues.append(Diagnostic("reference-glyph-missing", str(error), node.span))
        else:
            try:
                glyph = resolver.resolve(occurrence, letter_style=style_requests.get(id(node), "italic"))
                bounds, metrics = glyph.layout_bounds, glyph.layout_metrics
                if (node.value in BINARY | RELATION | OPERATORS
                        or (node.value == '∘' and glyph.font_core
                            and glyph.font_core['summary'].get('source_kind') == 'composed'
                            and glyph.math_axis_em is not None)):
                    axis = glyph.math_axis_em
                    if axis is None:
                        issues.append(
                            Diagnostic(
                                "math-axis-missing",
                                "Operator has no recorded math-axis guide",
                                node.span,
                            )
                        )
                    elif (
                        type(axis) not in (int, float)
                        or not math.isfinite(axis)
                        or not 0 <= axis <= 2
                    ):
                        issues.append(
                            Diagnostic(
                                "math-axis-invalid",
                                "Operator math-axis guide is invalid",
                                node.span,
                            )
                        )
                    else:
                        baseline = (axis - style.axis_em) * em
                offset = radius + max(0, -bounds[0] * em)
                advance = max(metrics.advance, bounds[2]) * em + offset + radius
                ascent = max(metrics.ascent, metrics.baseline - bounds[1]) * em + radius
                descent = max(metrics.descent, bounds[3] - metrics.baseline) * em + radius
                if compact:
                    # Keep the frozen correction frame, em, baseline and math axis.
                    # Capture position is not an optical side bearing.
                    if not is_han(node.value):
                        offset = radius + (.04 - bounds[0]) * em
                        advance = (bounds[2] - bounds[0] + .08) * em + 2 * radius
                        if node.value in "0123456789":
                            # A near-vertical 1 still needs a readable numeric cell.
                            # Match the table profile's minimum (0.45 x 0.7 em),
                            # retaining wider optical advances and centering only
                            # the extra space. Never resize the recorded strokes.
                            extra = max(0, .45 * .7 * em - advance)
                            offset += extra / 2
                            advance += extra
                    ascent = max(0, metrics.baseline - bounds[1]) * em + radius
                    descent = max(0, bounds[3] - metrics.baseline) * em + radius
                if glyph.machine_capability != "centerline":
                    issues.append(
                        Diagnostic(
                            "point-adaptation-required",
                            "Math symbol requires an explicit machine dot adapter",
                            node.span,
                        )
                    )
            except ValueError as error:
                status = "missing"
                issues.append(Diagnostic("asset-missing", str(error), node.span))
        placed = MathGlyph(
            occurrence, glyph, 0, baseline, em, advance, offset, ascent, descent, status, outline
        )
        return MathBox(
            advance,
            max(0, ascent - baseline),
            max(0, descent + baseline),
            style.axis_em * em,
            (placed,),
            diagnostics=tuple(issues),
        )

    def gap_key(left, right):
        if left is None or left == "open" or right == "close":
            return None
        if "rel" in (left, right):
            return "relation_gap_em"
        if "bin" in (left, right):
            return "binary_gap_em"
        if left == "punct" or "op" in (left, right):
            return "operator_gap_em"
        return None

    def gap(left, right, em):
        key = gap_key(left, right)
        return getattr(style, key) * em if key else 0

    def dimension(key, start, end, em, label="", note=""):
        return MathDimension(key, start, end, em, getattr(style, key) * em, label, note)

    def size_mark(key, x, y, em, child_em, note=""):
        return dimension(key, (x, y), (x, y - child_em), em, "字号", note)

    def combine(em, placements, rules=(), width=0):
        """Union conservative ink-inclusive boxes, retaining source traversal order."""
        glyphs, combined_rules, issues, dimensions = [], list(rules), [], []
        ascent = descent = 0
        for box, x, y in placements:
            glyphs.extend(
                replace(g, x_mm=g.x_mm + x, baseline_mm=g.baseline_mm + y) for g in box.glyphs
            )
            combined_rules.extend(
                replace(r, points=tuple((px + x, py + y) for px, py in r.points)) for r in box.rules
            )
            issues.extend(box.diagnostics)
            if inspect:
                dimensions.extend(d.translated(x, y) for d in box.dimensions)
            width = max(width, x + box.width)
            ascent, descent = max(ascent, box.ascent - y), max(descent, box.descent + y)
        for rule in combined_rules:
            width = max(width, max(x for x, _ in rule.points) + radius)
            ascent = max(ascent, -min(y for _, y in rule.points) + radius)
            descent = max(descent, max(y for _, y in rule.points) + radius)
        return MathBox(
            width,
            ascent,
            descent,
            style.axis_em * em,
            tuple(glyphs),
            tuple(combined_rules),
            tuple(issues),
            dimensions=tuple(dimensions),
        )

    def rule(node, role, points):
        identity = digest([owner, node.kind, role, node.span.start, node.span.end])
        return MathRule(f"{owner}:math-rule:{role}:{identity}", node.span, tuple(points))

    def sampled(node, role, character, transform, builder, span=None):
        occurrence = sample_occurrence(node, owner, role, character, span)
        identity = occurrence.occurrence_id
        try:
            glyph = resolver.resolve(occurrence, letter_style=style_requests.get(id(node), "italic"))
            paths = builder(glyph)
            return tuple(
                MathRule(
                    f"{identity}:stroke:{i}",
                    occurrence.span,
                    tuple(path),
                    glyph.asset_id,
                    glyph.sample_id,
                    transform,
                )
                for i, path in enumerate(paths)
            ), ()
        except ValueError as error:
            return None, (
                Diagnostic("math-construction-sample-invalid", str(error), occurrence.span),
            )

    def tight_vertical(box):
        if not compact:
            return box
        _, top, _, bottom = ink_bounds(box, stroke_width)
        return replace(box, ascent=max(0, -top), descent=max(0, bottom))

    def delimit(node, content, em, left, right):
        content = tight_vertical(content)
        clearance = max(style.delimiter_clearance_em * em, stroke_width * 1.5)
        top, bottom = delimiter_frame(
            ascent=content.ascent, descent=content.descent,
            axis=style.axis_em * em, em=em, radius=radius,
        )
        width = max(style.delimiter_width_em * em, 3 * stroke_width)

        def side_width(side, character):
            if character == ".":
                return 0
            if not compact or style.delimiter_source != "sample":
                return width
            factor = 1.2 if character in "{}" else .85 if character in "[]" else 1
            cap = max(style.delimiter_width_em * em * factor, 3 * stroke_width)
            if character in "|‖":
                cap = max((.12 if character == "|" else .24) * em, 2 * stroke_width)
            try:
                glyph = resolver.resolve(sample_occurrence(node, owner, "delimiter-" + side, character))
                l, t, r, b = glyph.bounds
                natural = (r - l) * (bottom - top) / (b - t) + 2 * radius if b > t else cap
                return min(cap, max(2 * radius + .04 * em, natural))
            except ValueError:
                # The sampled builder below retains the blocking diagnostic.
                return cap

        widths = {"left": side_width("left", left), "right": side_width("right", right)}
        left_width = widths["left"] + clearance if left != "." else 0
        right_width = widths["right"] + clearance if right != "." else 0
        rules, issues = [], []
        for side, character, x in (
            ("left", left, 0),
            ("right", right, left_width + content.width + clearance),
        ):
            target_width = widths[side]
            if style.delimiter_source == "sample" and character != ".":
                encoded_span = dict(node.attributes).get(side + "_span")
                span = (
                    SourceSpan(*(int(v) for v in encoded_span.split(":")))
                    if encoded_span
                    else node.span
                )
                paths, errors = sampled(
                    node,
                    "delimiter-" + side,
                    character,
                    "sample-delimiter-extensible-axis-v3",
                    lambda glyph, x=x, target_width=target_width: tuple(
                        tuple((px + x, py) for px, py in path)
                        for path in delimiter_sample_paths(
                            glyph, width=target_width, top=top, bottom=bottom, em=em, radius=radius
                        )
                    ),
                    span,
                )
                issues.extend(errors)
                if paths is not None:
                    rules.extend(paths)
                    continue
            for i, path in enumerate(
                delimiter_paths(character, width=target_width, top=top, bottom=bottom, radius=radius)
            ):
                item = rule(node, f"delimiter-{side}-{i}", tuple((px + x, py) for px, py in path))
                encoded_span = dict(node.attributes).get(side + "_span")
                if encoded_span:
                    item = replace(
                        item, span=SourceSpan(*(int(v) for v in encoded_span.split(":")))
                    )
                rules.append(item)
        result = combine(
            em, [(content, left_width, 0)], rules, left_width + content.width + right_width
        )
        if inspect and (left != "." or right != "."):
            x = 0 if left != "." else left_width + content.width + clearance
            span = widths["left" if left != "." else "right"]
            a = span if left != "." else x - clearance
            result = measured(result, dimension("delimiter_width_em", (x, top), (x + span, top),
                                               em, "构件槽宽", "紧凑录制模式使用样本比例与笔宽约束"),
                              dimension("delimiter_clearance_em", (a, 0), (a + clearance, 0),
                                        em, "构件槽至内容"))
        return replace(result, diagnostics=(*result.diagnostics, *issues))

    def visit(node, em, display_style=False):
        if cancel_check:
            cancel_check()
        if node.kind == "Symbol":
            if node.value in {"∫", "∮", "∑", "∏"} and style.large_operator_scale != 1:
                operator = symbol(node, em * style.large_operator_scale)
                shift = style.axis_em * em * (style.large_operator_scale - 1)
                result = combine(em, [(operator, 0, shift)])
                return measured(result, size_mark("large_operator_scale", 0, shift, em,
                                                  em * style.large_operator_scale)) if inspect else result
            if inspect and node.value in {"∫", "∮", "∑", "∏"}:
                return measured(symbol(node, em), size_mark("large_operator_scale", 0, 0, em, em))
            return symbol(node, em)
        if node.kind == "Space":
            return empty(
                em,
                {
                    "zero": 0,
                    "thin": 1 / 6,
                    "medium": 2 / 9,
                    "thick": 5 / 18,
                    "word": 0.5,
                    "quad": 1,
                    "qquad": 2,
                }[node.value]
                * em,
            )
        if node.kind == "Scripts":
            base = visit(node.children[0], em, display_style)
            operator = node.children[0]
            ratio = (
                style.limits_scale
                if operator.value in {"∫", "∮", "∑", "∏", "lim", "min", "max"}
                else style.script_scale
            )
            children = [visit(child, em * ratio) for child in node.children[1:]]
            roles = dict(node.attributes)
            size_key = ("limits_scale" if operator.value in {"∫", "∮", "∑", "∏", "lim", "min", "max"}
                        else "script_scale")
            sup = children[int(roles["sup"]) - 1] if "sup" in roles else None
            sub = children[int(roles["sub"]) - 1] if "sub" in roles else None
            # Edge-to-edge whitespace is automatic, separate from requested offsets.
            clearance = max(0.06 * em, stroke_width * 0.5)
            policy = dict(operator.attributes).get("limits")
            stacked = policy == "limits" or (
                policy != "nolimits"
                and display_style
                and operator.value in {"∑", "∏", "lim", "min", "max"}
            )
            if stacked:
                clearance = max(style.limits_clearance_em * em, stroke_width * 1.5)
                width = max([base.width] + [child.width for child in children])
                placements = [(base, (width - base.width) / 2, 0)]
                for index, box in enumerate(children, 1):
                    y = (
                        -base.ascent - clearance - box.descent
                        if roles.get("sup") == str(index)
                        else base.descent + clearance + box.ascent
                    )
                    placements.append((box, (width - box.width) / 2, y))
                result = combine(em, placements, width=width)
                if inspect:
                    for index, (box, x, y) in enumerate(placements[1:], 1):
                        above = roles.get("sup") == str(index)
                        a, b = ((-base.ascent, y + box.descent) if above
                                else (base.descent, y - box.ascent))
                        result = measured(result, size_mark(size_key, x, y, em, em * ratio),
                                          dimension("limits_clearance_em", (width, a), (width, b),
                                                    em, "上限" if above else "下限", "笔宽保护下限"))
                return result
            base_ink = ink_bounds(base, stroke_width)
            sup_ink = ink_bounds(sup, stroke_width) if sup else (0, 0, 0, 0)
            sub_ink = ink_bounds(sub, stroke_width) if sub else (0, 0, 0, 0)
            sup_y = min(
                -style.superscript_raise_em * em, -style.axis_em * em - clearance - sup_ink[3]
            )
            sub_y = max(style.subscript_drop_em * em, -sub_ink[1] - 0.15 * em)
            sup_y -= max(0, -base_ink[1] - (0.88 * em + radius))
            sub_y += max(0, base_ink[3] - (0.25 * em + radius))
            if sup and sub:
                sub_y = max(sub_y, sup_y + sup_ink[3] + clearance - sub_ink[1])
            placements = [(base, 0, 0)]
            for index, box in enumerate(children, 1):
                y = sup_y if roles.get("sup") == str(index) else sub_y
                script_ink = ink_bounds(box, stroke_width)
                # Position from ink, not advance width or a user-controlled vertical gap.
                x = max(0, base_ink[2] + clearance - script_ink[0])
                placements.append((box, x, y))
            result = combine(em, placements)
            if inspect:
                for index, (_box, x, y) in enumerate(placements[1:], 1):
                    key = "superscript_raise_em" if roles.get("sup") == str(index) else "subscript_drop_em"
                    result = measured(result, size_mark(size_key, x, y, em, em * ratio),
                                      dimension(key, (x, 0), (x, y), em, "基线位移",
                                                "按字形边界与笔宽避碰后的位置"))
            return result
        if node.kind == "Fraction":
            factor = 1 if dict(node.attributes).get("style") == "dfrac" else style.fraction_scale
            numerator, denominator = [tight_vertical(visit(child, em * factor)) for child in node.children]
            clearance = max(style.fraction_clearance_em * em, stroke_width * 1.5)
            width = max(numerator.width, denominator.width) + 2 * clearance
            axis = -style.axis_em * em
            line = rule(node, "fraction", ((radius, axis), (width - radius, axis)))
            lines, issues = (line,), ()
            if style.fraction_source == "sample":
                paths, issues = sampled(
                    node,
                    "fraction",
                    "−",
                    "sample-minus-length-v1",
                    lambda glyph: fraction_paths(
                        glyph, width=width, axis=axis, em=em, radius=radius
                    ),
                )
                if paths is not None:
                    lines = paths
            upper = min(y for line in lines for _, y in line.points)
            lower = max(y for line in lines for _, y in line.points)
            num_y = upper - radius - clearance - numerator.descent
            den_y = lower + radius + clearance + denominator.ascent
            result = combine(
                em,
                [
                    (
                        numerator,
                        (width - numerator.width) / 2,
                        num_y,
                    ),
                    (
                        denominator,
                        (width - denominator.width) / 2,
                        den_y,
                    ),
                ],
                lines,
                width,
            )
            if inspect:
                note = "按分数线实际边界、字形和笔宽测量"
                result = measured(
                    result,
                    size_mark("fraction_scale", (width - numerator.width) / 2, num_y, em,
                              em * factor, r"\dfrac 保持当前层字号" if factor == 1 and
                              dict(node.attributes).get("style") == "dfrac" else ""),
                    dimension("fraction_clearance_em",
                              (width, num_y + ink_bounds(numerator, stroke_width)[3]),
                              (width, upper - radius), em, "分子至线", note),
                    dimension("fraction_clearance_em", (width, lower + radius),
                              (width, den_y + ink_bounds(denominator, stroke_width)[1]),
                              em, "线至分母", note),
                )
            return replace(result, diagnostics=(*result.diagnostics, *issues))
        if node.kind == "Radical":
            indexed = dict(node.attributes).get("indexed") == "true"
            # Visit degree first to preserve the lexical occurrence order.
            degree = visit(node.children[0], em * style.script_scale) if indexed else None
            content = tight_vertical(visit(node.children[-1], em, display_style))
            clearance = max(style.radical_clearance_em * em, stroke_width * 1.5)
            start = degree.width + clearance if degree else 0
            hook_width = (0.46 if compact else 0.62) * em
            content_x = start + hook_width + clearance
            top = -content.ascent - clearance - radius
            width = content_x + content.width + 2 * radius
            line = rule(
                node,
                "radical",
                (
                    (start + radius, -0.15 * em),
                    (start + 0.16 * em + radius, -0.25 * em),
                    (start + 0.32 * em + radius, content.descent),
                    (start + hook_width + radius, top),
                    (width - radius, top),
                ),
            )
            lines, issues = (line,), ()
            if style.radical_source == "sample":
                paths, issues = sampled(
                    node,
                    "radical",
                    "√",
                    "sample-radical-compact-v2" if compact else "sample-radical-piecewise-v1",
                    lambda glyph: radical_sample_paths(
                        glyph,
                        start=start,
                        hook_width=hook_width,
                        width=width,
                        bar_bottom=top,
                        bottom=content.descent,
                        radius=radius,
                    ),
                )
                if paths is not None:
                    lines = paths
            placements = [(degree, 0, -0.55 * content.ascent - degree.descent)] if degree else []
            placements.append((content, content_x, 0))
            result = combine(em, placements, lines, width)
            if inspect:
                # The bar endpoint defines the underside of the overbar.
                bar_y = max(point for line in lines for point in line.points)[1] + radius
                ink_top = ink_bounds(content, stroke_width)[1]
                result = measured(result, dimension("radical_clearance_em", (width, bar_y),
                                                    (width, ink_top), em, "顶线至内容",
                                                    "按笔宽与内容边界测量"))
            return replace(result, diagnostics=(*result.diagnostics, *issues))
        if node.kind == "Delimited":
            attributes = dict(node.attributes)
            return delimit(
                node,
                visit(node.children[0], em, display_style),
                em,
                attributes["left"],
                attributes["right"],
            )
        if node.kind in {"EquationTag", "EquationReference"}:
            label_em = em * style.tag_scale if node.kind == "EquationTag" else em
            content = visit(node.children[0], label_em)
            if inspect and node.kind == "EquationTag":
                content = measured(content, size_mark("tag_scale", 0, 0, em, label_em))
            return (
                delimit(node, content, label_em, "(", ")")
                if dict(node.attributes).get("parentheses") == "true"
                else content
            )
        if node.kind == "Numbered":
            content = visit(node.children[0], em, True)
            tag = visit(node.children[1], em)
            clearance = max(style.tag_gap_em * em, 2 * stroke_width)
            width = max(content.width + clearance + tag.width, available_width or 0)
            tag_x = width - tag.width
            content_x = (
                0
                if style.display_align == "left"
                else min((width - content.width) / 2, tag_x - clearance - content.width)
            )
            result = combine(em, [(content, content_x, 0), (tag, tag_x, 0)], width=width)
            return measured(result, dimension("tag_gap_em", (content_x + content.width, 0),
                                              (tag_x, 0), em, "内容至编号",
                                              "含笔宽保护及编号对齐")) if inspect else result
        if node.kind == "Alignment":
            attributes = dict(node.attributes)
            gathered = attributes["environment"] in {"gathered", "gather*", "gather"}
            row_cells = [
                tuple(cell for cell in row.children if cell.kind != "EquationTag")
                for row in node.children
            ]
            tags = [
                next((visit(cell, em) for cell in row.children if cell.kind == "EquationTag"), None)
                for row in node.children
            ]
            rows = [[visit(cell, em, True) for cell in cells] for cells in row_cells]
            columns = max(len(row) for row in rows)
            if not gathered:
                columns += columns % 2
            rows = [row + [empty(em)] * (columns - len(row)) for row in rows]
            widths = [max(row[c].width for row in rows) for c in range(columns)]
            leading = [0.0] * columns
            if not gathered:
                for cells in row_cells:
                    for c, cell in enumerate(cells):
                        if c % 2 and cell.children:
                            leading[c] = max(
                                leading[c], gap("ord", cell.children[0].math_class, em)
                            )
            pair_gap = max(style.alignment_pair_gap_em * em, 2 * stroke_width)
            row_gap = max(style.alignment_row_gap_em * em, 2 * stroke_width)
            ascents = [max(0.88 * em + radius, *(cell.ascent for cell in row)) for row in rows]
            descents = [max(0.25 * em + radius, *(cell.descent for cell in row)) for row in rows]
            for r, tag in enumerate(tags):
                if tag:
                    ascents[r] = max(ascents[r], tag.ascent)
                    descents[r] = max(descents[r], tag.descent)
            content_width = sum(widths) + sum(leading) + pair_gap * ((columns - 1) // 2)
            width, content_x = content_width, 0
            if any(tags):
                tag_width = max(tag.width for tag in tags if tag)
                clearance = max(style.tag_gap_em * em, 2 * stroke_width)
                width = max(content_width + clearance + tag_width, available_width or 0)
                content_x = (
                    0
                    if style.display_align == "left"
                    else min(
                        (width - content_width) / 2, width - tag_width - clearance - content_width
                    )
                )
            height = sum(ascents) + sum(descents) + row_gap * (len(rows) - 1)
            position = attributes["position"]
            top = (
                -ascents[0]
                if position == "t"
                else descents[-1] - height
                if position == "b"
                else -style.axis_em * em - height / 2
            )
            placements, y, dimensions = [], top, []
            for r, row in enumerate(rows):
                x = content_x
                for c, cell in enumerate(row):
                    if c and c % 2 == 0:
                        if inspect and r == 0 and c == 2:
                            dimensions.append(dimension("alignment_pair_gap_em", (x, y),
                                                        (x + pair_gap, y), em, "等式组间距"))
                        x += pair_gap
                    x += leading[c]
                    offset = (
                        (widths[c] - cell.width) / 2
                        if gathered
                        else 0
                        if c % 2
                        else widths[c] - cell.width
                    )
                    placements.append((cell, x + offset, y + ascents[r]))
                    x += widths[c]
                if tags[r]:
                    placements.append((tags[r], width - tags[r].width, y + ascents[r]))
                    if inspect and not any(d.key == "tag_gap_em" for d in dimensions):
                        dimensions.append(dimension("tag_gap_em", (content_x + content_width, y),
                            (width - tags[r].width, y), em, "内容至编号"))
                y += ascents[r] + descents[r] + row_gap
                if inspect and r == 0 and len(rows) > 1:
                    dimensions.append(dimension("alignment_row_gap_em", (width, y - row_gap),
                                                (width, y), em, "行框净间距"))
            content = combine(em, placements, width=width)
            content = measured(content, *dimensions)
            return replace(
                content,
                ascent=max(content.ascent, -top),
                descent=max(content.descent, top + height),
            )
        if node.kind == "Accent":
            content = visit(node.children[0], em, display_style)
            placement, paths, width = accent_geometry(
                node.value, content, em=em, style=style, pen=stroke_width
            )
            lines = tuple(rule(node, f"accent-{i}", path) for i, path in enumerate(paths))
            issues = ()
            if node.value in {"bar", "overline", "underline"} and style.fraction_source == "sample":
                (left, y), (right, _) = paths[0]

                def accent_line(glyph):
                    sampled_paths = fraction_paths(
                        glyph, width=right - left + 2 * radius, axis=0, em=em, radius=radius
                    )
                    # Preserve waviness and place its closest ink edge at the
                    # clearance established for the geometric construction.
                    edge = (min if node.value == "underline" else max)(
                        py for path in sampled_paths for _, py in path
                    )
                    return tuple(
                        tuple((px + left - radius, py + y - edge) for px, py in path)
                        for path in sampled_paths
                    )

                sampled_lines, issues = sampled(
                    node, "accent-line", "−", "sample-minus-length-v1", accent_line
                )
                if sampled_lines is not None:
                    lines = sampled_lines
            result = combine(em, [placement], lines, width)
            if inspect:
                ys = [y for line in lines for _, y in line.points]
                a, b = min(ys), max(ys)
                _, top, _, bottom = ink_bounds(content, stroke_width)
                below = node.value == "underline"
                result = measured(result,
                    dimension("accent_height_em", (width, a), (width, b), em, "构件高度"),
                    dimension("accent_clearance_em", (width, bottom if below else top),
                              (width, a - radius if below else b + radius), em, "标记至内容"))
            return replace(result, diagnostics=(*result.diagnostics, *issues))
        if node.kind == "Array":
            rows = [
                [visit(cell, em) for cell in row.children]
                for row in node.children
                if row.kind == "ArrayRow"
            ]
            dimensions = []
            placements, lines, width, top, height = array_geometry(
                node, rows, em=em, style=style, pen=stroke_width,
                measure=(lambda key, a, b, label: dimensions.append(
                    dimension(key, a, b, em, label))) if inspect else None,
            )
            content = combine(
                em, placements, [rule(source, role, path) for source, role, path in lines], width
            )
            return replace(
                measured(content, *dimensions),
                ascent=max(content.ascent, -top),
                descent=max(content.descent, top + height),
            )
        if node.kind == "Matrix" and dict(node.attributes)["environment"] == "smallmatrix":
            ordinary = replace(
                node,
                attributes=tuple(
                    (key, "matrix" if key == "environment" else value)
                    for key, value in node.attributes
                ),
            )
            content = visit(ordinary, em * style.small_matrix_scale)
            shift = (style.small_matrix_scale - 1) * style.axis_em * em
            result = combine(em, [(content, 0, shift)])
            return measured(result, size_mark("small_matrix_scale", 0, shift, em,
                                              em * style.small_matrix_scale)) if inspect else result
        if node.kind == "Matrix":
            rows = [[visit(cell, em) for cell in row.children] for row in node.children]
            environment = dict(node.attributes)["environment"]
            widths = [max(em * 0.5, *(row[c].width for row in rows)) for c in range(len(rows[0]))]
            ascents = [max(em * 0.88 + radius, *(cell.ascent for cell in row)) for row in rows]
            descents = [max(em * 0.25 + radius, *(cell.descent for cell in row)) for row in rows]
            row_gap, col_gap = (
                max(em * style.matrix_row_gap_em, 2 * stroke_width),
                max(em * style.matrix_col_gap_em, 2 * stroke_width),
            )
            height = sum(ascents) + sum(descents) + row_gap * (len(rows) - 1)
            y = -style.axis_em * em - height / 2
            placements = []
            for r, row in enumerate(rows):
                x = 0
                for c, cell in enumerate(row):
                    offset = 0 if environment == "cases" else (widths[c] - cell.width) / 2
                    placements.append((cell, x + offset, y + ascents[r]))
                    x += widths[c] + col_gap
                y += ascents[r] + descents[r] + row_gap
            content = combine(em, placements, width=sum(widths) + col_gap * (len(widths) - 1))
            # Include empty cells in the row geometry too.
            content = replace(
                content,
                ascent=height / 2 + style.axis_em * em,
                descent=max(0, height / 2 - style.axis_em * em),
            )
            if inspect:
                if len(widths) > 1:
                    content = measured(content, dimension("matrix_col_gap_em", (widths[0], 0),
                                           (widths[0] + col_gap, 0), em, "列框净间距"))
                if len(rows) > 1:
                    row_bottom = placements[0][2] + descents[0]
                    content = measured(content, dimension("matrix_row_gap_em",
                        (content.width, row_bottom), (content.width, row_bottom + row_gap), em, "行框净间距"))
            left, right = node_delimiters(node)
            return delimit(node, content, em, left, right)
        if node.kind in {"Row", "Group", "Operator", "Text"}:
            x, ascent, descent, previous = 0, 0, 0, None
            glyphs, rules, issues, dimensions = [], [], [], []
            for child in node.children:
                box = visit(child, em, display_style)
                if node.kind == "Row" and child.kind != "Space":
                    key = gap_key(previous, child.math_class)
                    if key:
                        advance = getattr(style, key) * em
                        if inspect:
                            dimensions.append(dimension(key, (x, 0), (x + advance, 0), em,
                                                        "字框间的附加间距"))
                        x += advance
                    previous = child.math_class
                glyphs.extend(replace(g, x_mm=g.x_mm + x) for g in box.glyphs)
                rules.extend(
                    replace(r, points=tuple((px + x, py) for px, py in r.points)) for r in box.rules
                )
                issues.extend(box.diagnostics)
                if inspect:
                    dimensions.extend(d.translated(x, 0) for d in box.dimensions)
                x += box.width
                ascent = max(ascent, box.ascent)
                descent = max(descent, box.descent)
            return MathBox(
                x, ascent, descent, style.axis_em * em, tuple(glyphs), tuple(rules), tuple(issues),
                dimensions=tuple(dimensions),
            )
        occurrence = Occurrence(
            f"{owner}:unsupported:{node.span.start}:{node.span.end}", owner, node.span, node.kind
        )
        placeholder = MathGlyph(
            occurrence,
            None,
            0,
            0,
            em,
            em,
            radius,
            0.88 * em + radius,
            0.25 * em + radius,
            "unsupported",
        )
        return MathBox(
            em,
            placeholder.ascent_mm,
            placeholder.descent_mm,
            style.axis_em * em,
            (placeholder,),
            diagnostics=(
                Diagnostic(
                    "math-structure-pending",
                    f"{node.kind} handwriting geometry is not yet implemented",
                    node.span,
                ),
            ),
        )

    box = visit(root, em, display)
    if inspect:
        box = measured(box,
            MathDimension("em_mm", (0, 0), (0, -em), em, em, "公式字号"),
            dimension("axis_em", (box.width, 0), (box.width, -box.axis), em, "基线至数学轴"))
    if reference:
        return box
    # A preview/export is useful before machine calibration, but this warning must
    # remain explicit; it is not evidence that the writer's math-axis is reviewed.
    return replace(
        box,
        diagnostics=box.diagnostics
        + (
            Diagnostic(
                "math-calibration-unreviewed",
                "Mathematical metrics use capture guides; writer calibration is not reviewed",
                root.span,
                "warning",
            ),
        ),
    )
