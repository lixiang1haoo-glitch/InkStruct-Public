"""Receive a frozen collection batch and measure source coverage without retuning."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_v6_exp import archive, sha, write
from run_v61_exp import check_integrity, dict_curves

from inkstruct.alignment import align_sample
from inkstruct.collection_receipt import extract_new_batch, partition_samples
from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.samples import load_raw_sample, merge_indexes
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics
from inkstruct.v61_collection import audit_targets, coverage_summary
from inkstruct.v61_contacts import contact_pairs
from inkstruct.v61_exp import PARAMETERS, V61ExpGenerator

PRIOR = Path('artifacts/v61_collection_20261013/plan_v4')
OLD_INDEX = Path('artifacts/component_aspect_20261007/user001_snapshot/index.jsonl')


def index_file(path, samples):
    with path.open('x') as stream:
        for sample in samples:
            stream.write(json.dumps(asdict(sample),ensure_ascii=False)+'\n')


def run(zip_path, root, frozen_run=None):
    root.mkdir(parents=True,exist_ok=False)
    split = json.loads((PRIOR/'split.json').read_text())
    plan = json.loads((PRIOR/'plan.json').read_text())
    training = {r['character'] for r in plan['recommendations']}
    excluded = set(split['development_regression']) | set(split['prospective_validation'])
    db = Path('artifacts/full_library_20261010/inputs/characters.sqlite3')
    correction = [Path('third_party/makemeahanzi/graphics.txt'),
                  Path('third_party/makemeahanzi/dictionary.txt'),
                  Path('configs/structure_overrides/unclipped_reference_v1.json')]
    inputs = [zip_path,OLD_INDEX,PRIOR/'split.json',PRIOR/'plan.json',
              PRIOR/'audit_source_archive.json',PRIOR/'development_audit.json',
              PRIOR/'validation_audit.json',
              Path('artifacts/v61_exp_20261013/run_v2/user_001/evaluation.json'),db,*correction]
    if frozen_run:
        inputs += [frozen_run/'source_archive.json',frozen_run/'protocol.json',
                   *sorted(frozen_run.glob('*/glyphs/*.json'))]
    code = [Path(__file__),Path('scripts/run_v6_exp.py'),Path('scripts/run_v61_exp.py'),
            *sorted(Path('src/inkstruct').glob('*.py'))]
    frozen = {kind:{str(p):sha(p) for p in paths} for kind,paths in [('inputs',inputs),('code',code)]}
    write(root/'protocol.json',{'name':'v6.1 exp frozen collection acceptance',**frozen,
        'code_commit_before_run':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'parameters':PARAMETERS,'generator':'V61ExpGenerator.prepare baseline_plan; same as collection forecast',
        'arms':{'before':'frozen existing complete sources','after':'same generator plus admitted training captures'},
        'changed_factor':'source pool only, including the consequent fixed-policy selection changes',
        'retuning':False,'target_originals':'opened only after all generation outputs are saved',
        'frozen_generation_comparison':str(frozen_run) if frozen_run else None,
        'production_default_changed':False,'heldout_all_repeats_excluded':sorted(excluded)})
    shutil.copyfile(zip_path,root/'received_original.zip')
    paths = extract_new_batch(root/'received_original.zip',root/'received')
    samples, failures = [], []
    for path in paths:
        try:
            samples.append(load_raw_sample(path,expected_writer='user_001'))
        except (ValueError,OSError) as error:
            failures.append({'path':str(path),'reason':str(error)})
    groups = partition_samples(samples,training,excluded)
    for key, rows in groups.items():
        index_file(root/f'{key}.jsonl',rows)
    counts = Counter(s.character for s in groups['training'])
    intake = {'zip_sha256':sha(zip_path),'raw_json_files':len(paths),'raw_valid':len(samples),
        'raw_rejected':failures,'training_counts':dict(counts),
        'missing_training_repeats':{c:max(0,2-counts[c]) for c in sorted(training) if counts[c]<2},
        'evaluation_received':dict(Counter(s.character for s in groups['evaluation'])),
        'unplanned_received':dict(Counter(s.character for s in groups['unplanned'])),
        'missing_validation_characters':sorted(set(split['prospective_validation'])-
            {s.character for s in groups['evaluation']}),
        'files':{str(p):sha(p) for p in paths}}
    write(root/'intake.json',intake)
    merge = merge_indexes([OLD_INDEX,root/'training.jsonl'],'user_001',root/'merged')
    write(root/'merge.json',merge)
    base = StructureRepository(db)
    target = CorrectedStructureRepository(base,*correction)
    profile,rejected = archive(Path(merge['index']),base,excluded)
    old = load_profile(PRIOR/'audit_source_archive.json')
    assert all(json.loads(json.dumps(asdict(s)))==json.loads(json.dumps(asdict(profile.source_trajectories[k])))
               for k,s in old.source_trajectories.items())
    assert not excluded & {s.character for s in profile.source_trajectories.values()}
    write(root/'source_archive.json',asdict(profile))
    if frozen_run:
        frozen_sources=load_profile(frozen_run/'source_archive.json')
        canonical=lambda p:json.loads(json.dumps({k:asdict(v) for k,v in p.source_trajectories.items()}))
        assert canonical(profile)==canonical(frozen_sources),'training source changed after generation freeze'
    write(root/'source_exclusions.json',rejected)
    new_ids = {s.sample_id for s in groups['training']}
    new_sources = {k:s for k,s in profile.source_trajectories.items() if k in new_ids}
    mapped = []
    for sample in groups['training']:
        aligned = align_sample(sample,base.get(sample.character))
        mapped.append({'character':sample.character,'sample_id':sample.sample_id,
            'raw_strokes':len(sample.strokes),'standard_strokes':len(base.get(sample.character).strokes),
            'stroke_order_status':aligned.stroke_order_status,'mappings':[asdict(m) for m in aligned.mappings],
            'admitted':sample.sample_id in new_sources,
            'reason':next((r['reason'] for r in rejected if r['sample_id']==sample.sample_id),None)})
    write(root/'new_mapping_audit.json',mapped)
    print('intake',len(samples),'training',len(groups['training']),'new complete sources',len(new_sources),flush=True)
    engines = {'before':V61ExpGenerator(old,base,target),'after':V61ExpGenerator(profile,base,target)}
    split_results = {}
    for split_name,chars in [('regression',split['development_regression']),
                             ('prospective',split['prospective_validation'])]:
        out = root/split_name
        (out/'glyphs').mkdir(parents=True)
        audits = {}
        for arm,engine in engines.items():
            slots,glyphs = audit_targets(engine,chars)
            audits[arm] = {'slots':slots,'glyphs':glyphs,'summary':coverage_summary(slots,glyphs)}
            write(out/f'{arm}_audit.json',audits[arm])
        expected = json.loads((PRIOR/('development_audit.json' if split_name=='regression' else 'validation_audit.json')).read_text())
        for c in chars:
            assert audits['before']['glyphs'][c]['baseline']['strokes']==expected['glyphs'][c]['baseline']['strokes']
        rows = []
        for c in chars:
            glyphs = {arm:audits[arm]['glyphs'][c]['baseline'] for arm in engines}
            if frozen_run:
                frozen_glyphs=json.loads((frozen_run/split_name/'glyphs'/f'{ord(c):04X}.json').read_text())
                assert all(glyphs[a]['strokes']==frozen_glyphs[a]['strokes'] for a in engines)
            write(out/'glyphs'/f'{ord(c):04X}.json',glyphs)
            xy = {arm:dict_curves(g) for arm,g in glyphs.items()}
            provenance,integrity,checks = {},{},{}
            for arm,engine in engines.items():
                ctx = engine.prepare(c)
                integrity[arm] = check_integrity(engine,ctx,ctx.baseline,ctx.baseline_plan)
                checks[arm] = {'protocol':invariants(ctx.baseline,ctx.graph),
                    'degenerate':[i+1 for i,s in enumerate(xy[arm]) if path_length(s)<.003]}
                provenance[arm] = [asdict(p) for p in ctx.baseline_plan.values()]
            rows.append({'character':c,'changed':xy['before']!=xy['after'],
                'provenance':provenance,'integrity':integrity,'checks':checks,
                'new_crossings':sorted(crossing_pairs(xy['after'])-crossing_pairs(xy['before'])),
                'removed_crossings':sorted(crossing_pairs(xy['before'])-crossing_pairs(xy['after'])),
                'new_brush_contacts':{str(w):sorted(contact_pairs(xy['after'],w)-contact_pairs(xy['before'],w))
                                      for w in (.014,.028,.05)},
                'removed_brush_contacts':{str(w):sorted(contact_pairs(xy['before'],w)-contact_pairs(xy['after'],w))
                                          for w in (.014,.028,.05)}})
        write(out/'records.json',rows)
        split_results[split_name] = {'before':audits['before']['summary'],'after':audits['after']['summary'],
            'changed_characters':[r['character'] for r in rows if r['changed']],
            'new_crossing_characters':[r['character'] for r in rows if r['new_crossings']],
            'new_brush_contact_characters':{str(w):[r['character'] for r in rows if r['new_brush_contacts'][str(w)]]
                                            for w in (.014,.028,.05)}}
        if split_name=='regression':
            conversion = []
            for slot_id in plan['projected_first_source_slots']:
                slot = audits['after']['slots'][slot_id]
                conversion.append({'slot_id':slot_id,'character':slot['character'],'canonical':slot['canonical'],
                    'stroke_count':slot['stroke_count'],'now_selected':slot['actual_selected'],
                    'safe_donor_characters':slot['safe_donor_characters'],'status':slot['status']})
            write(root/'forecast_conversion.json',conversion)
        print(split_name,split_results[split_name],flush=True)
    # No original may influence generation: all arm files exist before this stage.
    originals = json.loads(Path('artifacts/v61_exp_20261013/run_v2/user_001/evaluation.json').read_text())
    evaluation = []
    for item in originals:
        c = item['character']
        glyphs = json.loads((root/'regression'/'glyphs'/f'{ord(c):04X}.json').read_text())
        metrics = {arm:[stroke_metrics(p,q) for p,q in zip(dict_curves(g),item['original'],strict=True)]
                   for arm,g in glyphs.items()}
        evaluation.append({**{k:item[k] for k in ('character','sample_id','original')},'metrics':metrics,
            'means':{arm:{k:float(np.mean([s[k] for s in ss])) for k in
                         ('mean_distance','max_distance','terminal_angle_deg','absolute_length_error')}
                     for arm,ss in metrics.items()}})
    write(root/'regression'/'evaluation.json',evaluation)
    # This receipt may contain future evaluation captures; retain and evaluate them
    # only after generation, without ever putting them in the merged training index.
    validation_evaluation = []
    validation_exclusions = []
    for sample in groups['evaluation']:
        if sample.character not in split['prospective_validation']:
            continue
        from inkstruct.source_trajectory import source_trajectory
        graph = base.get(sample.character)
        source,reason = source_trajectory(sample,align_sample(sample,graph),graph)
        if source is None:
            validation_exclusions.append({'character':sample.character,'sample_id':sample.sample_id,'reason':reason})
            continue
        original = [s.points for s in source.strokes]
        glyphs = json.loads((root/'prospective'/'glyphs'/f'{ord(sample.character):04X}.json').read_text())
        validation_evaluation.append({'character':sample.character,'sample_id':sample.sample_id,'original':original,
            'metrics':{arm:[stroke_metrics(p,q) for p,q in zip(dict_curves(g),original,strict=True)]
                       for arm,g in glyphs.items()}})
    write(root/'prospective'/'evaluation.json',validation_evaluation)
    write(root/'prospective'/'evaluation_exclusions.json',validation_exclusions)
    summary = {'intake':intake,'new_complete_samples':len(new_sources),
        'new_complete_characters':dict(Counter(s.character for s in new_sources.values())),
        'old_archive_samples':old.sample_count,'new_archive_samples':profile.sample_count,
        'new_mapping_rejections':[r for r in rejected if r['sample_id'] in new_ids],
        'splits':split_results,'regression_original_samples':len(evaluation),
        'prospective_original_samples':len(validation_evaluation)}
    write(root/'summary.json',summary)
    for group in frozen.values():
        assert all(sha(Path(p))==h for p,h in group.items())
    assert all(sha(Path(p))==h for p,h in intake['files'].items())
    write(root/'verification.json',{'input_code_and_raw_hashes_unchanged':True,
        'old_source_payloads_unchanged':True,'all_target_character_groups_excluded':True,
        'before_31_stroke_payloads_match_frozen_planner':True,'retuning':False,
        'both_arms_match_pre_validation_generation':bool(frozen_run),
        'production_default_changed':False,'missing_validation_originals':intake['missing_validation_characters']})


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frozen-run',type=Path)
    args = parser.parse_args()
    run(args.zip,args.output,args.frozen_run)
