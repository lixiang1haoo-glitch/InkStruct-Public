"""Opt-in whole-glyph frame calibration without changing stroke representation.

No rotation, independent stroke warp, smoothing, point removal or target capture
is involved. This module is deliberately not imported by the production entry.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import asdict

import numpy as np

from .contextual_trajectory import fit_shared_similarity
from .trajectory_experiment import SharedTransform, invariants

POLICY = "v6_shared_glyph_frame_v1"
MIN_CHARACTERS = 8


def reference_frame(graph):
    """Match the public frame to the existing capture normalization (extent .85)."""
    xy = np.asarray([p for s in graph.strokes for p in s.median], dtype=float)
    if not len(xy) or not np.isfinite(xy).all():
        raise ValueError("invalid reference frame")
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = float(max(hi - lo))
    if span <= 1e-9:
        raise ValueError("degenerate reference frame")
    scale = .85 / span
    offset = .5 - scale * (hi + lo) / 2
    return SharedTransform(scale, scale, float(offset[0]), float(offset[1]))


def compose(first, second):
    return SharedTransform(first.sx * second.sx, first.sy * second.sy,
                           first.tx * second.sx + second.tx,
                           first.ty * second.sy + second.ty)


class GlyphFrameEvidence:
    """Robust three-parameter writer summary, with one vote per training character."""

    def __init__(self, sources, repository, *, excluded_characters=()):
        excluded = set(excluded_characters)
        groups = defaultdict(list)
        self.rejected = []
        for source in sources.values():
            if source.character in excluded:
                continue
            try:
                graph = repository.get(source.character)
                mapping = {s.standard_stroke_id: s.points for s in source.strokes}
                frame = reference_frame(graph)
                t = fit_shared_similarity([frame.apply(s.median) for s in graph.strokes],
                                          [mapping[s.stroke_id] for s in graph.strokes])
                groups[source.character].append([t.sx, t.tx, t.ty])
            except (KeyError, ValueError) as error:
                self.rejected.append({"sample_id": source.sample_id, "reason": str(error)})
        self.groups = {c: np.median(v, axis=0) for c, v in groups.items()}

    def predict(self, character):
        # Defence in depth: exclude all repeats of the requested character even
        # if a caller supplies an archive that was not filtered beforehand.
        characters = sorted(set(self.groups) - {character})
        result = {"policy": POLICY, "training_characters": characters,
                  "character_count": len(characters), "target_excluded": character}
        if len(characters) < MIN_CHARACTERS:
            return {**result, "available": False, "reason": "fewer than eight training characters"}
        scale, tx, ty = map(float, np.median([self.groups[c] for c in characters], axis=0))
        # Measure shift at the glyph centre, not the intercept at coordinate zero.
        shift = np.array([tx, ty]) + .5 * (scale - 1)
        if not .75 <= scale <= 1.25 or np.linalg.norm(shift) > .15:
            return {**result, "available": False, "reason": "writer frame exceeds frozen bounds"}
        return {**result, "available": True,
                "transform": {"sx": scale, "sy": scale, "tx": tx, "ty": ty}}


def apply_glyph_frame(glyph, graph, *, evidence=None):
    """Transform a finished fixed-donor glyph, retaining every point and dynamic value."""
    transform = reference_frame(graph)
    prediction = None if evidence is None else evidence.predict(graph.character)
    if prediction and prediction["available"]:
        transform = compose(transform, SharedTransform(**prediction["transform"]))
    result = copy.deepcopy(glyph)
    for stroke in result.strokes:
        xy = transform.apply([(p.x, p.y) for p in stroke.points])
        for p, (x, y) in zip(stroke.points, xy, strict=True):
            p.x, p.y = float(x), float(y)
    errors = invariants(result, graph)
    detail = {"policy": POLICY, "transform": asdict(transform), "prediction": prediction,
              "applied": not errors, "errors": errors,
              "fallback_reason": "proposed frame violates output contract" if errors else None}
    if errors:
        return copy.deepcopy(glyph), detail
    result.generator += ":" + POLICY
    result.canvas_fit = detail
    return result, detail
