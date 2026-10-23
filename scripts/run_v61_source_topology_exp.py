"""Bounded source-aware admission ablation; production remains unchanged."""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_v6_exp import sha, write
from run_v61_admission_exp import PRIOR, ROOT_CONTEXTS, SPLIT, stroke_payload
from run_v61_exp import check_integrity, dict_curves

from inkstruct.exemplar_index import component_key
from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics
from inkstruct.v61_admission_exp import AdmissionProbeGenerator
from inkstruct.v61_contacts import contact_pairs

OLD=Path('artifacts/v61_exp_20261013/run_v2')
ACCEPTED=Path('artifacts/v61_root_topology_20261013/run_v3')
ARCHIVES=Path('artifacts/architecture_review_20261011/run_v1')
REVIEW=Path('artifacts/v61_root_topology_20261013/review.json')
WRITERS=('user_001','scx','mjb','wsq')
ARMS={'A':'current accepted baseline; prior copper/white source probes retained',
      'B':'fixed original pool/fit; inherited source topology distinguished; legacy reference warnings still block',
      'C':'B policy plus reference length/contact differences diagnostic only',
      'D':'C accepted sources fixed; expand ordered whole-root role bridges'}


def load(path):
    return json.loads(path.read_text())


def run(root):
    root.mkdir(parents=True,exist_ok=False)
    db=Path('artifacts/full_library_20261010/inputs/characters.sqlite3')
    correction=[Path('third_party/makemeahanzi/graphics.txt'),Path('third_party/makemeahanzi/dictionary.txt'),
                Path('configs/structure_overrides/unclipped_reference_v1.json')]
    sources={w:(PRIOR if w=='user_001' else ARCHIVES/w)/'source_archive.json' for w in WRITERS}
    split=load(SPLIT)
    cohorts={w:(split['development_regression']+split['prospective_validation'] if w=='user_001'
                else [r['character'] for r in load(OLD/w/'records.json')]) for w in WRITERS}
    inputs=[db,*correction,SPLIT,REVIEW,*sources.values(),
            *sorted(ACCEPTED.glob('glyphs/*.json')),*sorted(PRIOR.glob('*/evaluation.json')),
            *(p for w in WRITERS[1:] for p in [OLD/w/'records.json',OLD/w/'evaluation.json',*sorted((OLD/w/'glyphs').glob('*.json'))])]
    code=[Path(__file__),Path('scripts/run_v61_exp.py'),Path('scripts/run_v61_admission_exp.py'),
          Path('scripts/run_v6_exp.py'),*sorted(Path('src/inkstruct').glob('*.py'))]
    frozen={kind:{str(p):sha(p) for p in paths} for kind,paths in [('inputs',inputs),('code',code)]}
    write(root/'protocol.json',{'name':'v6.1 source-topology expansion',**frozen,'cohorts':cohorts,'arms':ARMS,
        'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'all_cases_status':'100 previously observed regression cases; no new blind holdout',
        'targets_excluded_as_character_groups':True,'retuning':False,'originals_opened_after_generation_freeze':True,
        'root_policy':'only complete exact-identity root with unchanged ordered-reference mapping thresholds',
        'hard_guards':'reliable full mapping, standard IDs/order, positive isotropy, exact inherited topology, protocol, nondegeneracy, no new external strict/0.028 brush pair',
        'soft_diagnostics':'C/D reference-relative length and removed reference-supported contacts; target-original deviations evaluation only',
        'human_review':'user accepted previous user_001 铜/伯 style; no approval inferred for new cases',
        'selection':'existing accepted plans fixed; fill reference slots only; unchanged score order and fixed per-candidate fits',
        'production_default_changed':False})
    review=load(REVIEW)
    all_records={}
    base=StructureRepository(db);target=CorrectedStructureRepository(base,*correction)
    for writer in WRITERS:
        out=root/writer;(out/'glyphs').mkdir(parents=True)
        profile=load_profile(sources[writer]);snapshot=asdict(profile)
        assert not set(cohorts[writer]) & {s.character for s in profile.source_trajectories.values()}
        engine=AdmissionProbeGenerator(profile,base,target)
        records=[]
        for char in cohorts[writer]:
            ctx=engine.prepare(char)
            if writer=='user_001':
                a,ap,al=engine.probe(ctx,root_contexts=ROOT_CONTEXTS,reviews=[review])
                saved=load(ACCEPTED/'glyphs'/f'{ord(char):04X}.json')['D']
            else:
                a,ap,al=ctx.baseline,ctx.baseline_plan,{}
                saved=load(OLD/writer/'glyphs'/f'{ord(char):04X}.json')['B']
            assert stroke_payload(asdict(a))==stroke_payload(saved), (writer,char,'A drift')
            b,bp,bl=engine.expand(ctx,ap,existing_pool=True,reference_differences_diagnostic=False)
            c,cp,cl=engine.expand(ctx,ap,existing_pool=True)
            root_contexts=sorted({component_key(ctx.graph,n) for n in ctx.graph.components
                if n.path!='root' and len(n.stroke_ids)>=2})
            d,dp,dl=engine.expand(ctx,cp,root_contexts=root_contexts)
            variants={'A':(a,ap,al),'B':(b,bp,bl),'C':(c,cp,cl),'D':(d,dp,dl)}
            glyphs={arm:asdict(g) for arm,(g,_,_) in variants.items()}
            row={'writer':writer,'character':char,'root_contexts':root_contexts,'arms':{}}
            before=dict_curves(glyphs['A'])
            for arm,(glyph,plan,log) in variants.items():
                for cid,p in ap.items():assert plan[cid]==p,'old source/layout changed'
                xy=dict_curves(glyphs[arm]);own={i:p.component_id for p in plan.values() for i in p.indices}
                pairs=crossing_pairs(xy)-crossing_pairs(before)
                internal={(p.indices[i],p.indices[j]) for p in plan.values()
                          for i,j in crossing_pairs([s.points for s in engine.source(p)])}
                external={(i,j) for i,j in pairs if own.get(i,f'ref:{i}')!=own.get(j,f'ref:{j}')}
                contacts={}
                for width in (.014,.028,.05):
                    added=contact_pairs(xy,width)-contact_pairs(before,width)
                    contacts[str(width)]={'new':sorted(added),
                        'new_cross_component':sorted((i,j) for i,j in added if own.get(i,f'ref:{i}')!=own.get(j,f'ref:{j}')),
                        'removed':sorted(contact_pairs(before,width)-contact_pairs(xy,width))}
                invariant_errors=invariants(glyph,ctx.graph)
                degenerate=[i+1 for i,s in enumerate(xy) if path_length(s)<.003]
                assert not invariant_errors and not degenerate and not external and not pairs-internal
                assert not contacts['0.028']['new_cross_component']
                row['arms'][arm]={'provenance':[asdict(p) for p in plan.values()],'log':log,
                    'integrity':check_integrity(engine,ctx,glyph,plan),'protocol':invariant_errors,'degenerate':degenerate,
                    'new_crossings':sorted(pairs),'source_inherited_new_crossings':sorted(pairs&internal),
                    'new_cross_component_crossings':sorted(external),'contacts':contacts,
                    'unchanged':stroke_payload(glyphs[arm])==stroke_payload(glyphs['A'])}
            write(out/'glyphs'/f'{ord(char):04X}.json',glyphs);records.append(row)
            print(writer,char,{k:v['integrity']['source_strokes'] for k,v in row['arms'].items()},flush=True)
        write(out/'records.json',records);all_records[writer]=records
        assert asdict(profile)==snapshot,'archive mutated'
    frozen_outputs={str(p):sha(p) for p in [*sorted(root.glob('*/glyphs/*.json')),*sorted(root.glob('*/records.json'))]}
    write(root/'generation_freeze.json',{'outputs':frozen_outputs,'evaluation_opened':False})
    summaries={}
    for writer,rows in all_records.items():
        files=sorted(PRIOR.glob('*/evaluation.json')) if writer=='user_001' else [OLD/writer/'evaluation.json']
        evaluations=[];groups=defaultdict(list)
        for file in files:
            for item in load(file):
                char=item['character'];gs=load(root/writer/'glyphs'/f'{ord(char):04X}.json')
                metrics={arm:[stroke_metrics(p,q) for p,q in zip(dict_curves(g),item['original'],strict=True)] for arm,g in gs.items()}
                result={**{k:item[k] for k in ('character','sample_id','original')},'metrics':metrics}
                evaluations.append(result);groups[char].append(result)
        write(root/writer/'evaluation.json',evaluations)
        means={char:{a:{k:float(np.mean([np.mean([s[k] for s in r['metrics'][a]]) for r in items]))
                for k in ('mean_distance','terminal_angle_deg','endpoint_error','absolute_length_error')}
                for a in ARMS} for char,items in groups.items()}
        summaries[writer]={'cases':len(rows),'evaluated_characters':len(groups),'original_samples':len(evaluations),
            'changed':{a:[r['character'] for r in rows if not r['arms'][a]['unchanged']] for a in ARMS},
            'coverage':{a:{k:sum(r['arms'][a]['integrity'][k] for r in rows) for k in ('source_strokes','reference_strokes')} for a in ARMS},
            'rejected_attempt_reasons':{a:dict(Counter(d['fallback_reason'] for r in rows for d in r['arms'][a]['log'].get('placement',[]) if not d['accepted'])) for a in ARMS},
            'character_metrics':means}
    write(root/'summary.json',summaries)
    for hashes in [*frozen.values(),frozen_outputs]:
        for file,digest in hashes.items():assert sha(Path(file))==digest,file
    write(root/'verification.json',{'frozen_inputs_code_outputs_match':True,'profiles_unchanged':True,
        'target_character_groups_excluded':True,'source_geometry_pressure_intrastroke_time_exact':True,
        'baseline_accepted_source_transforms_unchanged':True,'protocol_failures':0,
        'new_cross_component_strict_crossings':0,'new_cross_component_brush_contacts_at_028':0,
        'production_default_changed':False})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
