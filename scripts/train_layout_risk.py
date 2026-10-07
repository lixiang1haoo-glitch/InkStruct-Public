"""Create paired correction outcomes with character-crossfit v4/source profiles."""
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
from inkstruct.profile import build_profile, load_profile
from inkstruct.samples import iter_index, sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import stroke_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = Path('configs/experiments/crossfit_layout_risk_v1.json')
    batch_path = Path('artifacts/author_terminal_context_20261007/batch_v1/plan.json')
    batch = read(batch_path)
    data = {w: {'index': f'artifacts/samples/{w}/index.jsonl',
        'archive': f'profiles/source_v1_20261007/{w}/profile.json'} for w in ('scx', 'mjb')}
    data['wsq'] = {'index': 'artifacts/samples/wsq/index.jsonl', 'archive': 'profiles/terminal_20261007/source/wsq/profile.json'}
    data['user_001'] = {'index': batch['train_index'], 'archive': batch['profile']}
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = [config, batch_path, DATABASE]+[Path(p) for d in data.values() for p in d.values()]
    code = [Path(__file__), Path('scripts/regress_calibrated_layout_writers.py'), Path('scripts/confirm_contextual_trajectory.py')]
    code += [Path('src/inkstruct') / (name+'.py') for name in ('layout_risk', 'profile', 'alignment', 'source_trajectory', 'contextual_trajectory',
        'exemplar_index', 'trajectory_experiment', 'generate', 'learned_component_layout', 'calibrated_component_layout')]
    save(args.output / 'run_protocol.json', {'config': read(config), 'datasets': data,
        'input_sha256': {str(p): sha256_file(p) for p in inputs}, 'code_sha256': {str(p): sha256_file(p) for p in code}})
    repository = StructureRepository(DATABASE)
    pending, audit, coverage = [], Counter(), {}
    for writer, d in data.items():
        samples = [s for s in iter_index(Path(d['index'])) if split(s.character) == 'train']
        assert samples and all(s.writer_id == writer for s in samples)
        chars = sorted({s.character for s in samples})
        coverage[writer] = Counter(train_characters=len(chars), train_captures=len(samples))
        for fold in range(3):
            root = args.output / writer / f'fold_{fold}'
            root.mkdir(parents=True)
            train_index = root / 'index.jsonl'
            with train_index.open('x') as stream:
                for sample in samples:
                    if training_fold(sample.character) != fold:
                        stream.write(json.dumps(asdict(sample), ensure_ascii=False)+'\n')
            profile, profile_path = build_profile(writer, train_index, repository, root / 'profiles', retain_source_trajectories=True)
            assert all(training_fold(s.character) != fold for s in profile.source_trajectories.values())
            index = ExemplarIndex(profile, repository)
            evidence = CalibratedComponentLayoutEvidence(index)
            calibration = evidence.calibrate()
            save(root / 'calibration.json', calibration)
            save(root / 'fold_manifest.json', {'fold': fold, 'training_characters': sorted(c for c in chars if training_fold(c) != fold),
                'target_characters': sorted(c for c in chars if training_fold(c) == fold),
                'profile': str(profile_path), 'profile_sha256': sha256_file(profile_path),
                'index_sha256': sha256_file(train_index)})
            generator = DeterministicGenerator(profile, repository.metadata()['source_version'], 'adaptive', 1.)
            print('profile', writer, fold, profile.sample_count, 'calibrated', calibration['reference_character_count'], flush=True)
            for character in chars:
                if training_fold(character) != fold:
                    continue
                try:
                    graph = repository.get(character)
                except KeyError:
                    coverage[writer]['no_public_structure'] += 1
                    continue
                slots = [(c, index.candidates(graph, c)) for c in graph.components if c.path != 'root' and not c.children_ids
                         and len(c.stroke_ids) >= 2 and c.confidence >= .8]
                slots = [(c, candidates) for c, candidates in slots if candidates]
                if not slots:
                    coverage[writer]['no_donor_task'] += 1
                    continue
                component, candidates = max(slots, key=lambda pair: (len(pair[1]), pair[0].path))
                ids = ordered_ids(graph, component)
                base = generator.generate(graph)
                original, dm = choose_component(base, graph, ids, candidates, index.sources, field_strength=0., max_candidates=16)
                predicted = evidence.predict(graph, component)
                center, span, _ = public_layout(graph, component)
                public = {'available': True, 'center': center.tolist(), 'span': span, 'policy': 'public_normalized_layout_control'}
                b, bm = place_with_calibrated_layout(base, original, dm, graph, component, index.sources, predicted, calibration, 1.)
                band = bm.get('layout_band', {})
                m, mm = place_with_learned_layout(base, original, dm, graph, component, index.sources, public, band.get('effective_strength', 0.))
                changed = asdict(m) != asdict(original)
                task = {'id': f'{writer}-crossfit-U+{ord(character):04X}', 'character': character,
                        'component_id': component.component_id, 'target_stroke_ids': ids, 'fold': fold}
                row = {'writer': writer, 'task': task, 'outputs': {k: asdict(v) for k, v in [('A', base), ('D', original), ('B', b), ('M', m), ('off', original)]},
                    'metadata': {'D': dm, 'B': bm, 'M': mm, 'off': dm}, 'predictions': {'learned': predicted, 'public': public},
                    'changed': changed, 'features': move_features(graph, component, original, m, predicted, band) if changed else None}
                for candidate in candidates+predicted.get('reference_sources', []):
                    assert training_fold(candidate['character']) != fold
                audit.update(audit_generated(row, index.sources, repository))
                path = root / 'generated' / (task['id']+'.json')
                save(path, row)
                pending.append(path)
                coverage[writer]['generated'] += 1
                coverage[writer]['changed'] += changed
            print('generated', writer, fold, dict(coverage[writer]), flush=True)
    # All fold predictions and source choices are immutable before scoring targets.
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
                'fold': row['task']['fold'], 'generated_file': str(path), 'generated_sha256': sha256_file(path),
                'references': [{'sample_id': s.sample_id, 'source_sha256': s.source_sha256} for s in targets[character]]}
            examples.append(example)
            save(args.output / 'labeled' / path.name, {**example, 'metrics': metrics})
            coverage[writer]['labeled'] += 1
            coverage[writer]['safe_benefit'] += example['safe_benefit']
    save(args.output / 'examples.json', examples)
    save(args.output / 'coverage.json', coverage)
    print('complete', {w: dict(c) for w, c in coverage.items()}, flush=True)


if __name__ == '__main__':
    main()
