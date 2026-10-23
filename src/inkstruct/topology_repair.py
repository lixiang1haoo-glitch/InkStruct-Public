"""Opt-in local translation for explicitly reviewed accidental crossings.

This is a geometry repair of existing output, not cross-character exemplar
transfer. No raw donor is mixed, rescaled, compressed, or smoothed.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from .contextual_trajectory import anchors, fit_shared_similarity
from .trajectory_experiment import crossing_pairs, invariants, point_distances

REPAIR_VERSION = 'reviewed_crossing_translation_v1'


def glyph_curves(glyph):
    return [[(p.x, p.y) for p in s.points] for s in glyph.strokes]


def repair_reviewed_crossings(base, graph, reviewed_pairs, *, max_shift=.06, step=.002,
                             clearance=.002, movable_stroke_ids=None):
    """Search a bounded translation of either involved stroke, then verify globally.

    Never auto-label every extra crossing as a defect. The caller supplies pairs
    reviewed against source structure or handwriting. Unreviewed strokes remain
    exact. New strict crossings anywhere in the glyph are forbidden.
    """
    if not (0 < step <= max_shift <= .1):
        raise ValueError('invalid repair displacement budget')
    if not 0 <= clearance <= max_shift:
        raise ValueError('invalid crossing clearance')
    ids = [s.standard_stroke_id for s in base.strokes]
    wanted = {tuple(sorted((ids.index(a), ids.index(b)))) for a, b in reviewed_pairs}
    if any(a == b for a, b in wanted):
        raise ValueError('reviewed pair must contain two different strokes')
    curves = glyph_curves(base)
    initial = crossing_pairs(curves)
    if not wanted & initial:
        return base, {'version': REPAIR_VERSION, 'applied': False,
                      'reason': 'reviewed crossings absent', 'translations': []}
    current = copy.deepcopy(base)
    translations, unresolved = [], []
    original = np.asarray([p for s in curves for p in s])
    low, high = original.min(axis=0), original.max(axis=0)
    standard_transform = fit_shared_similarity([s.median for s in graph.strokes], curves)
    expected_centers = [anchors([standard_transform.apply(s.median)]).mean(axis=0)
                        for s in graph.strokes]
    # Minimize displacement, with a deterministic directional tie break. Same
    # radius candidates all receive exact full-glyph topology verification.
    directions = [(math.cos(a), math.sin(a)) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
    for pair in sorted(wanted):
        current_curves = glyph_curves(current)
        current_crossings = crossing_pairs(current_curves)
        if pair not in current_crossings:
            continue
        chosen = None
        for radius in np.arange(step, max_shift + step / 2, step):
            proposals = []
            for index in pair:
                if movable_stroke_ids is not None and ids[index] not in movable_stroke_ids:
                    continue
                raw = np.asarray(current_curves[index])
                for dx, dy in directions:
                    shift = np.array([dx, dy]) * radius
                    moved = raw + shift
                    if np.linalg.norm(moved[0] - curves[index][0]) > max_shift + 1e-10:
                        continue
                    if (moved < 0).any() or (moved > 1).any():
                        continue
                    # Do not increase the original glyph envelope beyond the
                    # displacement budget; the final canvas fit is not a repair.
                    if (moved < low - max_shift).any() or (moved > high + max_shift).any():
                        continue
                    trial = list(current_curves)
                    trial[index] = [tuple(p) for p in moved]
                    intersections = crossing_pairs(trial)
                    if pair in intersections or intersections - current_crossings:
                        continue
                    left, right = [trial[k] for k in pair]
                    separation = min(float(point_distances(left, right).min()),
                                     float(point_distances(right, left).min()))
                    if separation < clearance:
                        continue
                    # Already repaired required pairs cannot be reintroduced.
                    if (intersections & wanted) - (current_crossings & wanted):
                        continue
                    alignment = float(np.linalg.norm(anchors([moved.tolist()]).mean(axis=0)
                                                     - expected_centers[index]))
                    proposals.append((len(intersections & wanted), alignment, index,
                                      float(dx), float(dy), moved))
            if proposals:
                chosen = min(proposals, key=lambda p: p[:5])
                break
        if chosen is None:
            unresolved.append([ids[i] for i in pair])
            continue
        _, _, index, dx, dy, moved = chosen
        for point, (x, y) in zip(current.strokes[index].points, moved, strict=True):
            point.x, point.y = float(x), float(y)
        translations.append({'stroke_id': ids[index], 'dx': float(dx * radius),
                             'dy': float(dy * radius), 'reviewed_pair': [ids[i] for i in pair]})
    errors = invariants(current, graph)
    final = crossing_pairs(glyph_curves(current))
    if errors or final - initial:
        return base, {'version': REPAIR_VERSION, 'applied': False,
                      'reason': 'global verification failed', 'invariant_errors': errors,
                      'translations': []}
    changed = bool(translations)
    if changed:
        current.generator = f'{base.generator}+{REPAIR_VERSION}'
    return current if changed else base, {'version': REPAIR_VERSION, 'applied': changed,
        'reason': None if changed else 'no bounded safe translation', 'translations': translations,
        'unresolved_pairs': unresolved,
        'before_reviewed_crossings': [[ids[i] for i in p] for p in sorted(initial & wanted)],
        'after_reviewed_crossings': [[ids[i] for i in p] for p in sorted(final & wanted)]}
