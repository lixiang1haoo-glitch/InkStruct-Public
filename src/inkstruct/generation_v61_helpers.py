"""Unmodified orchestration helpers from the verified corrected v6.1 scripts.

No research result files are required at runtime. Keep source checks and the
bounded sheep-key substitution identical to run_v61_author_strokes.py.
"""
import numpy as np

from .trajectory_experiment import SharedTransform, assemble
from .v61_author_strokes import pair_changes, retain_source_relationships
from .v61_exp import curves

LABELS = {'author_complete_component':'完整部件', 'author_hybrid_retained':'关键笔替换·保留部件',
          'author_hybrid_key':'关键笔替换', 'author_single_stroke':'作者单笔'}


def plan_sources(plan, kind='author_complete_component'):
    result = {}
    for p in plan:
        for i, sid in zip(p['indices'], p['candidate']['stroke_ids'], strict=True):
            result[i] = {**p['candidate'], 'kind': kind, 'source_stroke_id': sid,
                         'transform': p['transform'], 'target_component': p['component_id']}
    return result

def hybrid(engine, record, glyph, graph, reference, provenance):
    replacements, result, log = {}, dict(provenance), []
    for audit in record['old_selected_audit']:
        bad = [c for c in audit['evidence']['checks'] if c['status'] == 'incompatible']
        if len(bad) != 1 or bad[0]['family'] != '羊' or bad[0]['local_stroke_order'] != 6:
            continue
        plan = next(p for p in record['arms']['old_G']['provenance']
                    if p['component_id'] == audit['target_component'])
        if any(i in result for i in plan['indices']):
            log.append({'reason': 'already covered by compatible complete component'})
            continue
        source = engine.profile.source_trajectories[plan['candidate']['sample_id']]
        assert source.character != graph.character and source.source_sha256 == plan['candidate']['source_sha256']
        mapping = {s.standard_stroke_id: s for s in source.strokes}
        transform = SharedTransform(**plan['transform'])
        pieces = {i: {'points': transform.apply(mapping[sid].points),
                       'pressure': mapping[sid].pressure, 'time': mapping[sid].t_ms}
                  for i, sid in zip(plan['indices'], plan['candidate']['stroke_ids'], strict=True)}
        key = plan['indices'][-1]
        current = curves(glyph)
        for i, v in pieces.items():
            if i != key:
                current[i] = v['points']
        selected, evidence = engine.select(graph, key, current, reference,
                                            start_anchor=pieces[key]['points'][0])
        if selected:
            pieces[key] = selected
            trial = curves(assemble(glyph, pieces, 'author_hybrid'))
            check = retain_source_relationships(pair_changes(curves(glyph), trial, reference),
                                                 plan['indices'][:-1])
            if check['unsupported_crossings'] or check['unsupported_contacts']:
                log.append({'reason': 'hybrid introduces unsupported relationships', 'checks': check})
                continue
            replacements.update(pieces)
            result.update(plan_sources([plan], 'author_hybrid_retained'))
            result[key] = {**evidence, 'kind': 'author_hybrid_key',
                           'target_component': plan['component_id']}
            log.append({'accepted': True, 'key': evidence,
                        'inherited_axes': plan['transform'], 'checks': check})
        else:
            log.append({'accepted': False, 'key': evidence})
    generated = assemble(glyph, replacements, 'author_hybrid')
    for i in replacements:
        p = result[i]
        sample = engine.profile.source_trajectories[p['sample_id']]
        source = next(s for s in sample.strokes if s.standard_stroke_id == p['source_stroke_id'])
        generated.strokes[i].confidence = source.confidence
        generated.strokes[i].component_key = 'hybrid:' + p['target_component']
    return generated, result, log

def check_sources(profile, glyph, provenance):
    errors = []
    for i, p in provenance.items():
        sample = profile.source_trajectories[p['sample_id']]
        assert sample.character != glyph.character and sample.source_sha256 == p['source_sha256']
        source = next(s for s in sample.strokes if s.standard_stroke_id == p['source_stroke_id'])
        expected = SharedTransform(**p['transform']).apply(source.points)
        actual = glyph.strokes[i].points
        if len(actual) != len(expected) or not np.allclose([(v.x,v.y) for v in actual],expected,atol=1e-12,rtol=0):
            errors.append([i,'geometry'])
        if [v.pressure for v in actual] != source.pressure:
            errors.append([i,'pressure'])
        if [v.t_ms-actual[0].t_ms for v in actual] != [round(t-source.t_ms[0]) for t in source.t_ms]:
            errors.append([i,'time'])
    return errors

def source_audit(engine, graph, sources):
    groups = {}
    for i, p in sources.items():
        if p['kind'] != 'author_complete_component':
            continue  # Individual strokes are intentionally not blocked by component split rules.
        key = (p['target_component'], p['sample_id'])
        groups.setdefault(key, []).append((i, p))
    for group in groups.values():
        for side, char, ids in [
            ('target', graph.character, [graph.strokes[i].stroke_id for i, _ in group]),
            ('source', group[0][1]['character'], [p['source_stroke_id'] for _, p in group])]:
            ev = engine.reuse_rules.check(engine.rule_graph(char, side=side), ids, side=side)
            if not ev['accepted']:
                raise ValueError(f'forbidden inherited source: {ev}')

def compact_sources(graph, sources, trials):
    by_id = {r['target_stroke_id']: r for r in trials}
    rows, donors, gaps = [], [], []
    for i, s in enumerate(graph.strokes):
        if i in sources:
            p = sources[i]
            rows.append({'order':i+1, 'standard_id':s.stroke_id, **p})
            donors.append({'character':p['character'], 'sample_id':p['sample_id'], 'orders':[i+1],
                           'source_stroke_id':p['source_stroke_id'], 'kind':p['kind'],
                           'label':LABELS.get(p['kind'],p['kind'])})
        else:
            evidence = by_id.get(s.stroke_id, {'reason':'no admitted author stroke; retained diagnostic reference'})
            gap = {'order':i+1, 'standard_id':s.stroke_id, **evidence}
            gaps.append(gap)
            rows.append({**gap, 'kind':'explicit_gap', 'display':'diagnostic reference only'})
    return rows, donors, gaps
