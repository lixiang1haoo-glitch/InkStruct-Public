"""Expand risk supervision to all compatible components in frozen crossfit folds."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from confirm_contextual_trajectory import split
from experiment_component_trust import glyph_from_dict, mean_present, read
from regress_calibrated_layout_writers import audit_generated
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.calibrated_component_layout import (
    CalibratedComponentLayoutEvidence,
    place_with_calibrated_layout,
)
from inkstruct.contextual_trajectory import choose_component
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.generate import DeterministicGenerator
from inkstruct.layout_risk import move_features, training_fold
from inkstruct.learned_component_layout import place_with_learned_layout, public_layout
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
    old_manifest = read(args.prior / 'generation_manifest.json')
    for name, expected in old_manifest.items():
        assert sha256_file(Path(name)) == expected, name
    data = prior['datasets']
    config = Path('configs/experiments/component_layout_risk_v1.json')
    manifests = sorted(args.prior.glob('*/fold_*/fold_manifest.json'))
    inputs = [config, args.prior / 'run_protocol.json', args.prior / 'generation_manifest.json', args.prior / 'examples.json']
    for path in manifests:
        m = read(path)
        inputs += [path, Path(m['profile']), path.parent / 'calibration.json']
        assert sha256_file(Path(m['profile'])) == m['profile_sha256']
        assert sha256_file(path.parent / 'index.jsonl') == m['index_sha256']
    args.output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), Path('src/inkstruct/component_layout_risk.py')]
    save(args.output / 'run_protocol.json', {'config': read(config), 'datasets': data, 'prior': str(args.prior),
        'input_sha256': {**prior['input_sha256'], **{str(p): sha256_file(p) for p in inputs}},
        'code_sha256': {**prior['code_sha256'], **{str(p): sha256_file(p) for p in code}}})
    repository = StructureRepository(DATABASE)
    pending, audit, coverage = [], Counter(), {w: Counter() for w in data}
    replays = 0
    for manifest_path in manifests:
        fold_manifest = read(manifest_path)
        old_root = manifest_path.parent
        writer, fold = old_root.parent.name, fold_manifest['fold']
        root = args.output / writer / f'fold_{fold}'
        root.mkdir(parents=True)
        save(root / 'fold_manifest.json', {**fold_manifest, 'frozen_manifest': str(manifest_path),
                                          'frozen_manifest_sha256': sha256_file(manifest_path)})
        profile = load_profile(Path(fold_manifest['profile']))
        index = ExemplarIndex(profile, repository)
        assert all(training_fold(s.character) != fold for s in index.sources.values())
        evidence = CalibratedComponentLayoutEvidence(index)
        calibration = read(old_root / 'calibration.json')
        assert evidence.calibrate() == calibration
        save(root / 'calibration.json', calibration)
        generator = DeterministicGenerator(profile, repository.metadata()['source_version'], 'adaptive', 1.)
        for character in fold_manifest['target_characters']:
            try:
                graph = repository.get(character)
            except KeyError:
                continue
            slots = [(c, index.candidates(graph, c)) for c in graph.components if c.path != 'root' and not c.children_ids
                     and len(c.stroke_ids) >= 2 and c.confidence >= .8]
            slots = [(c, candidates) for c, candidates in slots if candidates]
            if not slots:
                continue
            coverage[writer]['generated_characters'] += 1
            base = generator.generate(graph)
            old_path = old_root / 'generated' / f'{writer}-crossfit-U+{ord(character):04X}.json'
            old = read(old_path)
            for component, candidates in slots:
                ids = ordered_ids(graph, component)
                original, dm = choose_component(base, graph, ids, candidates, index.sources, field_strength=0., max_candidates=16)
                predicted = evidence.predict(graph, component)
                center, span, _ = public_layout(graph, component)
                public = {'available': True, 'center': center.tolist(), 'span': span, 'policy': 'public_normalized_layout_control'}
                b, bm = place_with_calibrated_layout(base, original, dm, graph, component, index.sources, predicted, calibration, 1.)
                band = bm.get('layout_band', {})
                m, mm = place_with_learned_layout(base, original, dm, graph, component, index.sources, public, band.get('effective_strength', 0.))
                changed = asdict(m) != asdict(original)
                task = {'id': f'{writer}-allcomponents-U+{ord(character):04X}-{component.component_id}', 'character': character,
                        'component_id': component.component_id, 'target_stroke_ids': ids, 'fold': fold}
                row = {'writer': writer, 'task': task, 'outputs': {k: asdict(v) for k, v in [('A', base), ('D', original), ('B', b), ('M', m), ('off', original)]},
                    'metadata': {'D': dm, 'B': bm, 'M': mm, 'off': dm}, 'predictions': {'learned': predicted, 'public': public},
                    'changed': changed, 'features': move_features(graph, component, original, m, predicted, band) if changed else None}
                if component.component_id == old['task']['component_id']:
                    # Diagnostic crossing pairs are tuples in memory, lists in
                    # persisted JSON; compare the same serialized representation.
                    assert json.loads(json.dumps(row['outputs'])) == old['outputs']
                    assert json.loads(json.dumps(row['metadata'])) == old['metadata']
                    assert row['features'] == old['features']
                    replays += 1
                for candidate in candidates+predicted.get('reference_sources', []):
                    assert training_fold(candidate['character']) != fold
                audit.update(audit_generated(row, index.sources, repository))
                path = root / 'generated' / (task['id']+'.json')
                save(path, row)
                pending.append(path)
                coverage[writer]['generated'] += 1
                coverage[writer]['changed'] += changed
        print('generated', writer, fold, dict(coverage[writer]), flush=True)
    assert replays == len(old_manifest)
    save(args.output / 'prior_replay.json', {'matched_complete_prior_outputs': replays, 'expected': len(old_manifest)})
    save(args.output / 'generation_manifest.json', {str(p): sha256_file(p) for p in pending})
    save(args.output / 'integrity_audit.json', dict(audit))
    examples = []
    for writer, d in data.items():
        sources = load_profile(Path(d['archive'])).source_trajectories
        targets = defaultdict(list)
        for sample in sources.values():
            if split(sample.character) == 'train':
                targets[sample.character].append(sample)
        for path in pending:
            if path.parent.parent.parent.name != writer:
                continue
            row = read(path)
            if not row['changed']:
                continue
            character = row['task']['character']
            if not targets[character]:
                coverage[writer]['changed_without_valid_gold'] += 1
                continue
            ids = row['task']['target_stroke_ids']
            graph = repository.get(character)
            indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
            metrics = {}
            for label in ('D', 'M'):
                xy = curves(glyph_from_dict(row['outputs'][label]))
                per_capture = []
                for sample in targets[character]:
                    mapping = {s.standard_stroke_id: s.points for s in sample.strokes}
                    per_capture.append({graph.strokes[i].stroke_id: stroke_metrics(xy[i], mapping[graph.strokes[i].stroke_id]) for i in indices})
                metrics[label] = {sid: {key: mean_present([capture[sid][key] for capture in per_capture])
                    for key in ('mean_distance', 'max_distance', 'terminal_angle_deg')} for sid in ids}
            dmean = float(np.mean([s['mean_distance'] for s in metrics['D'].values()]))
            mmean = float(np.mean([s['mean_distance'] for s in metrics['M'].values()]))
            ratio = mmean/max(dmean, 1e-12)
            local = max(metrics['M'][sid]['max_distance']-metrics['D'][sid]['max_distance'] for sid in ids)
            angle = float(np.mean([metrics['M'][sid]['terminal_angle_deg']-metrics['D'][sid]['terminal_angle_deg'] for sid in ids]))
            example = {'writer': writer, 'character': character, 'features': row['features'], 'geometry_ratio': ratio,
                'local_increase': local, 'angle_increase': angle, 'safe_benefit': ratio < 1.-1e-12 and local <= .005+1e-12 and angle <= .5+1e-12,
                'component_id': row['task']['component_id'], 'fold': row['task']['fold'], 'generated_file': str(path), 'generated_sha256': sha256_file(path),
                'references': [{'sample_id': s.sample_id, 'source_sha256': s.source_sha256} for s in targets[character]]}
            examples.append(example)
            save(args.output / 'labeled' / path.name, {**example, 'metrics': metrics})
            coverage[writer]['labeled'] += 1
            coverage[writer]['safe_benefit'] += example['safe_benefit']
    for writer in data:
        coverage[writer]['labeled_characters'] = len({e['character'] for e in examples if e['writer'] == writer})
    save(args.output / 'examples.json', examples)
    save(args.output / 'coverage.json', coverage)
    print('complete', {w: dict(c) for w, c in coverage.items()}, flush=True)


if __name__ == '__main__':
    main()
