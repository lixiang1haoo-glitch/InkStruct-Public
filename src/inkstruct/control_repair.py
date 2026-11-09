"""Opt-in repairs for duplicated endpoint displacement and weak residual shape.

The original generator stays the default. Geometry statistics describe endpoint
positions relative to the *original* component, not extra offsets after a stroke
bbox warp. This implementation applies those positions once and continuously.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .component_style import absolute_bbox, relative_bbox, transform_between_bboxes
from .generate import DeterministicGenerator
from .geometry import bbox, path_length, signature_key
from .trajectory_experiment import crossing_pairs, invariants

POLICY = "endpoint_consistent_sparse_shape_v1"


def endpoint_consistent_controls(
    controls, transformed, start_delta, end_delta, *, straight_ratio=0.97
):
    """Treat deltas as total displacements; never add them twice at end vertices.

    Near-straight reference paths use a shared similarity between endpoint pairs,
    preserving their small natural bow instead of amplifying a tiny bbox height.
    Other paths retain the bbox warp, distributing only the remaining endpoint
    correction continuously over their arc parameters.
    """
    source = np.asarray(controls, dtype=float)
    warped = np.asarray(transformed, dtype=float)
    if source.shape != warped.shape or source.ndim != 2 or source.shape[1] != 2 or len(source) < 2:
        raise ValueError("matched polylines required")
    if not np.isfinite(source).all() or not np.isfinite(warped).all():
        raise ValueError("finite controls required")
    deltas = np.asarray([start_delta, end_delta], dtype=float)
    if deltas.shape != (2, 2) or not np.isfinite(deltas).all():
        raise ValueError("finite endpoint displacement pairs required")
    start = source[0] + deltas[0]
    end = source[-1] + deltas[1]
    chord = source[-1] - source[0]
    target = end - start
    length = path_length(source.tolist())
    span = float(np.linalg.norm(chord))
    if span > 1e-9 and span / max(length, 1e-9) >= straight_ratio:
        if np.dot(target, chord) <= 0 or np.linalg.norm(target) < 1e-6:
            return controls, "rejected collapsed/reversed endpoint proposal"
        a = float(np.dot(chord, target) / np.dot(chord, chord))
        b = float((chord[0] * target[1] - chord[1] * target[0]) / np.dot(chord, chord))
        matrix = np.array([[a, -b], [b, a]])
        result = (source - source[0]) @ matrix.T + start
        return [tuple(p) for p in result], "endpoint_similarity"
    distances = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(source, axis=0), axis=1))]
    t = distances / max(distances[-1], 1e-9)
    result = warped + (1 - t[:, None]) * (start - warped[0]) + t[:, None] * (end - warped[-1])
    return [tuple(p) for p in result], "continuous_remaining_endpoint_displacement"


def regularize_residual(residual, sample_count, *, support=4):
    """Shrink only non-affine shape; preserve both learned endpoint residuals."""
    if support < 1 or sample_count < 0:
        raise ValueError("invalid support")
    r = np.asarray(residual, dtype=float)
    if r.ndim != 2 or r.shape[1] != 2 or len(r) < 2 or not np.isfinite(r).all():
        raise ValueError("finite residual polyline required")
    t = np.linspace(0.0, 1.0, len(r))[:, None]
    affine = (1 - t) * r[0] + t * r[-1]
    weight = min(1.0, sample_count / support)
    return [tuple(p) for p in affine + weight * (r - affine)]


class ControlRepairGenerator(DeterministicGenerator):
    """Explicit experimental entry, with separate geometry/residual ablations."""

    def __init__(self, profile, structure_version, *, geometry=True, sparse=True, guard=True):
        super().__init__(profile, structure_version, "adaptive", 1.0)
        self.repair_geometry, self.repair_sparse, self.guard = geometry, sparse, guard
        self.baseline = DeterministicGenerator(profile, structure_version, "adaptive", 1.0)
        self.last_diagnostics = {}
        self._events = []

    def _prototype(self, signature, component_path):
        prototype, exact = super()._prototype(signature, component_path)
        if (
            self.repair_sparse
            and prototype is not None
            and prototype.sample_count < 4
            and int(signature.split("|")[1]) >= 1
        ):
            self._events.append(
                {
                    "kind": "sparse_residual",
                    "key": prototype.key,
                    "sample_count": prototype.sample_count,
                    "weight": prototype.sample_count / 4,
                    "scope": "non-affine residual only; endpoints unchanged",
                }
            )
            prototype = replace(
                prototype, residual=regularize_residual(prototype.residual, prototype.sample_count)
            )
        return prototype, exact

    def _stroke_geometry_controls(self, graph, component, standard, controls, component_bbox):
        if not self.repair_geometry:
            return super()._stroke_geometry_controls(
                graph, component, standard, controls, component_bbox
            )
        if component is None or component_bbox is None:
            return controls, None, False
        proto, damping, exact = self._component_geometry_prototype(
            graph, component, standard.stroke_id, signature_key(standard.signature)
        )
        if proto is None or damping <= 0:
            return controls, None, False
        relative = relative_bbox(standard.bbox, component.bbox)
        desired = tuple(
            max(-0.15, min(1.15, v + d * damping))
            for v, d in zip(relative, proto.stroke_bbox_delta, strict=True)
        )
        if desired[2] - desired[0] < 0.005 or desired[3] - desired[1] < 0.005:
            return controls, None, False
        warped = transform_between_bboxes(
            controls, bbox(controls), absolute_bbox(desired, component_bbox)
        )
        span = np.maximum(np.asarray(component_bbox[2:]) - component_bbox[:2], 1e-6)
        result, method = endpoint_consistent_controls(
            controls,
            warped,
            np.asarray(proto.start_delta) * span * damping,
            np.asarray(proto.end_delta) * span * damping,
        )
        self._events.append(
            {
                "kind": "geometry",
                "stroke_id": standard.stroke_id,
                "prototype": proto.key,
                "method": method,
            }
        )
        return result, proto, exact

    def generate(self, graph):
        self._events = []
        proposed = super().generate(graph)
        baseline = self.baseline.generate(graph)

        def curves(g):
            return [[(p.x, p.y) for p in s.points] for s in g.strokes]

        extra = crossing_pairs(curves(proposed)) - crossing_pairs(curves(baseline))
        errors = invariants(proposed, graph)
        degenerated = [
            a.standard_stroke_id
            for a, b in zip(baseline.strokes, proposed.strokes, strict=True)
            if path_length([(p.x, p.y) for p in a.points]) > 1e-6
            and path_length([(p.x, p.y) for p in b.points]) <= 1e-6
        ]
        if degenerated:
            errors.append("new degenerate stroke")
        changed = [
            a.standard_stroke_id
            for a, b in zip(baseline.strokes, proposed.strokes, strict=True)
            if [(p.x, p.y) for p in a.points] != [(p.x, p.y) for p in b.points]
        ]
        rejected = self.guard and bool(extra or errors)
        self.last_diagnostics[graph.character] = {
            "policy": POLICY,
            "geometry": self.repair_geometry,
            "sparse": self.repair_sparse,
            "events": self._events,
            "candidate_changed_ids": changed,
            "new_crossings": sorted(extra),
            "invariant_errors": errors,
            "new_degenerate_ids": degenerated,
            "applied": bool(changed) and not rejected,
            "fallback": "new crossing/protocol failure" if rejected else None,
            "scope": "candidate requires visual re-review; not a calibrated quality classifier",
        }
        if rejected:
            return baseline
        if changed:
            proposed.generator += "+" + POLICY
        return proposed
