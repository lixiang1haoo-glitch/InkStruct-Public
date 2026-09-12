"""Fit a complete glyph without clipping individual trajectory points."""

from __future__ import annotations

import math

from .schemas import GeneratedGlyph

BOUNDARY_POLICY = "whole_glyph_fit_v1"
BOUNDARY_EPSILON = 1e-9


def fit_glyph_to_canvas(glyph: GeneratedGlyph, margin: float = 0.02) -> GeneratedGlyph:
    """Preserve in-bounds coordinates; fit actual overflow with one similarity transform.

    Called before coordinate rounding, after all geometric operations. Pressure,
    time, stroke identity and point count are untouched. Boundary contact alone
    is valid and does not trigger fitting.
    """
    if not math.isfinite(margin) or not 0 <= margin < 0.5:
        raise ValueError("canvas margin must be finite and inside [0, 0.5)")
    points = [point for stroke in glyph.strokes for point in stroke.points]
    if not points or any(not math.isfinite(p.x) or not math.isfinite(p.y) for p in points):
        raise ValueError("cannot fit empty or non-finite glyph coordinates")
    x0, x1 = min(p.x for p in points), max(p.x for p in points)
    y0, y1 = min(p.y for p in points), max(p.y for p in points)
    overflow = max(0.0, -x0, -y0, x1 - 1, y1 - 1)
    scale, dx, dy = 1.0, 0.0, 0.0
    applied = overflow > BOUNDARY_EPSILON
    if applied:
        span = max(x1 - x0, y1 - y0)
        if not math.isfinite(span):
            raise ValueError("glyph extent exceeds finite coordinate range")
        scale = min(1.0, (1 - 2 * margin) / span) if span else 1.0
        # Minimal translation on each axis, rather than recentering every glyph.
        dx = max(margin - scale * x0, min(0.0, 1 - margin - scale * x1))
        dy = max(margin - scale * y0, min(0.0, 1 - margin - scale * y1))
    for point in points:
        point.x = round(scale * point.x + dx, 6)
        point.y = round(scale * point.y + dy, 6)
        if not 0 <= point.x <= 1 or not 0 <= point.y <= 1:
            raise ValueError("canvas fit failed to produce bounded coordinates")
    glyph.canvas_fit = {
        "policy": BOUNDARY_POLICY,
        "applied": applied,
        "original_bbox": [x0, y0, x1, y1],
        "max_overflow": overflow,
        "scale": scale,
        "translation": [dx, dy],
        "review_required": scale < 0.8 or max(abs(dx), abs(dy)) > 0.2,
    }
    return glyph
