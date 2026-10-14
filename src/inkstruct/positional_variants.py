"""Bounded semantic variant checks for complete component reuse, not font fitting.

Only a small explicit family registry blocks candidates. Ambiguous geometry and
unsupported families are labelled, never silently promoted to semantic proof.
No source vertex, pressure, time, structure record or standard ID is modified.
"""
from __future__ import annotations

import numpy as np

from .exemplar_index import ordered_ids
from .geometry import path_length
from .trajectory_experiment import at_distance

VERSION = 'positional_key_strokes_v1'
# Zero-based ordered local strokes. Car's final two swap functional direction
# in some positional records; matching only count/name cannot prove that map.
FAMILIES = {'羊': (6, (5,)), '土': (3, (2,)), '王': (4, (3,)),
            '子': (3, (2,)), '车': (4, (2, 3))}
PARAMETERS = {'arc_window': [.35, .90], 'vertical_slope_max': .20,
              'left_fall_slope_min': .35, 'horizontal_slope_max': .15,
              'rising_slope_min': .30}


def key_form(points):
    """Long pen-down chord ignores entry flourish and last 10% hook/noise.

    Grey bands deliberately avoid labelling mild author slant as a new form.
    Positive isotropic scaling and translation do not change the classification.
    """
    length = path_length(points)
    if length < 1e-9:
        return {'form': 'uncertain', 'reason': 'negligible stroke'}
    v = at_distance(points, .90 * length) - at_distance(points, .35 * length)
    dx, dy = map(float, v)
    form = 'uncertain'
    if dy > 1e-9 and abs(dx) / dy <= .20:
        form = 'vertical'
    elif dy > 1e-9 and -dx / dy >= .35:
        form = 'left_falling'
    elif dx > 1e-9 and abs(dy) / dx <= .15:
        form = 'horizontal'
    elif dx > 1e-9 and -dy / dx >= .30:
        form = 'rising'
    elif dx > 1e-9 and dy / dx >= .35:
        form = 'right_falling'
    return {'form': form, 'unit_chord': (v / max(float(np.linalg.norm(v)), 1e-12)).tolist(),
            'window': [.35, .90]}


def check_positional_variants(source_graph, source_node, target_graph, target_node, source_strokes):
    """Check direct and aligned descendant families in a complete-source proposal.

    Reference records specify coarse content variants, not author curvature or
    exact angles. When a source context differs but its actual handwriting clearly
    realizes the target form, the observed form may support reuse. Existing
    identity/count/order/version gates remain independently required.
    """
    source_ids = ordered_ids(source_graph, source_node)
    target_ids = ordered_ids(target_graph, target_node)
    if len(source_ids) != len(target_ids) or len(source_strokes) != len(source_ids):
        return {'version': VERSION, 'accepted': False, 'reason': 'variant map incomplete', 'checks': []}
    local = {sid: i for i, sid in enumerate(target_ids)}
    sm = {s.stroke_id: s for s in source_graph.strokes}
    tm = {s.stroke_id: s for s in target_graph.strokes}
    checks, seen = [], set()
    targets = [target_node, *(n for n in target_graph.components
                             if n.component_id != target_node.component_id and set(n.stroke_ids) <= set(target_ids))]
    for tn in targets:
        spec = FAMILIES.get(tn.canonical)
        if not spec or len(tn.stroke_ids) != spec[0]:
            continue
        tids = ordered_ids(target_graph, tn)
        paired = [source_ids[local[k]] for k in tids]
        sns = [n for n in source_graph.components if n.canonical == tn.canonical and
               n.glyph_variant == tn.glyph_variant and ordered_ids(source_graph, n) == paired]
        if not sns:
            checks.append({'family': tn.canonical, 'target_component': tn.component_id,
                           'status': 'review', 'reason': 'aligned descendant variant evidence unavailable'})
            continue
        sn = sns[0]
        for k in spec[1]:
            tid, sid = tids[k], paired[k]
            if (tid, tn.canonical) in seen:
                continue
            seen.add((tid, tn.canonical))
            target = key_form(tm[tid].median)
            reference = key_form(sm[sid].median)
            author = key_form(source_strokes[local[tid]].points)
            t, s, a = (v['form'] for v in (target, reference, author))
            status, reason = 'compatible', 'same coarse content form'
            if t == 'uncertain' or s == 'uncertain':
                status, reason = 'review', 'reference key form ambiguous'
            elif s != t:
                if a == t:
                    reason = 'observed author realizes target form despite source context'
                else:
                    status, reason = 'incompatible', 'source positional variant differs from target'
            elif tn.canonical == '羊' and {t, a} == {'vertical', 'left_falling'}:
                status, reason = 'incompatible', 'actual author sheep stroke has opposite key form'
            elif a != t:
                status, reason = 'review', 'author variation; not enough evidence to reject'
            checks.append({'family': tn.canonical, 'source_component': sn.component_id,
                'target_component': tn.component_id, 'source_role': sn.role, 'target_role': tn.role,
                'local_stroke_order': k+1, 'source_stroke_id': sid, 'target_stroke_id': tid,
                'source_reference': reference, 'target_reference': target, 'author': author,
                'status': status, 'reason': reason})
    bad = [r for r in checks if r['status'] == 'incompatible']
    return {'version': VERSION, 'accepted': not bad, 'checks': checks,
            'reason': '; '.join(f'{r["family"]} stroke {r["local_stroke_order"]}: {r["reason"]}' for r in bad) or None,
            'scope': 'registered key strokes only; no guarantee for unregistered forms'}
