"""Training-only paired layout trials using frozen crossfit source components."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from experiment_component_trust import glyph_from_dict, mean_present, read
from regress_calibrated_layout_writers import audit_generated
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.layout_risk import move_features, training_fold
from inkstruct.learned_component_layout import place_with_learned_layout
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import stroke_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prior = read(args.prior / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in prior[group].items():
            assert sha256_file(Path(name)) == expected, name
    manifest = read(args.prior / 'generation_manifest.json')
    for name, expected in manifest.items():
        assert sha256_file(Path(name)) == expected, name
    config_path = Path('configs/experiments/counterfactual_layout_risk_v1.json')
    config = read(config_path)
    args.output.mkdir(parents=True, exist_ok=False)
    extra = [config_path, args.prior / 'run_protocol.json', args.prior / 'generation_manifest.json', args.prior / 'examples.json']
    code = [Path(__file__), Path('src/inkstruct/counterfactual_layout_risk.py')]
    save(args.output / 'run_protocol.json', {'config': config, 'datasets': prior['datasets'], 'prior': str(args.prior),
        'input_sha256': {**prior['input_sha256'], **{str(p): sha256_file(p) for p in extra}},
        'code_sha256': {**prior['code_sha256'], **{str(p): sha256_file(p) for p in code}}})
    repository = StructureRepository(DATABASE)
    pending, audit, coverage = [], Counter(), {w: Counter() for w in prior['datasets']}
    for fold_file in sorted(args.prior.glob('*/fold_*/fold_manifest.json')):
        fold = read(fold_file)
        writer = fold_file.parent.parent.name
        profile = load_profile(Path(fold['profile']))
        assert sha256_file(Path(fold['profile'])) == fold['profile_sha256']
        assert all(training_fold(s.character) != fold['fold'] for s in profile.source_trajectories.values())
        for path in sorted((fold_file.parent / 'generated').glob('*.json')):
            old = read(path)
            metadata, prediction = old['metadata']['D'], old['predictions']['learned']
            band = old['metadata']['B'].get('layout_band', {})
            if metadata['selected'] is None or not prediction.get('available') or 'distance_before' not in band:
                coverage[writer]['ineligible_component'] += 1
                continue
            coverage[writer]['eligible_components'] += 1
            graph = repository.get(old['task']['character'])
            component = next(c for c in graph.components if c.component_id == old['task']['component_id'])
            base, original = [glyph_from_dict(old['outputs'][k]) for k in ('A', 'D')]
            for strength in config['strengths']:
                output, meta = place_with_learned_layout(base, original, metadata, graph, component, profile.source_trajectories, old['predictions']['public'], strength)
                changed = asdict(output) != old['outputs']['D']
                trial = {'writer': writer, 'task': old['task'], 'proposal_id': f'public_{strength}', 'strength': strength,
                    'frozen_input': str(path), 'frozen_input_sha256': sha256_file(path),
                    'output': asdict(output), 'metadata': meta, 'changed': changed,
                    'features': move_features(graph, component, original, output, prediction, {**band, 'effective_strength': strength}) if changed else None}
                check = {'task': old['task'], 'outputs': {'A': old['outputs']['A'], 'D': old['outputs']['D'], 'P': trial['output'], 'off': old['outputs']['D']},
                    'metadata': {'D': metadata, 'P': meta, 'off': metadata}, 'predictions': old['predictions']}
                audit.update(audit_generated(check, profile.source_trajectories, repository))
                target = args.output / writer / ('generated') / (old['task']['id']+'-'+trial['proposal_id']+'.json')
                save(target, trial)
                pending.append(target)
                coverage[writer]['trials'] += 1
                coverage[writer]['changed'] += changed
        print('generated', writer, fold['fold'], dict(coverage[writer]), flush=True)
    save(args.output / 'generation_manifest.json', {str(p): sha256_file(p) for p in pending})
    save(args.output / 'integrity_audit.json', dict(audit))
    examples = []
    for writer, dataset in prior['datasets'].items():
        gold = defaultdict(list)
        for sample in load_profile(Path(dataset['archive'])).source_trajectories.values():
            gold[sample.character].append(sample)
        baseline_cache = {}
        for path in pending:
            if path.parent.parent.name != writer:
                continue
            trial = read(path)
            if not trial['changed']:
                continue
            character = trial['task']['character']
            if not gold[character]:
                coverage[writer]['changed_without_valid_gold'] += 1
                continue
            old = read(Path(trial['frozen_input']))
            ids = trial['task']['target_stroke_ids']
            graph = repository.get(character)
            indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
            metrics = {}
            for label, payload in [('D', old['outputs']['D']), ('P', trial['output'])]:
                cache_key = trial['frozen_input']
                if label == 'D' and cache_key in baseline_cache:
                    metrics[label] = baseline_cache[cache_key]
                    continue
                xy = curves(glyph_from_dict(payload))
                captures = []
                for source in gold[character]:
                    mapping = {s.standard_stroke_id: s.points for s in source.strokes}
                    captures.append({graph.strokes[i].stroke_id: stroke_metrics(xy[i], mapping[graph.strokes[i].stroke_id]) for i in indices})
                metrics[label] = {sid: {key: mean_present([capture[sid][key] for capture in captures])
                    for key in ('mean_distance', 'max_distance', 'terminal_angle_deg')} for sid in ids}
                if label == 'D':
                    baseline_cache[cache_key] = metrics[label]
            dmean = float(np.mean([p['mean_distance'] for p in metrics['D'].values()]))
            pmean = float(np.mean([p['mean_distance'] for p in metrics['P'].values()]))
            ratio = pmean/max(dmean, 1e-12)
            local = max(metrics['P'][sid]['max_distance']-metrics['D'][sid]['max_distance'] for sid in ids)
            angle = float(np.mean([metrics['P'][sid]['terminal_angle_deg']-metrics['D'][sid]['terminal_angle_deg'] for sid in ids]))
            example = {'writer': writer, 'character': character, 'component_id': trial['task']['component_id'],
                'proposal_id': trial['proposal_id'], 'features': trial['features'], 'geometry_ratio': ratio,
                'local_increase': local, 'angle_increase': angle, 'safe_benefit': ratio < 1.-1e-12 and local <= .005+1e-12 and angle <= .5+1e-12,
                'fold': trial['task']['fold'], 'generated_file': str(path), 'generated_sha256': sha256_file(path),
                'references': [{'sample_id': s.sample_id, 'source_sha256': s.source_sha256} for s in gold[character]]}
            examples.append(example)
            save(args.output / 'labeled' / path.name, {**example, 'metrics': metrics})
            coverage[writer]['labeled'] += 1
            coverage[writer]['safe_benefit'] += example['safe_benefit']
        coverage[writer]['labeled_characters'] = len({e['character'] for e in examples if e['writer'] == writer})
        print('scored', writer, dict(coverage[writer]), flush=True)
    save(args.output / 'examples.json', examples)
    save(args.output / 'coverage.json', coverage)
    print('complete', flush=True)


if __name__ == '__main__':
    main()
