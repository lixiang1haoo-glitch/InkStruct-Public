"""Explicit derived geometry from captured specimens; original assets stay immutable."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

from ..document.schema import Occurrence, digest


def sample_occurrence(node, owner, role, character, span=None):
    anchor = node.occurrence_id or digest([owner, node.kind, node.span.start, node.span.end])
    identity = f"{owner}:math-rule:{anchor}:{role}:sample:{ord(character):x}"
    return Occurrence(identity, owner, span or node.span, character)


def migrate_equation_choice(node, owner, role, character, resolver):
    """Preserve explicit choices from the first, offset-keyed bracket version."""
    if node.kind not in {"EquationTag", "EquationReference"} or not node.occurrence_id:
        return
    current = sample_occurrence(node, owner, role, character)
    legacy = sample_occurrence(replace(node, occurrence_id=None), owner, role, character)
    previous = resolver.selections.get(legacy.occurrence_id)
    if previous and current.occurrence_id not in resolver.selections:
        # Keep the old entry for historical source states and validate it via
        # resolve, including unavailable calibration or incompatible character.
        resolver.selections[current.occurrence_id] = replace(
            previous, occurrence_id=current.occurrence_id
        )


def migrate_equation_choices(document, resolver):
    for root in document.nodes:
        for formula in root.walk():
            if formula.math:
                for node in formula.math.walk():
                    if dict(node.attributes).get("parentheses") == "true":
                        for side, char in (("left", "("), ("right", ")")):
                            migrate_equation_choice(
                                node, formula.node_id, "delimiter-" + side, char, resolver
                            )


def _bounds(glyph):
    if glyph.machine_capability != "centerline":
        raise ValueError("Construction sample requires drawable centerline strokes")
    return glyph.bounds


def fraction_paths(glyph, *, width, axis, em, radius):
    left, top, right, bottom = _bounds(glyph)
    if right - left <= 1e-8:
        raise ValueError("Minus specimen has no horizontal extent")
    sx = (width - 2 * radius) / (right - left)
    centre = (top + bottom) / 2
    # Stretch only length. Preserve the sampled vertical waviness at this em.
    return tuple(
        tuple((radius + (x - left) * sx, axis + (y - centre) * em) for x, y in stroke)
        for stroke in glyph.strokes
    )


def delimiter_sample_paths(glyph, *, width, top, bottom, em, radius):
    left, high, right, low = _bounds(glyph)
    if low - high <= 1e-8:
        raise ValueError("Delimiter specimen has no vertical extent")
    sx = (width - 2 * radius) / (right - left) if right > left else 0
    if glyph.character in "|‖":
        sx = min(sx, em)  # Do not magnify a vertical stroke's tiny x jitter.
    offset = (width - (right - left) * sx) / 2
    sy = (bottom - top) / (low - high)
    return tuple(
        tuple((offset + (x - left) * sx, top + (y - high) * sy) for x, y in stroke)
        for stroke in glyph.strokes
    )


def radical_sample_paths(glyph, *, start, hook_width, width, bar_bottom, bottom, radius):
    left, top, right, low = _bounds(glyph)
    height = low - top
    if height <= 1e-8 or right - left <= 1e-8:
        raise ValueError("Radical specimen has no usable extent")
    # The stem/hook extends below the top band; the remaining right-hand
    # portion must be an overbar. One- and multi-stroke forms are both allowed.
    below = [x for stroke in glyph.strokes for x, y in stroke if y > top + 0.2 * height]
    split = max(below)
    bar_strokes = [
        s
        for s in glyph.strokes
        if max(y for _, y in s) <= top + 0.2 * height
        and max(x for x, _ in s) - min(x for x, _ in s) >= 0.3 * (right - left)
    ]
    stems = [s for s in glyph.strokes if s not in bar_strokes]
    if bar_strokes and stems:
        split = max(x for s in stems for x, _ in s)
    else:
        # A continuous root: locate the upper-band run containing its rightmost
        # endpoint. Its bend separates the rising stem from the overbar.
        stroke = max(glyph.strokes, key=lambda s: max(x for x, _ in s))
        j = max(range(len(stroke)), key=lambda i: stroke[i][0])
        a = b = j
        while a and stroke[a - 1][1] <= top + 0.2 * height:
            a -= 1
        while b + 1 < len(stroke) and stroke[b + 1][1] <= top + 0.2 * height:
            b += 1
        run = stroke[a : b + 1]
        dx, dy = run[-1][0] - run[0][0], run[-1][1] - run[0][1]
        length = (dx * dx + dy * dy) ** 0.5
        if length > 1e-8:
            distances = [abs(dx * (y - run[0][1]) - dy * (x - run[0][0])) / length for x, y in run]
            corner = (
                run[max(range(len(run)), key=distances.__getitem__)][0]
                if max(distances) > 0.03 * height
                else min(x for x, _ in run)
            )
            split = max(split, corner)
    cap = [y for stroke in glyph.strokes for x, y in stroke if x > split]
    if (
        split - left <= 1e-8
        or right - split < 0.2 * (right - left)
        or not cap
        or max(cap) > top + 0.25 * height
    ):
        raise ValueError(
            "Cannot identify the sampled radical overbar; use a reviewed sample or geometric construction"
        )
    sy = (bottom - bar_bottom) / (low - max(cap))
    cap_scale = (width - radius - start - radius - hook_width) / (right - split)
    if cap_scale <= 0 or sy <= 0:
        raise ValueError("Radical target frame is too small")

    def transform(x, y):
        xx = (
            (x - left) * hook_width / (split - left)
            if x <= split
            else hook_width + (x - split) * cap_scale
        )
        return start + radius + xx, bottom - (low - y) * sy

    result = []
    for stroke in glyph.strokes:
        points = [transform(*stroke[0])]
        for a, b in pairwise(stroke):
            # A breakpoint makes the piecewise affine map exact on crossing
            # segments without dropping, smoothing or joining captured strokes.
            if (a[0] - split) * (b[0] - split) < 0:
                t = (split - a[0]) / (b[0] - a[0])
                points.append(transform(split, a[1] + t * (b[1] - a[1])))
            points.append(transform(*b))
        result.append(tuple(points))
    return tuple(result)
