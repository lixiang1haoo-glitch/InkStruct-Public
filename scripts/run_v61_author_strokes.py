"""Bounded author key replacement and single-stroke fallback ablations."""
from __future__ import annotations

import argparse
import gzip
import subprocess
from dataclasses import asdict
from pathlib import Path

import numpy as np
from generate_v61_library import CORRECTIONS, DB, SOURCES, WRITERS, digest, dump, encoded
from run_v61_positional_variants import load

from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import SharedTransform, assemble, invariants
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_author_strokes import (
    PARAMETERS,
    AuthorStrokeFallback,
    pair_changes,
    require_author_only,
    retain_source_relationships,
)
from inkstruct.v61_exp import curves

PRIOR = Path('artifacts/v61_positional_variants_20261014/run_final')
COHORT = '羝羚而相儒荡叵铜伯饿群翔'


def decode(value):
    return GeneratedGlyph(**{**value, 'strokes': [GeneratedStroke(**{**s,
        'points': [GeneratedPoint(**p) for p in s['points']]}) for s in value['strokes']]})


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


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    inputs = [DB,*CORRECTIONS,*SOURCES.values()]
    prior_files = [PRIOR/w/f'{ord(c):04X}.json.gz' for w in WRITERS for c in COHORT]
    hashes = {str(p):digest(p) for p in inputs+prior_files}
    dump(out/'protocol.json',{'name':'v6.1 author stroke fallback v1', 'parameters':PARAMETERS,
        'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'code':{str(p):digest(p) for p in [Path(__file__),Path('src/inkstruct/v61_author_strokes.py')]},
        'inputs':hashes,'characters':COHORT,'split':'development/regression only; no new held-out claim',
        'fixed':'saved new_G full component placements and archives; same-character donors excluded',
        'arms':{'A':'previous positional repair','B':'only sheep key replacement',
                'C':'only author single-stroke fallback','D':'B then C'},
        'limitations':['inherited whole components may use prior bounded axes; all new single strokes isotropic',
                      'direction buckets are not complete semantic stroke labels',
                      'reference still supplies single-stroke placement; no style quality claim from coverage'],
        'target_originals_used':False,'production_changed':False})
    base=StructureRepository(DB)
    target=CorrectedStructureRepository(base,*CORRECTIONS)
    summary=[]
    for w in WRITERS:
        profile=load_profile(SOURCES[w]);engine=AuthorStrokeFallback(profile,base)
        (out/w).mkdir()
        for char in COHORT:
            old=load(PRIOR/w/f'{ord(char):04X}.json.gz')
            a=decode(old['arms']['new_G']['glyph'])
            original_graph=target.get(char)
            graph=framed_graph(original_graph,reference_frame(original_graph))
            reference=[s.median for s in graph.strokes]
            ap=plan_sources(old['arms']['new_G']['provenance'])
            b,bp,blog=hybrid(engine,old,a,graph,reference,ap)
            c,cp,clog=engine.fill(a,graph,reference,ap)
            d,dp,dlog=engine.fill(b,graph,reference,bp)
            record={'writer':w,'character':char,'arms':{},'hybrid_log':blog}
            for name,g,p,log in [('A',a,ap,{}),('B',b,bp,blog),('C',c,cp,clog),('D',d,dp,dlog)]:
                checks={'protocol':invariants(g,graph),'source_exact':check_sources(profile,g,p),
                        'geometry':pair_changes(curves(a),curves(g),reference),
                        'author_strokes':len(p),'total_strokes':len(g.strokes),
                        'author_only_ready':len(p)==len(g.strokes)}
                assert not checks['protocol'] and not checks['source_exact'], checks
                record['arms'][name]={'glyph':asdict(g),'provenance':p,'checks':checks,'log':log}
                if name=='D' and checks['author_only_ready']:
                    require_author_only(g,p)
                    (out/w/f'{ord(char):04X}.author_only.json').write_bytes(encoded(asdict(g)))
            (out/w/f'{ord(char):04X}.json.gz').write_bytes(gzip.compress(encoded(record),mtime=0))
            summary.append({'writer':w,'character':char,
                            'arms':{k:v['checks'] for k,v in record['arms'].items()}})
            print(w,char,{k:v['checks']['author_strokes'] for k,v in record['arms'].items()},flush=True)
    assert hashes=={str(p):digest(p) for p in inputs+prior_files}
    dump(out/'summary.json',summary)
    dump(out/'freeze.json',{'outputs':{str(p):digest(p) for p in out.glob('*/*.json.gz')},
                           'target_originals_opened':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
