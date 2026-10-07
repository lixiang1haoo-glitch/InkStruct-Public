"""Bound complete-exemplar reranking by continuous stroke correspondence drift."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .author_terminal_context import MODES

TRUST_POLICY = 'whole_component_arclength_trust_v1'


def parameterized_curve(points):
    curve = np.asarray(points, dtype=float)
    if curve.ndim != 2 or curve.shape[1] != 2 or len(curve) < 2 or not np.isfinite(curve).all():
        raise ValueError('finite nonempty 2D polyline with at least two vertices required')
    lengths = np.linalg.norm(np.diff(curve, axis=0), axis=1)
    keep = np.r_[True, lengths > 0]
    curve = curve[keep]
    if len(curve) == 1:
        return np.array([0., 1.]), np.repeat(curve, 2, axis=0)
    cumulative = np.r_[0., np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
    return cumulative/cumulative[-1], curve


def correspondence_bound(left, right):
    """Exact maximum displacement under continuous normalized-arclength matching.

    Between consecutive union knots both interpolants are linear. Their
    difference is linear and its Euclidean norm convex, so the maximum is at a
    knot. This correspondence covers both complete curves: its maximum bounds
    their symmetric Hausdorff distance. Knots are for auditing only; outputs are
    never resampled. Zero-length polylines are interpreted as constant curves.
    """
    lp, lc = parameterized_curve(left)
    rp, rc = parameterized_curve(right)
    knots = np.unique(np.r_[lp, rp])
    l = np.column_stack([np.interp(knots, lp, lc[:, i]) for i in range(2)])
    r = np.column_stack([np.interp(knots, rp, rc[:, i]) for i in range(2)])
    distances = np.linalg.norm(l-r, axis=1)
    worst = int(np.argmax(distances))
    return {'maximum': float(distances[worst]), 'worst_arc_fraction': float(knots[worst]),
            'start_displacement': float(distances[0]), 'end_displacement': float(distances[-1]),
            'audit_knots': len(knots), 'interpretation': 'continuous correspondence bound, not a target quality estimate'}


@dataclass
class TrustedComponentCandidates:
    prepared: object
    alternatives: list

    def select(self, radius=None, *, weight=.04, mode='author'):
        if radius is not None and (not math.isfinite(radius) or radius < 0):
            raise ValueError('radius must be None or finite and nonnegative')
        # Delegate validation and preserve the exact unguarded/disabled behavior.
        unguarded, metadata = self.prepared.select(weight, mode)
        if radius is None:
            return unguarded, metadata
        if radius == 0 or weight == 0 or metadata.get('context_fallback_reason'):
            glyph, original = self.prepared.select(0., mode)
            return glyph, {**original, 'local_trust': {'policy': TRUST_POLICY, 'radius': radius,
                'reason': 'zero radius, disabled direction score or unavailable evidence; exact D',
                'candidates': self.alternatives}}
        eligible = [i for i, r in enumerate(self.alternatives) if r['maximum'] <= radius+1e-12]
        if not eligible:
            raise RuntimeError('D must remain inside every nonnegative trust radius')
        selected_index = min(eligible, key=lambda i: self.prepared.alternatives[i][1]['score']+
                             weight*self.prepared.alternatives[i][1]['author_terminal_penalties'][mode])
        glyph, selected = self.prepared.alternatives[selected_index]
        return glyph, {**metadata, 'selected': selected,
            'total_selection_score': selected['score']+weight*selected['author_terminal_penalties'][mode],
            'local_trust': {'policy': TRUST_POLICY, 'radius': radius,
                'selected_bound': self.alternatives[selected_index],
                'rejected_candidates': len(self.alternatives)-len(eligible),
                'changed_from_unguarded': selected['candidate'] != metadata['selected']['candidate'],
                'candidates': self.alternatives,
                'reason': 'complete candidate ranking inside per-stroke correspondence bound'}}


def prepare_component_trust(prepared, target_ids):
    original = prepared.original
    indices = [i for i, s in enumerate(original.strokes) if s.standard_stroke_id in target_ids]
    if len(indices) != len(target_ids) or not indices:
        raise ValueError('unique complete target stroke IDs required')
    diagnostics = []
    for glyph, record in prepared.alternatives:
        per_stroke = {}
        for i in indices:
            source, target = original.strokes[i], glyph.strokes[i]
            if source.standard_stroke_id != target.standard_stroke_id:
                raise ValueError('candidate stroke mapping changed')
            per_stroke[source.standard_stroke_id] = correspondence_bound(
                [(p.x, p.y) for p in source.points], [(p.x, p.y) for p in target.points])
        diagnostics.append({'candidate': record['candidate'], 'per_stroke': per_stroke,
                            'maximum': max(r['maximum'] for r in per_stroke.values())})
    if set(prepared.common_supported_strokes) != set(MODES):
        raise ValueError('unexpected direction modes')
    return TrustedComponentCandidates(prepared, diagnostics)
