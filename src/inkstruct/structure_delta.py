"""Opt-in source correction transport over fixed output; never edits raw captures.

Source restoration is distinct from author style. Keep the old style realization
and add only the reference displacement in the same global/canvas linear frame.
No prototype reselection, averaging, spline, or per-stroke shape rescaling occurs.
"""
from __future__ import annotations

import copy

import numpy as np

from .geometry import path_length
from .topology_repair import glyph_curves, repair_reviewed_crossings
from .trajectory_experiment import assemble, crossing_pairs, cumulative, invariants

POLICY = 'fixed_style_structure_delta_v1'


def interpolate(points, parameters):
    points = np.asarray(points, dtype=float)
    lengths = cumulative(points)
    if lengths[-1] <= 1e-12:
        return np.repeat(points[:1], len(parameters), axis=0)
    t = lengths/lengths[-1]
    # Keep the final vertex at repeated arc positions (identical coordinates).
    unique = np.r_[np.diff(t) > 1e-12, True]
    return np.column_stack([np.interp(parameters, t[unique], points[unique, i]) for i in (0, 1)])


def transport_stroke(points, old_reference, corrected_reference, linear):
    """Return union-knot polyline and old-output arc parameters.

    For source unclipping, equal vertex counts establish exact source-index
    correspondence. Parameterize both fields by restored-source arc length so
    duplicate/clipped old vertices cannot erase the recovered tail.
    For reviewed reconstruction, normalized arc correspondence is an explicit
    approximation, not evidence of author intent.
    """
    old, new, output = (np.asarray(x, dtype=float) for x in (old_reference, corrected_reference, points))
    if any(x.ndim != 2 or x.shape[1] != 2 or len(x) < 2 or not np.isfinite(x).all() for x in (old, new, output)):
        raise ValueError('invalid source or generated polyline')
    linear = np.asarray(linear, dtype=float)
    if linear.shape != (2, 2) or not np.isfinite(linear).all() or np.linalg.det(linear) <= 1e-12:
        raise ValueError('invalid reference-to-output linear frame')
    output_arc, new_arc, old_arc = map(cumulative, (output, new, old))
    if output_arc[-1] <= 1e-12 or new_arc[-1] <= 1e-12:
        raise ValueError('degenerate output or corrected source')
    nt = new_arc/new_arc[-1]
    ot = old_arc/max(old_arc[-1], 1e-12)
    outt = output_arc/output_arc[-1]
    source_index = len(old) == len(new)
    knots = np.unique(np.r_[outt, nt, [] if source_index else ot])
    if source_index:
        unique = np.r_[np.diff(nt) > 1e-12, True]
        delta = np.column_stack([np.interp(knots, nt[unique], (new-old)[unique, i]) for i in (0, 1)])
    else:
        delta = interpolate(new, knots)-interpolate(old, knots)
    proposal = interpolate(output, knots)+delta@linear.T
    return proposal.tolist(), knots, {'correspondence': 'source_vertex_index' if source_index else 'approximate_normalized_arc',
        'original_points': len(output), 'output_points': len(proposal),
        'max_displacement': float(np.linalg.norm(delta@linear.T,axis=1).max()),
        'source_length_before': float(old_arc[-1]), 'source_length_after': float(new_arc[-1]),
        'output_length_before': float(output_arc[-1]), 'output_length_after': path_length(proposal.tolist())}


def apply_structure_delta(base, original_graph, corrected_graph, global_style, *, guard=False,
                          max_shift=.06, step=.002, clearance=.002):
    """Transport verified reference deltas only; optional baseline topology guard.

    The caller must use a provenance-validated correction repository. Captured
    strokes are excluded even if their coordinates happen to match generation.
    Guard targets newly introduced pairs as a compatibility constraint, not an
    automatic assertion that every non-font author crossing is wrong.
    """
    if original_graph.character != corrected_graph.character or base.character != original_graph.character:
        raise ValueError('character mismatch')
    ids = [s.standard_stroke_id for s in base.strokes]
    expected = [(s.stroke_id,s.order) for s in original_graph.strokes]
    if expected != [(s.stroke_id,s.order) for s in corrected_graph.strokes] or expected != [(s.standard_stroke_id,s.order) for s in base.strokes]:
        raise ValueError('stroke identity/order mismatch')
    changed = [i for i,(a,b) in enumerate(zip(original_graph.strokes,corrected_graph.strokes,strict=True)) if a.median != b.median]
    if not changed:
        return base, {'policy':POLICY,'applied':False,'reason':'reference unchanged','events':[]}
    linear = np.array([[global_style.get('scale_x',1.),global_style.get('slant',0.)],
                       [0.,global_style.get('scale_y',1.)]])*base.canvas_fit.get('scale',1.)
    replacements, events = {}, []
    for i in changed:
        stroke = base.strokes[i]
        event = {'stroke_id':ids[i]};events.append(event)
        if str(stroke.style_source).startswith(('source-','observed-')):
            event.update(applied=False,reason='captured trajectory protected');continue
        try:
            points, t, info = transport_stroke([(p.x,p.y) for p in stroke.points],original_graph.strokes[i].median,corrected_graph.strokes[i].median,linear)
        except ValueError as error:
            event.update(applied=False,reason=str(error));continue
        oldt = cumulative([(p.x,p.y) for p in stroke.points]);oldt /= oldt[-1]
        replacements[i] = {'points':points,'pressure':np.interp(t,oldt,[p.pressure for p in stroke.points]).tolist(),
                           'time':np.interp(t,oldt,[p.t_ms for p in stroke.points]).tolist()}
        event.update(applied=True,reason=None,transport=info)
    if not replacements:
        return base, {'policy':POLICY,'applied':False,'reason':'no eligible source change','events':events}
    candidate = assemble(base,replacements,'structure_delta')
    initial = crossing_pairs(glyph_curves(base))
    proposal_pairs = crossing_pairs(glyph_curves(candidate))-initial
    report = {'policy':POLICY,'guard':guard,'events':events,'new_pairs_before_guard':sorted(proposal_pairs)}
    if guard:
        pairs = [(ids[i],ids[j]) for i,j in sorted(proposal_pairs)]
        if pairs and not invariants(candidate,original_graph):
            try:
                candidate, diagnosis = repair_reviewed_crossings(candidate,corrected_graph,pairs,
                    movable_stroke_ids={ids[i] for i in replacements},max_shift=max_shift,step=step,clearance=clearance)
                report['translation_guard'] = diagnosis
            except ValueError as error:
                report['translation_guard'] = {'applied':False,'reason':str(error)}
        errors = invariants(candidate,original_graph)
        extra = crossing_pairs(glyph_curves(candidate))-initial
        if errors or extra:
            return base, {**report,'applied':False,'reason':'whole proposal rejected: bounds/protocol or new crossings',
                          'invariant_errors':errors,'unresolved_pairs':sorted(extra)}
    candidate.generator = base.generator+'+'+POLICY+('-guarded' if guard else '')
    candidate.canvas_fit = copy.deepcopy(base.canvas_fit)
    candidate.canvas_fit['structure_delta'] = {'policy':POLICY,'global_fit_reapplied':False,'guard':guard}
    return candidate, {**report,'applied':True,'reason':None,'changed_ids':[ids[i] for i in replacements]}
