"""Experimental whole-component placement with source-preserving spatial correction.

The target anchor is generated from a training-only style profile, never from
held-out handwriting. Every source point receives the same spatial map.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import bbox, resample
from .trajectory_experiment import SharedTransform


def anchors(strokes, count=16):
    if not strokes or any(len(s) < 2 for s in strokes):
        raise ValueError('complete nonempty component required')
    return np.asarray([resample(s, count) for s in strokes], dtype=float).reshape(-1, 2)


def fit_shared_similarity(source, target):
    """Equal stroke weight, positive scale and translation; no rotation or per-stroke fit."""
    if len(source) != len(target):
        raise ValueError('stroke count mismatch')
    x, y = anchors(source), anchors(target)
    xm, ym = x.mean(axis=0), y.mean(axis=0)
    xc, yc = x - xm, y - ym
    denominator = float(np.sum(xc * xc))
    if denominator < 1e-12 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('invalid component geometry')
    scale = float(np.sum(xc * yc) / denominator)
    if scale <= 1e-8:
        raise ValueError('incompatible component direction')
    offset = ym - scale * xm
    return SharedTransform(scale, scale, float(offset[0]), float(offset[1]))


def anchor_error(source, target):
    return float(np.linalg.norm(anchors(source) - anchors(target), axis=1).mean())


@dataclass
class SharedDisplacement:
    origin: np.ndarray
    span: float
    centers: np.ndarray
    coefficients: np.ndarray
    radius: float
    derivative_bound: float

    def weights(self, points):
        p = (np.asarray(points) - self.origin) / self.span
        logits = -np.sum((p[:, None] - self.centers) ** 2, axis=2) / (2 * self.radius ** 2)
        weights = np.exp(logits - logits.max(axis=1, keepdims=True))
        return weights / weights.sum(axis=1, keepdims=True)

    def apply(self, points):
        result = np.asarray(points) + self.weights(points) @ self.coefficients * self.span
        return [tuple(map(float, p)) for p in result]

    def metadata(self):
        return {'origin': self.origin.tolist(), 'span': self.span,
                'centers': self.centers.tolist(), 'coefficients': self.coefficients.tolist(),
                'radius': self.radius, 'derivative_bound': self.derivative_bound}


def fit_shared_displacement(source, target, strength=1.0, derivative_cap=0.25, ridge=0.005):
    """A single smooth Gaussian field, constrained to remain close to identity.

    For normalized Gaussian weights, ||dD/dp|| <= diameter(coefficients) *
    diameter(centers) / radius**2 globally. Capping below one guarantees the
    continuous map is injective, and bounds distance distortion. The output
    polyline still requires discrete crossing checks. No source vertex is lost.
    """
    if not 0 <= strength <= 1 or not 0 <= derivative_cap < 1 or ridge <= 0:
        raise ValueError('invalid field constraint')
    x, y = anchors(source), anchors(target)
    if x.shape != y.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('incompatible component anchors')
    box = bbox([tuple(p) for p in x])
    origin = np.array(box[:2])
    span = max(box[2] - box[0], box[3] - box[1])
    if span <= 1e-8:
        raise ValueError('degenerate component')
    centers = np.array([(a, b) for a in (0., .5, 1.) for b in (0., .5, 1.)])
    field = SharedDisplacement(origin, span, centers, np.zeros((9, 2)), .65, 0.)
    weights = field.weights(x)
    coefficients = np.linalg.solve(weights.T @ weights + len(x) * ridge * np.eye(9),
                                   weights.T @ ((y - x) / span))
    diameter = float(np.linalg.norm(coefficients[:, None] - coefficients, axis=2).max())
    center_diameter = float(np.linalg.norm(centers[:, None] - centers, axis=2).max())
    bound = diameter * center_diameter / field.radius ** 2
    factor = strength * min(1., derivative_cap / max(bound, 1e-12))
    field.coefficients = coefficients * factor
    field.derivative_bound = bound * factor
    return field


def place_component(source, target, *, field_strength=0.0):
    transform = fit_shared_similarity(source, target)
    placed = [transform.apply(s) for s in source]
    field = None
    if field_strength:
        field = fit_shared_displacement(placed, target, field_strength)
        placed = [field.apply(s) for s in placed]
    return placed, transform, field


def choose_component(base, graph, target_ids, candidates, sources, *, field_strength=0.0,
                     max_candidates=16):
    """Select a complete exemplar using only generated anchors and training donors.

    Returns (glyph, provenance). If every complete candidate fails, the exact
    original glyph object is returned. The caller owns any target evaluation.
    """
    from dataclasses import asdict

    from .geometry import path_length
    from .trajectory_experiment import assemble, crossing_pairs, invariants

    base_curves = [[(p.x, p.y) for p in s.points] for s in base.strokes]
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in target_ids]
    if len(indices) != len(target_ids) or not indices:
        raise ValueError('target component IDs must be unique and complete')
    target = [base_curves[i] for i in indices]
    base_crossings = crossing_pairs(base_curves)
    diagnostics, accepted = [], []
    for candidate in candidates[:max_candidates]:
        if candidate['character'] == graph.character:
            raise ValueError('cross-character pool contains target character')
        sample = sources[candidate['sample_id']]
        if sample.character != candidate['character'] or sample.source_sha256 != candidate['source_sha256']:
            raise ValueError('donor identity mismatch')
        source_map = {s.standard_stroke_id: s for s in sample.strokes}
        source = [source_map[k] for k in candidate['stroke_ids']]
        try:
            placed, transform, field = place_component([s.points for s in source], target,
                                                       field_strength=field_strength)
        except ValueError as exc:
            diagnostics.append({'candidate': candidate, 'errors': [str(exc)]})
            continue
        replacements = {i: {'points': p, 'pressure': s.pressure, 'time': s.t_ms}
                        for i, p, s in zip(indices, placed, source, strict=True)}
        glyph = assemble(base, replacements, 'contextual')
        predicted = [[(p.x, p.y) for p in s.points] for s in glyph.strokes]
        errors = invariants(glyph, graph)
        new_crossings = crossing_pairs(predicted) - base_crossings
        lengths = [path_length(p) / max(path_length(t), 1e-9)
                   for p, t in zip(placed, target, strict=True)]
        score = anchor_error(placed, target) + .01 * candidate['score']
        record = {'candidate': candidate, 'score': score, 'transform': asdict(transform),
                  'field': field.metadata() if field else None,
                  'errors': errors, 'new_crossings_vs_A': sorted(new_crossings),
                  'length_ratios_vs_A': lengths,
                  'accepted': not errors and not new_crossings and min(lengths) >= .4 and max(lengths) <= 2.5}
        diagnostics.append(record)
        if record['accepted']:
            accepted.append((score, glyph, record))
    if not accepted:
        return base, {'fallback_reason': 'no topology-compatible complete exemplar',
                      'candidates': diagnostics, 'selected': None}
    _, glyph, selected = min(accepted, key=lambda item: item[0])
    return glyph, {'fallback_reason': None, 'selected': selected, 'candidates': diagnostics}
