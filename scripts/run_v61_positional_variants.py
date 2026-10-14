"""Frozen before/after variant repair and positional-family audit; no production edits."""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from generate_v61_library import (
    CORRECTIONS,
    DB,
    REVIEW,
    SOURCES,
    WRITERS,
    digest,
    dump,
    encoded,
    generate,
)
from run_v61_admission_exp import stroke_payload
from run_v61_candidate_expansion import ARMS, evaluate

from inkstruct.positional_variants import FAMILIES, PARAMETERS, check_positional_variants
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import SharedTransform
from inkstruct.v61_candidate_expansion import CandidateExpansionGenerator
from inkstruct.v61_exp import Placement

PRIOR = Path('artifacts/v61_candidate_expansion_20261014')
ADDITIONAL = '羚翔群祥鲜地场培理珠孙轻'


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    baseline_files = { (p.parent.name,load(p)['character']):p for folder in ['run_v3','protection_v1']
                      for p in (PRIOR/folder).glob('*/*.json.gz')}
    chars = list(dict.fromkeys(list(load(PRIOR/'run_v3/protocol.json')['cohort']) +
                              list(load(PRIOR/'protection_v1/protocol.json')['cohort']) + list(ADDITIONAL)))
    inputs = [DB,*CORRECTIONS,REVIEW,*SOURCES.values()]
    code = [Path(__file__),Path('scripts/run_v61_candidate_expansion.py'),
            Path('scripts/generate_v61_library.py'),*Path('src/inkstruct').glob('*.py')]
    frozen = {str(p):digest(p) for p in inputs}
    dump(out/'protocol.json',{'name':'v6.1 positional variant repair',
        'git_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'inputs':frozen,'code':{str(p):digest(p) for p in code},
        'prior_outputs':{str(p):digest(p) for p in baseline_files.values()},
        'families':FAMILIES,'parameters':PARAMETERS,'characters':chars,
        'split':'all development/regression; added positional-family cases are not held-out',
        'fixed':'archives, reference, pools, transforms, layout scores and prior geometry limits',
        'only_change':'freeze saved accepted donors/transforms; remove incompatible choices, retry full sources only in remaining gaps',
        'baseline_strategy':'restore saved F/G placement plans, verify full emitted payload against saved glyphs; do not count replay/search-order drift as repair',
        'target_originals_used':False,'production_changed':False})
    base=StructureRepository(DB);target=CorrectedStructureRepository(base,*CORRECTIONS)
    summaries=[]
    for writer in WRITERS:
        profile=load_profile(SOURCES[writer])
        old=CandidateExpansionGenerator(profile,base,target,variant_checks=False)
        new=CandidateExpansionGenerator(profile,base,target,variant_checks=True)
        new.inventory(True)
        folder=out/writer;folder.mkdir()
        for char in chars:
            ctx,a,ap,_=generate(old,char,writer,load(REVIEW))
            if (writer,char) in baseline_files:
                prior=load(baseline_files[writer,char])
                assert stroke_payload(asdict(a))==stroke_payload(prior['arms']['A']['glyph'])
                fctx=copy.copy(ctx)
                for _ in range(3):
                    fctx.graph,_=old.expanded(fctx.graph,target)
                gctx=fctx
                def restore(name, prior=prior):
                    return {p['component_id']:Placement(p['component_id'],tuple(p['ids']),tuple(p['indices']),
                        p['candidate'],SharedTransform(**p['transform']),p['base_score'])
                        for p in prior['arms'][name]['provenance']}
                fp,gp=restore('F_combined'),restore('G_axes')
                fg,gg=old.emit(fctx,fp),old.emit(gctx,gp)
                flog,glog=[],[]
                assert stroke_payload(asdict(fg))==stroke_payload(prior['arms']['F_combined']['glyph'])
                assert stroke_payload(asdict(gg))==stroke_payload(prior['arms']['G_axes']['glyph'])
            else:
                fctx,fg,fp,flog=old.extend(ctx,ap,ARMS['F_combined'])
                gctx,gg,gp,glog=old.extend(fctx,fp,ARMS['G_axes'])
            nctx,ng,np,nlog=new.repair(fctx,fp,ARMS['F_combined'])
            xctx,xg,xp,xlog=new.repair(gctx,gp,ARMS['G_axes'])
            record={'writer':writer,'character':char,'existing_regression':(writer,char) in baseline_files,
                    'original_baseline_verified':(writer,char) in baseline_files,'arms':{},'old_selected_audit':[]}
            for cid,p in gp.items():
                audit=new.variant_evidence(gctx,p)
                if audit['checks']:
                    record['old_selected_audit'].append({'candidate':p.candidate,'target_component':cid,'evidence':audit})
            for arm,engine,context,glyph,plan,log in [
                ('old_F',old,fctx,fg,fp,flog),('old_G',old,gctx,gg,gp,glog),
                ('new_F',new,nctx,ng,np,nlog),('new_G',new,xctx,xg,xp,xlog)]:
                checks=evaluate(engine,context,glyph,plan,gg)
                audits=[new.variant_evidence(context,p) for p in plan.values()]
                if arm.startswith('new'):
                    assert all(r['accepted'] for r in audits),'incompatible source bypassed final audit'
                record['arms'][arm]={'glyph':asdict(glyph),'checks':checks,'provenance':[asdict(p) for p in plan.values()],
                                     'variant_audit':audits,'log':log}
            # Audit all declared sheep sources, including compatible candidates
            # rejected elsewhere; existence is not actual admitted coverage.
            if char in '羝羚翔':
                tn=next(n for n in xctx.graph.components if n.canonical=='羊')
                inventory=[]
                for sg,sn,q,errors in new.inventory(True).get(('羊','羊',6),[]):
                    mapping={s.standard_stroke_id:s for s in profile.source_trajectories[q['sample_id']].strokes}
                    ev=check_positional_variants(sg,sn,xctx.graph,tn,[mapping[k] for k in q['stroke_ids']])
                    inventory.append({'candidate':q,'mapping_errors':errors,'variant_evidence':ev})
                record['sheep_inventory']=inventory
            (folder/f'{ord(char):04X}.json.gz').write_bytes(gzip.compress(encoded(record),mtime=0))
            row={'writer':writer,'character':char,'strokes':len(a.strokes),
                 'old_selected_incompatible':sum(not r['evidence']['accepted'] for r in record['old_selected_audit']),
                 'arms':{k:v['checks'] for k,v in record['arms'].items()}}
            summaries.append(row)
            print(writer,char,{k:v['integrity']['source_strokes'] for k,v in row['arms'].items()},
                  'bad prior',row['old_selected_incompatible'],flush=True)
    assert frozen=={str(p):digest(p) for p in inputs}
    dump(out/'summary.json',summaries)
    dump(out/'freeze.json',{'outputs':{str(p):digest(p) for p in out.glob('*/*.json.gz')},'target_originals_opened':False})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
