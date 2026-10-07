"""Minimax common translation of a complete candidate inside a local trust bound."""
from __future__ import annotations

from dataclasses import asdict
from itertools import combinations

import numpy as np

from .component_trust import parameterized_curve
from .contextual_trajectory import anchor_error
from .exemplar_variation import source_component
from .topology_repair import glyph_curves
from .trajectory_experiment import crossing_pairs, invariants


def convex_hull(points):
    points = sorted({tuple(p) for p in points})
    if len(points) <= 1:
        return np.asarray(points)
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return np.asarray(lower[:-1]+upper[:-1])


def smallest_circle_center(points, max_hull=64):
    """Finite 2D minimax center via one/two/three boundary points of the hull.

    A smallest enclosing disk has at most three boundary points determining its
    center. Exhaustive hull triples avoid optimization tolerances. If the hull
    is too large, abstain instead of claiming an approximate minimax solution.
    """
    cloud = np.asarray(points, dtype=float)
    if cloud.ndim != 2 or cloud.shape[1] != 2 or not len(cloud) or not np.isfinite(cloud).all():
        raise ValueError('finite nonempty 2D point cloud required')
    hull = convex_hull(cloud)
    if len(hull) > max_hull:
        raise ValueError('translation hull exceeds bounded solver capacity')
    center = hull.mean(0)
    radius2 = float(np.sum((hull-center)**2, axis=1).max())
    for left, right in combinations(hull, 2):
        proposal = (left+right)/2
        r2 = float(np.sum((left-right)**2)/4)
        if r2 >= radius2:
            continue
        maximum = float(np.sum((hull-proposal)**2, axis=1).max())
        if maximum <= r2+1e-14:
            center, radius2 = proposal, maximum
    for a, b, c in combinations(hull, 3):
        u, v = b-a, c-a
        determinant = 2*(u[0]*v[1]-u[1]*v[0])
        if abs(determinant) <= 1e-16:
            continue
        us, vs = float(u@u), float(v@v)
        proposal = a+np.array([us*v[1]-vs*u[1], u[0]*vs-v[0]*us])/determinant
        r2 = float(np.sum((proposal-a)**2))
        if r2 >= radius2:
            continue
        maximum = float(np.sum((hull-proposal)**2, axis=1).max())
        if maximum <= r2+1e-14:
            center, radius2 = proposal, maximum
    return center, float(np.sqrt(radius2)), len(hull)


def displacement_cloud(original, candidate):
    parts = []
    for left, right in zip(original, candidate, strict=True):
        lp, lc = parameterized_curve(left)
        rp, rc = parameterized_curve(right)
        knots = np.unique(np.r_[lp, rp])
        a = np.column_stack([np.interp(knots, lp, lc[:, i]) for i in range(2)])
        b = np.column_stack([np.interp(knots, rp, rc[:, i]) for i in range(2)])
        parts.append(b-a)
    return np.vstack(parts)


def translate_prepared_candidates(base, graph, target_ids, prepared, sources):
    """Return a fresh candidate pool; original frozen alternatives stay intact.

    Each candidate receives one common translation minimizing worst continuous
    correspondence displacement from D. Its score is recomputed against A;
    direction penalties stay unchanged because translation preserves them.
    Safety failure retains that candidate's original placement, with a reason.
    """
    from .author_terminal_context import AuthorTerminalCandidates

    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in target_ids]
    baseline = [glyph_curves(base)[i] for i in indices]
    original = [glyph_curves(prepared.original)[i] for i in indices]
    initial_crossings = crossing_pairs(glyph_curves(base))
    alternatives, diagnostics = [], []
    for glyph, record in prepared.alternatives:
        placed = [glyph_curves(glyph)[i] for i in indices]
        cloud = displacement_cloud(original, placed)
        before = float(np.linalg.norm(cloud, axis=1).max())
        tagged = {**record, 'common_translation': {'before_bound': before, 'applied': False}}
        try:
            center, after, count = smallest_circle_center(cloud)
            tagged['common_translation'].update({'proposed_delta': (-center).tolist(),
                'proposed_bound': after, 'hull_points': count})
            if before-after <= 1e-12:
                tagged['common_translation']['reason'] = 'no meaningful reduction in correspondence bound'
            else:
                transform = {**record['transform'], 'tx': record['transform']['tx']-float(center[0]),
                             'ty': record['transform']['ty']-float(center[1])}
                proposal_record = {**tagged, 'transform': transform}
                proposal, proposed_curves = source_component(base, target_ids, proposal_record, sources)
                errors = invariants(proposal, graph)
                crossings = crossing_pairs(glyph_curves(proposal))-initial_crossings
                tagged['common_translation'].update({'invariants': errors, 'new_crossings_vs_A': sorted(crossings)})
                if errors or crossings:
                    tagged['common_translation']['reason'] = 'translated placement fails existing safety gates; keep original'
                else:
                    glyph = proposal
                    tagged['transform'] = transform
                    tagged['score'] = anchor_error(proposed_curves, baseline)+.01*record['candidate']['score']
                    tagged['common_translation']['applied'] = True
        except ValueError as error:
            tagged['common_translation']['reason'] = str(error)
        alternatives.append((glyph, tagged))
        diagnostics.append(tagged)
    # D has zero displacement and remains unchanged, including all glyph fields.
    chosen = prepared.original_meta['selected']
    if chosen is not None:
        d = [g for g, r in alternatives if r['candidate'] == chosen['candidate']]
        assert len(d) == 1 and asdict(d[0]) == asdict(prepared.original)
    return AuthorTerminalCandidates(prepared.original, prepared.original_meta, alternatives,
                                    diagnostics, prepared.common_supported_strokes)
