"""Post-freeze mechanistic ablation: limit B/C effects to changed reference strokes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from experiment_component_trust import glyph_from_dict, mean_present
from run_raw_trajectory_experiment import curves, save
from validate_structure_corrections import METRICS, read, repositories

from inkstruct.samples import sha256_file
from inkstruct.topology_repair import repair_reviewed_crossings
from inkstruct.trajectory_experiment import assemble, crossing_pairs, invariants, stroke_metrics


def patch(base, proposal, old, corrected):
    replacements={}
    for i,(a,b) in enumerate(zip(old.strokes,corrected.strokes,strict=True)):
        if a.median==b.median or base.strokes[i].style_source.startswith(('source-','observed-')):continue
        s=proposal.strokes[i]
        replacements[i]={'points':[(p.x,p.y) for p in s.points],'pressure':[p.pressure for p in s.points],'time':[p.t_ms for p in s.points]}
    if not replacements:return base,{'applied':False,'reason':'reference unchanged'}
    result=assemble(base,replacements,'scoped_source_regeneration')
    ids=[s.stroke_id for s in old.strokes]
    initial=crossing_pairs(curves(base));pairs=crossing_pairs(curves(result))-initial
    diagnostics={}
    if pairs:
        try:
            result,diagnostics=repair_reviewed_crossings(result,corrected,[(ids[i],ids[j]) for i,j in pairs],
                movable_stroke_ids={ids[i] for i in replacements},max_shift=.06,step=.002,clearance=.002)
        except ValueError as e:diagnostics={'reason':str(e)}
    failures=invariants(result,old);extra=crossing_pairs(curves(result))-initial
    if failures or extra:return base,{'applied':False,'reason':'proposal rejected','failures':failures,'extra_pairs':sorted(extra),'guard':diagnostics}
    return result,{'applied':True,'reason':None,'guard':diagnostics}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    old,corrected=repositories();frozen=read(args.input/'generation_manifest.json')
    save(args.output/'protocol.json',{'input_manifest_sha256':sha256_file(args.input/'generation_manifest.json'),
        'script_sha256':sha256_file(Path(__file__)),'scope':'Observed mechanistic ablation, after T/G outcome; not held-out selection or new validation claim',
        'arms':{'SB':'A plus only changed-source strokes from B, inherited topology guard','SC':'A plus only changed-source strokes from C, inherited topology guard'},
        'parameters':{'max_shift':.06,'step':.002,'clearance':.002},'reference_identity':corrected.identity})
    manifest={}
    for p,h in frozen.items():
        assert sha256_file(Path(p))==h
        row=read(Path(p));c=row['task']['character'];base=glyph_from_dict(row['outputs']['A'])
        graph,new=old.get(c),corrected.get(c)
        results={k:patch(base,glyph_from_dict(row['outputs'][source]),graph,new) for k,source in [('SB','B'),('SC','C')]}
        record={'task':row['task'],'events':row['events'],'outputs':{k:asdict(g) for k,(g,_) in results.items()},'diagnostics':{k:d for k,(_,d) in results.items()}}
        for g,_ in results.values():
            assert not invariants(g,graph)
            assert not crossing_pairs(curves(g))-crossing_pairs(curves(base))
            for i,(a,b) in enumerate(zip(graph.strokes,new.strokes,strict=True)):
                if a.median==b.median:assert curves(g)[i]==curves(base)[i]
        path=args.output/'generated'/Path(p).name;save(path,record);manifest[str(path)]=sha256_file(path)
    save(args.output/'generation_manifest.json',manifest)
    print('sealed',len(manifest),'scoped cases',flush=True)
    rows=[]
    for p,h in manifest.items():
        assert sha256_file(Path(p))==h
        row=read(Path(p));prior=read(args.input/'evaluated'/Path(p).name);row['reference']=prior['reference']
        if row['reference'] is not None:
            row['metrics']={}
            row['stroke_metrics']={}
            for k,v in row['outputs'].items():
                g=glyph_from_dict(v)
                row['stroke_metrics'][k]={s.standard_stroke_id:stroke_metrics(a,b) for s,a,b in zip(g.strokes,curves(g),row['reference'],strict=True)}
                row['metrics'][k]={m:mean_present([s[m] for s in row['stroke_metrics'][k].values()]) for m in METRICS}
            row['A_metrics']=prior['metrics']['A']
        save(args.output/'evaluated'/Path(p).name,row);rows.append(row)
    summary={}
    for writer in ('scx','mjb','wsq','all'):
        subset=[r for r in rows if (writer=='all' or r['task']['writer']==writer) and r['reference'] is not None and r['task']['cohort']=='observed_regression']
        summary[writer]={'n':len(subset)}
        for k in ('SB','SC'):
            differences=[r['metrics'][k]['mean_distance']-r['A_metrics']['mean_distance'] for r in subset]
            summary[writer][k]={m:mean_present([r['metrics'][k][m] for r in subset]) for m in METRICS}
            summary[writer][k].update(better=sum(d < -1e-9 for d in differences),equal=sum(abs(d)<=1e-9 for d in differences),worse=sum(d > 1e-9 for d in differences))
    save(args.output/'summary.json',summary)
    print('scope ablation done',summary['all'],flush=True)


if __name__=='__main__':main()
