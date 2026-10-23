"""Frozen A/B/C/D root-component and reviewed-source-topology admission probe."""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_v6_exp import sha, write
from run_v61_exp import check_integrity, dict_curves

from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics
from inkstruct.v61_admission_exp import AdmissionProbeGenerator
from inkstruct.v61_contacts import contact_pairs

PRIOR = Path('artifacts/v61_collection_acceptance_20261013/run_v3_with_validation')
SPLIT = Path('artifacts/v61_collection_20261013/plan_v4/split.json')
ROOT_CONTEXTS = ('同|同|right|⿰|6',)
ARMS = {'A':'current frozen complete-trajectory generator',
        'B':'A plus ordered whole-root 同 bridge only',
        'C':'A plus explicitly reviewed source-internal 白 crossing only',
        'D':'B and C combined'}


def load(path):
    return json.loads(path.read_text())


def stroke_payload(glyph):
    # Existing v61 emit changes provenance label vocabulary relative to v6;
    # compare every stroke field except those two descriptive labels.
    return [{k:v for k,v in s.items() if k not in ('style_source','component_key')}
            for s in glyph['strokes']]


def run(root, review_path):
    root.mkdir(parents=True, exist_ok=False)
    (root/'glyphs').mkdir()
    db = Path('artifacts/full_library_20261010/inputs/characters.sqlite3')
    correction = [Path('third_party/makemeahanzi/graphics.txt'),
                  Path('third_party/makemeahanzi/dictionary.txt'),
                  Path('configs/structure_overrides/unclipped_reference_v1.json')]
    inputs = [PRIOR/'source_archive.json', PRIOR/'protocol.json', SPLIT, review_path, db, *correction,
              *sorted(PRIOR.glob('*/glyphs/*.json')), *sorted(PRIOR.glob('*/evaluation.json'))]
    code = [Path(__file__),Path('scripts/run_v61_exp.py'),Path('scripts/run_v6_exp.py'),
            *sorted(Path('src/inkstruct').glob('*.py'))]
    frozen = {kind:{str(p):sha(p) for p in paths} for kind,paths in [('inputs',inputs),('code',code)]}
    review = load(review_path)
    split = load(SPLIT)
    cohorts = {'regression':split['development_regression'], 'previous_validation':split['prospective_validation']}
    targets = {char for chars in cohorts.values() for char in chars}
    profile = load_profile(PRIOR/'source_archive.json')
    assert not targets & {s.character for s in profile.source_trajectories.values()}
    protocol = {'name':'v6.1 exp bounded source admission', **frozen,
        'code_commit_before_run':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'arms':ARMS,'root_context_allowlist':ROOT_CONTEXTS,'source_review':review,
        'cohorts':cohorts,'all_cases_status':'previously observed regression, not new blind holdout',
        'parameters':'unchanged existing mapping/reference/fit thresholds; .028 external brush gate',
        'retuning':False,'target_originals':'read after output hashes freeze; excluded as whole character groups',
        'changed_factors':'B expands source role from whole glyph to component; C corrects source-internal topology admission; neither changes ranking or layout',
        'production_default_changed':False}
    write(root/'protocol.json',protocol)
    engine = AdmissionProbeGenerator(profile,StructureRepository(db),CorrectedStructureRepository(StructureRepository(db),*correction))
    records=[]
    for cohort,chars in cohorts.items():
        olddir = PRIOR/('prospective' if cohort=='previous_validation' else 'regression')
        for char in chars:
            ctx=engine.prepare(char)
            old=load(olddir/'glyphs'/f'{ord(char):04X}.json')['after']
            assert json.loads(json.dumps(asdict(ctx.baseline)))==old, f'baseline drift: {char}'
            variants={'A':(ctx.baseline,ctx.baseline_plan,{})}
            for arm,roots,reviews in [('B',ROOT_CONTEXTS,()),('C',(),[review]),('D',ROOT_CONTEXTS,[review])]:
                variants[arm]=engine.probe(ctx,root_contexts=roots,reviews=reviews)
            glyphs={arm:asdict(g) for arm,(g,_,_) in variants.items()}
            row={'character':char,'cohort':cohort,'arms':{}}
            before=dict_curves(old)
            for arm,(glyph,plan,log) in variants.items():
                xy=dict_curves(glyphs[arm])
                own={i:p.component_id for p in plan.values() for i in p.indices}
                contacts={}
                for width in (.014,.028,.05):
                    added=contact_pairs(xy,width)-contact_pairs(before,width)
                    contacts[str(width)]={'new':sorted(added),
                        'new_between_sources_or_reference':sorted((a,b) for a,b in added if own.get(a,f'ref:{a}')!=own.get(b,f'ref:{b}')),
                        'removed':sorted(contact_pairs(before,width)-contact_pairs(xy,width))}
                row['arms'][arm]={'provenance':[asdict(p) for p in plan.values()],
                    'integrity':check_integrity(engine,ctx,glyph,plan),'log':log,
                    'protocol':invariants(glyph,ctx.graph),'degenerate':[i+1 for i,s in enumerate(xy) if path_length(s)<.003],
                    'new_crossings':sorted(crossing_pairs(xy)-crossing_pairs(before)),
                    'removed_crossings':sorted(crossing_pairs(before)-crossing_pairs(xy)),
                    'contacts':contacts,'strokes_exactly_unchanged':stroke_payload(glyphs[arm])==stroke_payload(old),
                    'label_metadata_changed':glyphs[arm]['strokes']!=old['strokes'] and stroke_payload(glyphs[arm])==stroke_payload(old)}
                assert not row['arms'][arm]['protocol'] and not row['arms'][arm]['degenerate']
            assert glyphs['B']['strokes']==glyphs['D']['strokes'] if char=='铜' else True
            assert glyphs['C']['strokes']==glyphs['D']['strokes'] if char=='伯' else True
            if char not in '铜伯':
                assert all(r['strokes_exactly_unchanged'] for r in row['arms'].values())
            write(root/'glyphs'/f'{ord(char):04X}.json',glyphs)
            records.append(row)
            print(char, {a:r['integrity']['source_strokes'] for a,r in row['arms'].items()},flush=True)
    write(root/'records.json',records)
    output_hashes={str(p):sha(p) for p in sorted(root.glob('glyphs/*.json'))}
    write(root/'generation_freeze.json',{'outputs':output_hashes,'records':sha(root/'records.json'),
        'target_originals_opened_in_this_run':False})
    # No target originals are loaded until all arms are frozen. These are already
    # observed data, so this ordering prevents leakage here, not historical exposure.
    evaluations=[]
    for file in sorted(PRIOR.glob('*/evaluation.json')):
        for item in load(file):
            char=item['character']
            gs=load(root/'glyphs'/f'{ord(char):04X}.json')
            metrics={arm:[stroke_metrics(p,q) for p,q in zip(dict_curves(g),item['original'],strict=True)] for arm,g in gs.items()}
            evaluations.append({**{k:item[k] for k in ('character','sample_id','original')},'metrics':metrics})
    write(root/'evaluation.json',evaluations)
    character_metrics={}
    grouped=defaultdict(list)
    for r in evaluations:grouped[r['character']].append(r)
    for char,items in grouped.items():
        character_metrics[char]={arm:{key:float(np.mean([np.mean([s[key] for s in r['metrics'][arm] if s[key] is not None]) for r in items]))
                for key in ('mean_distance','max_distance','endpoint_error','terminal_angle_deg','absolute_length_error')}
            for arm in ARMS}
    summary={'cases':len(records),'original_samples':len(evaluations),'original_character_groups':len(grouped),
        'changed_characters':{a:[r['character'] for r in records if not r['arms'][a]['strokes_exactly_unchanged']] for a in ARMS},
        'coverage':{a:{c:{k:sum(r['arms'][a]['integrity'][k] for r in records if r['cohort']==c)
            for k in ('source_strokes','reference_strokes')} for c in cohorts} for a in ARMS},
        'character_metrics':character_metrics,'protocol_failures':0,'degenerate_strokes':0,
        'protection_characters_exactly_unchanged':len(records)-2,'production_default_changed':False}
    write(root/'summary.json',summary)
    for hashes in frozen.values():
        for file,digest in hashes.items():assert sha(Path(file))==digest, file
    for file,digest in output_hashes.items():assert sha(Path(file))==digest
    write(root/'verification.json',{'input_code_and_outputs_unchanged':True,
        'target_groups_excluded':True,'all_source_points_pressure_intrastroke_time_exact':True,
        'protocol_failures':0,'production_default_changed':False})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--review',type=Path,required=True,help='Private source-bound visual review JSON; never commit personal IDs.')
    args=p.parse_args()
    run(args.output,args.review)
