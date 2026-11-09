"""Versioned, bounded content checks; recorded points are never edited here."""
from __future__ import annotations

import numpy as np

from .exemplar_index import ordered_ids
from .geometry import resample, stroke_signature
from .positional_variants import check_positional_variants, key_form

VERSION = 'v62-content-admission-v1'
PARAMETERS = {'stem_window': [4/40, 19/40], 'vertical_reference_dx': .22,
              'slant_reference_dx': .28, 'actual_stem_dx': .50,
              'minimum_stem_dy': .45, 'actual_minimum_stem_dy': .25}


def hook_form(points):
    sig = stroke_signature(points)
    if not ('↓' in sig.directions and '→' in sig.directions
            and any(d in sig.directions for d in ('↑', '↗'))):
        return {'form': 'unclassified'}
    a = np.asarray(resample(points, 41))
    span = a.max(0)-a.min(0)
    if span[1] < 1e-6 or span[0] < .1*span[1]:
        return {'form': 'unclassified'}
    dx, dy = (a[19]-a[4])/span[1]
    form = 'uncertain'
    if dy >= PARAMETERS['minimum_stem_dy']:
        if abs(dx) <= PARAMETERS['vertical_reference_dx']:
            form = 'vertical_bend_hook'
        elif abs(dx) >= PARAMETERS['slant_reference_dx']:
            form = 'slant_hook'
    # A rising finishing stroke (vertical lift) is not a terminal upright hook.
    # Reference role must be explicit; actual ink still gets the wider stem gate.
    if form == 'vertical_bend_hook' and not sig.directions.endswith('↑'):
        form = 'uncertain'
    return {'form': form, 'stem_dx': float(abs(dx)), 'stem_dy': float(dy)}


def hook_compatibility(target, source_reference, actual):
    t, s, a = map(hook_form, (target, source_reference, actual))
    if t['form'] != 'vertical_bend_hook':
        return {'accepted': True, 'status': 'not_checked', 'scope': 'vertical bend hook',
                'target': t, 'source_reference': s, 'actual': a}
    actual_ok = (a.get('stem_dy', 0) >= PARAMETERS['actual_minimum_stem_dy']
                 and a.get('stem_dx', 1) <= PARAMETERS['actual_stem_dx'])
    ok = s['form'] == 'vertical_bend_hook' and actual_ok
    return {'accepted': ok, 'status': 'compatible' if ok else 'incompatible',
            'reason': None if ok else 'vertical-bend hook requires compatible reference role and actual stem',
            'target': t, 'source_reference': s, 'actual': a}


def functional_form(points):
    result = key_form(points)['form']
    if result != 'uncertain':
        return result
    a = np.asarray(resample(points, 41)); v = a[36]-a[14]
    if v[1] > 0 and abs(v[0]) <= .35*v[1]:
        return 'vertical'
    if v[0] > 0 and abs(v[1]) <= .30*v[0]:
        return 'horizontal'
    return 'uncertain'


def stop_keys(graph):
    return {sid for node in graph.components if node.canonical == '止' and len(node.stroke_ids) == 4
            for sid in ordered_ids(graph, node)[2:]}


def stroke_compatibility(graph, index, source_reference, actual):
    target = graph.strokes[index]
    ev = hook_compatibility(target.median, source_reference, actual)
    if target.stroke_id in stop_keys(graph):
        t, s, a = map(functional_form, (target.median, source_reference, actual))
        ok = t in ('vertical', 'horizontal') and a == t
        return {'family': '止', 'accepted': ok, 'status': 'compatible' if ok else 'incompatible',
                'target_reference': t, 'source_reference': s, 'actual': a,
                'reason': None if ok else 'stop-component key differs or is unverified'}
    return ev


def check_content_variants(sg, sn, tg, tn, strokes):
    old = check_positional_variants(sg, sn, tg, tn, strokes)
    if not old['accepted']:
        return old
    sids, tids = ordered_ids(sg, sn), ordered_ids(tg, tn)
    if len(strokes) != len(tids) or len(sids) != len(tids):
        return {'accepted': False, 'reason': 'semantic mapping incomplete', 'checks': []}
    sm, tm = ({s.stroke_id: s for s in g.strokes} for g in (sg, tg))
    local = {sid: i for i, sid in enumerate(tids)}
    checks = list(old['checks'])
    for i, tid in enumerate(tids):
        ev = hook_compatibility(tm[tid].median, sm[sids[i]].median, strokes[i].points)
        if ev['status'] != 'not_checked':
            checks.append({'family': 'vertical_bend_hook', 'target_stroke_id': tid,
                           'source_stroke_id': sids[i], **ev})
    for node in tg.components:
        if node.canonical != '止' or len(node.stroke_ids) != 4:
            continue
        for tid in ordered_ids(tg, node)[2:]:
            if tid not in local:
                continue
            i = local[tid]
            target, reference, actual = map(functional_form,
                (tm[tid].median, sm[sids[i]].median, strokes[i].points))
            # Registered distinguishing strokes require positive evidence. A clear
            # actual target form may support a different source context.
            ok = target in ('vertical', 'horizontal') and actual == target
            checks.append({'family': '止', 'target_stroke_id': tid,
                'source_stroke_id': sids[i], 'source_reference': reference,
                'target_reference': target, 'actual': actual, 'accepted': ok,
                'status': 'compatible' if ok else 'incompatible',
                'reason': None if ok else 'stop-component key stroke differs or is unverified'})
    bad = [c for c in checks if c.get('accepted') is False or c['status'] == 'incompatible']
    return {'version': VERSION, 'accepted': not bad, 'checks': checks,
            'reason': '; '.join(c.get('reason') or c['family'] for c in bad) or None,
            'scope': 'legacy registered families, stop-component keys, vertical bend hooks; other forms unverified'}
