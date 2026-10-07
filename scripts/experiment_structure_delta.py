"""Isolate fixed-style source-delta transport from whole-graph regeneration."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from experiment_component_trust import glyph_from_dict, mean_present
from run_raw_trajectory_experiment import curves, save
from validate_structure_corrections import (
    CONFIG,
    DICTIONARY,
    GRAPHICS,
    METRICS,
    REGRESSION,
    read,
    repositories,
)

from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.reviewed_geometry import ReviewedGeometryProcessor
from inkstruct.samples import sha256_file
from inkstruct.structure_delta import apply_structure_delta
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics

OLD = Path('artifacts/structure_audit_20261007/validation_v2')
REVIEWED = Path('configs/geometry_repairs/reviewed_v1.json')


def generate(out):
    out.mkdir(parents=True,exist_ok=False)
    base,corrected=repositories()
    manifest=read(OLD/'generation_manifest.json')
    files=[OLD/'generation_manifest.json',OLD/'protocol.json',CONFIG,REVIEWED,GRAPHICS,DICTIONARY,base.path]
    profiles={w:REGRESSION/'training'/(w+'.json') for w in ('scx','mjb','wsq')}
    files+=list(profiles.values())
    code=[Path(__file__),*Path('src/inkstruct').glob('*.py')]
    save(out/'protocol.json',{'input_sha256':{str(p):sha256_file(p) for p in files},'code_sha256':{str(p):sha256_file(p) for p in code},
        'old_manifest':manifest,'arms':{'A':'frozen v4','B':'whole corrected structure, old profile','C':'corrected structure, rebuilt profile (prior frozen run)',
        'R':'existing reviewed two-short-median processor, same A/profile','T':'fixed A plus transported reference delta, unguarded diagnostic','G':'T plus existing bounded translation and whole-proposal protocol/topology rejection'},
        'parameters':{'max_shift':.06,'step':.002,'clearance':.002,'fit_after_transport':False},
        'scope':'Mechanistic experiment on observed development/regression cohorts; no fresh holdout. All choices frozen before generation. No quality-based tuning or target evaluation data in inference.',
        'hypothesis':'B can reselect prototypes/change residual scale and neighboring layout. Transport only validated source displacement into fixed global/canvas linear frame to keep old style realization.',
        'reference_identity':corrected.identity})
    engines={}
    for w,p in profiles.items():
        profile=load_profile(p)
        baseline=DeterministicGenerator(profile,base.metadata()['source_version'],'adaptive',1.)
        engines[w]=(profile,ReviewedGeometryProcessor(baseline,base,REVIEWED,GRAPHICS,DICTIONARY))
    output_manifest={}
    for n,(p,h) in enumerate(manifest.items()):
        assert sha256_file(Path(p))==h
        row=read(Path(p));task=row['task'];w,c=task['writer'],task['character']
        graph,reference=base.get(c),corrected.get(c)
        profile,reviewed=engines[w]
        original=glyph_from_dict(row['outputs']['A'])
        results={'R':reviewed.apply(original,graph),
            'T':apply_structure_delta(original,graph,reference,profile.global_style),
            'G':apply_structure_delta(original,graph,reference,profile.global_style,guard=True)}
        record={'task':task,'events':row['events'],'outputs':{**row['outputs'],**{k:asdict(g) for k,(g,_) in results.items()}},
            'diagnostics':{k:m for k,(_,m) in results.items()}}
        allglyphs={k:glyph_from_dict(v) for k,v in record['outputs'].items()}
        initial=crossing_pairs(curves(original))
        record['checks']={k:{'invariants':invariants(g,graph),'degenerate_ids':[s.standard_stroke_id for s in g.strokes if path_length([(p.x,p.y) for p in s.points])<1e-6],
            'new_pairs':sorted(crossing_pairs(curves(g))-initial),'changed_ids':[a.standard_stroke_id for a,b in zip(original.strokes,g.strokes,strict=True) if [(p.x,p.y) for p in a.points]!=[(p.x,p.y) for p in b.points]],
            'changed_unchanged_reference_ids':[graph.strokes[i].stroke_id for i,(a,b) in enumerate(zip(curves(original),curves(g),strict=True)) if a!=b and graph.strokes[i].median==reference.strokes[i].median]}
            for k,g in allglyphs.items()}
        target=out/'generated'/Path(p).name
        save(target,record);output_manifest[str(target)]=sha256_file(target)
        if (n+1)%20==0:print('generated',n+1,flush=True)
    save(out/'generation_manifest.json',output_manifest)


def evaluate(out):
    protocol=read(out/'protocol.json')
    for p,h in {**protocol['input_sha256'],**protocol['code_sha256']}.items():assert sha256_file(Path(p))==h,p
    rows=[]
    for n,(p,h) in enumerate(read(out/'generation_manifest.json').items()):
        assert sha256_file(Path(p))==h
        row=read(Path(p));gold=read(OLD/'evaluated'/Path(p).name)
        row['reference']=gold['reference']
        if row['reference'] is not None:
            row['reference_identity']=gold['reference_identity']
            row['stroke_metrics']=gold['stroke_metrics']
            row['metrics']=gold['metrics']
            ids=[s['standard_stroke_id'] for s in row['outputs']['A']['strokes']]
            for k in ('R','T','G'):
                predictions=curves(glyph_from_dict(row['outputs'][k]))
                row['stroke_metrics'][k]={sid:stroke_metrics(a,b) for sid,a,b in zip(ids,predictions,row['reference'],strict=True)}
                row['metrics'][k]={m:mean_present([s[m] for s in row['stroke_metrics'][k].values()]) for m in METRICS}
        save(out/'evaluated'/Path(p).name,row);rows.append(row)
        if (n+1)%30==0:print('scored',n+1,flush=True)
    summary={}
    for w in ('scx','mjb','wsq','all'):
        subset=[r for r in rows if w=='all' or r['task']['writer']==w]
        writer={}
        for group,selected in [('all',subset),('affected',[r for r in subset if r['events']['changes']]),('unchanged_reference',[r for r in subset if not r['events']['changes']]),
                               ('regression_gold',[r for r in subset if r['task']['cohort']=='observed_regression' and r['reference'] is not None])]:
            data={'n':len(selected),'scored':sum(r['reference'] is not None for r in selected)}
            for k in ('A','B','C','R','T','G'):
                scored=[r for r in selected if r['reference'] is not None]
                delta=[r['metrics'][k]['mean_distance']-r['metrics']['A']['mean_distance'] for r in scored]
                data[k]={m:mean_present([r['metrics'][k][m] for r in scored]) for m in METRICS}
                data[k].update(better=sum(d < -1e-9 for d in delta),worse=sum(d > 1e-9 for d in delta),equal=sum(abs(d)<=1e-9 for d in delta),
                    invariant_failures=sum(bool(r['checks'][k]['invariants']) for r in selected),
                    changed_cases=sum(bool(r['checks'][k]['changed_ids']) for r in selected),
                    changed_unchanged_reference_strokes=sum(len(r['checks'][k]['changed_unchanged_reference_ids']) for r in selected),
                    new_crossing_cases=sum(bool(r['checks'][k]['new_pairs']) for r in selected),new_pairs=sum(len(r['checks'][k]['new_pairs']) for r in selected))
            writer[group]=data
        summary[w]=writer
    save(out/'summary.json',summary)
    preservation={p:sha256_file(Path(p))==h for p,h in protocol['input_sha256'].items()}
    assert all(preservation.values());save(out/'input_preservation.json',preservation)
    print('done',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=['generate','evaluate'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();{'generate':generate,'evaluate':evaluate}[args.stage](args.output)
