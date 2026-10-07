"""Freeze on scx development, then evaluate unused scx and untuned mjb targets."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_raw_trajectory_experiment import (
    DATABASE,
    key,
    leaf_components,
    ordered_ids,
    rank,
    save,
    select_candidate,
)

from inkstruct.contextual_trajectory import choose_component
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import bbox
from inkstruct.profile import build_profile, load_profile
from inkstruct.samples import iter_index, sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import (
    assemble,
    crossing_pairs,
    decode_component,
    invariants,
    shared_transform,
    stroke_metrics,
)

BASELINE = Path('artifacts/raw_trajectory_20261007')
CODE = [Path('src/inkstruct/contextual_trajectory.py'),
        Path('src/inkstruct/trajectory_experiment.py'),
        Path('scripts/run_raw_trajectory_experiment.py')]


def read(path):
    return json.loads(path.read_text())


def points(glyph):
    return [[(p.x, p.y) for p in s.points] for s in glyph.strokes]


def split(character):
    if character in '岛尴':
        return 'dev'
    group = int(rank(character)[:8], 16) % 10
    return 'train' if group < 6 else 'dev' if group < 8 else 'test'


def prepare(output):
    output.mkdir(exist_ok=False, parents=True)
    development = read(Path('artifacts/contextual_trajectory_20261007/development_v2/summary.json'))
    guarded = {k: v for k, v in development.items() if k.startswith('guarded_') and v['fallback_count'] <= 16}
    selected = min(guarded, key=lambda k: guarded[k]['mean_distance'])
    strength = float(selected.rsplit('_', 1)[-1])
    repository = StructureRepository(DATABASE)
    already_used = {t['character'] for t in read(BASELINE / 'plan.json')['tasks']}
    datasets = {}
    for writer in ('scx', 'mjb'):
        index = Path(f'artifacts/samples/{writer}/index.jsonl')
        source_path = Path(f'profiles/source_v1_20261007/{writer}/profile.json')
        source = load_profile(source_path).source_trajectories
        by_character = defaultdict(list)
        for s in source.values():
            by_character[s.character].append(s)
        samples = {c: min(v, key=lambda s: rank(s.sample_id)) for c, v in by_character.items()}
        graphs = {c: repository.get(c) for c in samples}
        train_path = output / f'{writer}_train_index.jsonl'
        with train_path.open('x') as f:
            for sample in iter_index(index):
                if split(sample.character) == 'train':
                    f.write(json.dumps(asdict(sample), ensure_ascii=False) + '\n')
        if writer == 'scx':
            profile_path = Path(read(BASELINE / 'plan.json')['train_profile'])
            profile = load_profile(profile_path)
        else:
            profile, profile_path = build_profile(writer, train_path, repository, output / 'profiles_train')
        pool = defaultdict(list)
        for c, sample in samples.items():
            if split(c) != 'train':
                continue
            mapping = {s.standard_stroke_id: s for s in sample.strokes}
            for component in leaf_components(graphs[c]):
                ids = ordered_ids(graphs[c], component)
                confidence = float(np.mean([mapping[k].confidence for k in ids]))
                box = bbox([p for k in ids for p in mapping[k].points])
                if confidence < .55 or min(box[2] - box[0], box[3] - box[1]) < 1e-5:
                    continue
                pool[key(graphs[c], component)].append({'character': c, 'sample_id': sample.sample_id,
                    'component_id': component.component_id, 'stroke_ids': ids,
                    'source_sha256': sample.source_sha256, 'confidence': confidence})
        targets = sorted([c for c in samples if split(c) == 'test'
                          and (writer != 'scx' or c not in already_used)], key=rank)
        groups = defaultdict(list)
        rejected = []
        for c in targets:
            slots = []
            for component in leaf_components(graphs[c]):
                candidates = select_candidate(graphs[c], component, pool, graphs)
                if candidates:
                    slots.append((component, candidates))
            if not slots:
                rejected.append(c)
                continue
            component, candidates = max(slots, key=lambda p: (len(p[1]), p[0].path))
            context = key(graphs[c], component)
            groups[context].append({'id': f'{writer}-fresh-U+{ord(c):04X}', 'character': c,
                'target_sample_id': samples[c].sample_id, 'target_stroke_ids': ordered_ids(graphs[c], component),
                'context': context, 'ranked_candidates': candidates, 'candidate': candidates[0]})
        ordered_groups = [groups[k] for k in sorted(groups)]
        tasks = []
        while ordered_groups and len(tasks) < 64:
            for group in ordered_groups:
                if group and len(tasks) < 64:
                    tasks.append(group.pop(0))
            ordered_groups = [g for g in ordered_groups if g]
        datasets[writer] = {'index': str(index), 'index_sha256': sha256_file(index),
            'sources': str(source_path), 'sources_sha256': sha256_file(source_path),
            'train_profile': str(profile_path), 'train_profile_sha256': sha256_file(profile_path),
            'train_profile_count': profile.sample_count,
            'source_split_counts': dict(Counter(split(c) for c in samples)),
            'available_fresh_targets': len(targets), 'no_compatible_donor': rejected, 'tasks': tasks}
        print(writer, 'fresh tasks', len(tasks), 'eligible raw targets', len(targets), flush=True)
    save(output / 'frozen_plan.json', {'datasets': datasets, 'chosen_development_variant': selected,
        'field_strength': strength, 'max_candidates': 16,
        'selection_rule': 'minimum scx development mean distance among guarded paths with >=50% activation',
        'previously_used_scx_characters': sorted(already_used),
        'code_sha256': {str(p): sha256_file(p) for p in CODE},
        'structure_sha256': sha256_file(DATABASE),
        'development_summary_sha256': sha256_file(Path('artifacts/contextual_trajectory_20261007/development_v2/summary.json'))})


def score(glyph, reference, indices):
    predicted = points(glyph)
    rows = [stroke_metrics(predicted[i], reference[i]) for i in indices]
    return {k: float(np.mean([r[k] for r in rows if r[k] is not None]))
            for k in ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error')}


def evaluate(output):
    frozen = read(output / 'frozen_plan.json')
    for path, expected in frozen['code_sha256'].items():
        if sha256_file(Path(path)) != expected:
            raise ValueError(f'changed frozen code {path}')
    if sha256_file(DATABASE) != frozen['structure_sha256']:
        raise ValueError('changed structure')
    repository = StructureRepository(DATABASE)
    summaries = {}
    for writer, dataset in frozen['datasets'].items():
        for name in ('index', 'sources', 'train_profile'):
            if sha256_file(Path(dataset[name])) != dataset[name + '_sha256']:
                raise ValueError(f'changed {writer} {name}')
        sources = load_profile(Path(dataset['sources'])).source_trajectories
        generator = DeterministicGenerator(load_profile(Path(dataset['train_profile'])),
                                            repository.metadata()['source_version'], 'adaptive', 1.)
        records = []
        for task in dataset['tasks']:
            graph = repository.get(task['character'])
            start = time.perf_counter()
            base = generator.generate(graph)
            base_seconds = time.perf_counter() - start
            base_curves = points(base)
            indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in task['target_stroke_ids']]
            for candidate in task['ranked_candidates']:
                assert split(candidate['character']) == 'train'
                assert candidate['character'] != task['character']
            start = time.perf_counter()
            contextual, provenance = choose_component(base, graph, task['target_stroke_ids'],
                task['ranked_candidates'], sources, field_strength=frozen['field_strength'],
                max_candidates=frozen['max_candidates'])
            contextual_seconds = time.perf_counter() - start
            donor = sources[task['candidate']['sample_id']]
            mapping = {s.standard_stroke_id: s for s in donor.strokes}
            selected = [mapping[k] for k in task['candidate']['stroke_ids']]
            transform = shared_transform([s.points for s in selected], bbox([p for i in indices for p in base_curves[i]]))
            decoded, _, _ = decode_component(selected, transform, 'B')
            raw_box = assemble(base, dict(zip(indices, decoded, strict=True)), 'B')
            variants = {'A': base, 'B': raw_box, 'D': contextual}
            # Target capture becomes accessible to the scorer only after all outputs are fixed.
            target = sources[task['target_sample_id']]
            target_map = {s.standard_stroke_id: s for s in target.strokes}
            reference = [target_map[s.stroke_id].points for s in graph.strokes]
            metrics = {label: score(glyph, reference, indices) for label, glyph in variants.items()}
            base_crossings = crossing_pairs(base_curves)
            checks = {label: {'invariants': invariants(glyph, graph),
                      'new_crossing_pairs_vs_A': sorted(crossing_pairs(points(glyph)) - base_crossings)}
                      for label, glyph in variants.items()}
            assert all(not c['invariants'] for c in checks.values())
            assert not checks['D']['new_crossing_pairs_vs_A']
            record = {'task': task, 'reference': reference, 'indices': indices,
                'reference_source_sha256': target.source_sha256,
                'metrics': metrics, 'checks': checks, 'provenance': provenance,
                'variants': {k: asdict(v) for k, v in variants.items()},
                'timing_seconds': {'A': base_seconds, 'D_additional': contextual_seconds}}
            save(output / 'cases' / f"{task['id']}.json", record)
            records.append(record)
        summary = {}
        for label in ('A', 'B', 'D'):
            summary[label] = {k: float(np.mean([r['metrics'][label][k] for r in records]))
                              for k in records[0]['metrics'][label]} if records else {}
            summary[label]['better_than_A'] = sum(r['metrics'][label]['mean_distance'] < r['metrics']['A']['mean_distance'] - 1e-9 for r in records)
            summary[label]['worse_than_A'] = sum(r['metrics'][label]['mean_distance'] > r['metrics']['A']['mean_distance'] + 1e-9 for r in records)
        summary['n'] = len(records)
        summary['fallbacks'] = sum(bool(r['provenance']['fallback_reason']) for r in records)
        summary['median_seconds'] = {key: float(np.median([r['timing_seconds'][key] for r in records])) for key in ('A', 'D_additional')} if records else {}
        summaries[writer] = summary
        print(writer, json.dumps(summary, ensure_ascii=False), flush=True)
    save(output / 'summary.json', summaries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'evaluate'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.phase == 'prepare' else evaluate)(args.output)


if __name__ == '__main__':
    main()
