"""Experimental bounded diagonal placement of a complete source component."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from .contextual_trajectory import anchor_error, anchors, choose_component, fit_shared_similarity
from .exemplar_variation import source_component
from .geometry import path_length
from .topology_repair import glyph_curves
from .trajectory_experiment import SharedTransform, assemble, crossing_pairs, invariants

ASPECT_POLICY = 'bounded_whole_component_aspect_v1'


def solve_bounded_correspondences(x, y, cap):
    """Exact convex diagonal least-squares fit for fixed correspondences."""
    xm, ym = x.mean(0), y.mean(0)
    xc, yc = x-xm, y-ym
    a = np.sum(xc*xc, axis=0)
    b = np.sum(xc*yc, axis=0)
    scale = float(b.sum()/max(a.sum(), 1e-12))
    if scale <= 1e-8:
        raise ValueError('incompatible component direction')
    candidates = [np.array([scale, scale])]
    if min(a) >= 1e-12:
        free = b/a
        if min(free) > 1e-8 and 1/cap <= free[0]/free[1] <= cap:
            candidates.append(free)
        for ratio in (1/cap, cap):
            sy = (ratio*b[0]+b[1])/(ratio**2*a[0]+a[1])
            if min(sy, ratio*sy) > 1e-8:
                candidates.append(np.array([ratio*sy, sy]))
    scale = min(candidates, key=lambda s: float(np.sum((xc*s-yc)**2)))
    offset = ym-scale*xm
    return SharedTransform(float(scale[0]), float(scale[1]), float(offset[0]), float(offset[1]))


def fit_bounded_aspect(source, target, cap=1.):
    """Fit one positive diagonal map with bounded width/height change.

    Arc-length correspondences move under anisotropic scaling. Rematch in the
    transformed frame, pull matching anchors back to source coordinates, then
    solve a bounded convex subproblem. Accept only decreasing actual matching
    error. Eight deterministic steps are an engineering bound, not a claim of
    global optimality. Original vertices are never replaced by the anchors.
    """
    if not math.isfinite(cap) or not 1 <= cap <= 2:
        raise ValueError('aspect cap must be finite and between 1 and 2')
    current = fit_shared_similarity(source, target)
    if cap == 1.:
        return current
    y = anchors(target)
    placed_anchors = anchors([current.apply(s) for s in source])
    error = float(np.sum((placed_anchors-y)**2))
    for _ in range(8):
        x = (placed_anchors-[current.tx, current.ty])/[current.sx, current.sy]
        try:
            proposal = solve_bounded_correspondences(x, y, cap)
        except ValueError:
            break
        proposed_anchors = anchors([proposal.apply(s) for s in source])
        new_error = float(np.sum((proposed_anchors-y)**2))
        if new_error >= error-1e-14:
            break
        current, placed_anchors, error = proposal, proposed_anchors, new_error
    return current


@dataclass
class AspectCandidates:
    base: object
    original: object
    original_record: dict | None
    alternatives: list
    diagnostics: list
    cap: float

    def select(self, *, fixed_donor=False):
        allowed = self.alternatives
        if fixed_donor:
            if self.original_record is None:
                return self.original, {'selected': None, 'candidates': self.diagnostics,
                    'fallback_reason': 'D has no accepted donor; fixed-donor arm retains D'}
            allowed = [(g, r) for g, r in allowed if r['candidate'] == self.original_record['candidate']]
        if not allowed:
            return self.base, {'selected': None, 'candidates': self.diagnostics,
                               'fallback_reason': 'no safe complete candidate'}
        glyph, record = min(allowed, key=lambda p: (p[1]['score'], p[1]['placement'] != 'isotropic'))
        return glyph, {'selected': record, 'candidates': self.diagnostics, 'fallback_reason': None,
            'policy': ASPECT_POLICY, 'cap': self.cap, 'fixed_donor': fixed_donor,
            'interpretation': 'bounded non-isotropic option with explicit isotropic fallback; do not pool with D'}


def prepare_aspect_candidates(base, graph, target_ids, candidates, sources, *, cap=1., max_candidates=16):
    if not math.isfinite(cap) or not 1 <= cap <= 2:
        raise ValueError('invalid aspect cap')
    original, original_meta = choose_component(base, graph, target_ids, candidates, sources, max_candidates=max_candidates)
    alternatives, diagnostics = [], []
    for record in original_meta['candidates']:
        tagged = {**record, 'placement': 'isotropic', 'aspect_cap': cap}
        diagnostics.append(tagged)
        if tagged.get('accepted'):
            glyph, _ = source_component(base, target_ids, tagged, sources)
            alternatives.append((glyph, tagged))
    base_curves = glyph_curves(base)
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in target_ids]
    target = [base_curves[i] for i in indices]
    initial_crossings = crossing_pairs(base_curves)
    if cap > 1:
        for candidate in candidates[:max_candidates]:
            mapping = {s.standard_stroke_id: s for s in sources[candidate['sample_id']].strokes}
            source = [mapping[sid] for sid in candidate['stroke_ids']]
            try:
                transform = fit_bounded_aspect([s.points for s in source], target, cap)
            except ValueError as error:
                diagnostics.append({'candidate': candidate, 'placement': 'bounded_xy', 'accepted': False,
                                    'errors': [str(error)], 'aspect_cap': cap})
                continue
            placed = [transform.apply(s.points) for s in source]
            replacements = {i: {'points': p, 'pressure': s.pressure, 'time': s.t_ms}
                for i, p, s in zip(indices, placed, source, strict=True)}
            glyph = assemble(base, replacements, 'contextual')
            errors = invariants(glyph, graph)
            new_crossings = crossing_pairs(glyph_curves(glyph))-initial_crossings
            lengths = [path_length(p)/max(path_length(t), 1e-9) for p, t in zip(placed, target, strict=True)]
            record = {'candidate': candidate, 'placement': 'bounded_xy', 'aspect_cap': cap,
                'axis_ratio': transform.sx/transform.sy, 'transform': asdict(transform),
                'score': anchor_error(placed, target)+.01*candidate['score'], 'field': None,
                'errors': errors, 'new_crossings_vs_A': sorted(new_crossings), 'length_ratios_vs_A': lengths,
                'accepted': not errors and not new_crossings and min(lengths) >= .4 and max(lengths) <= 2.5}
            diagnostics.append(record)
            if record['accepted']:
                alternatives.append((glyph, record))
    return AspectCandidates(base, original, original_meta['selected'], alternatives, diagnostics, cap)
