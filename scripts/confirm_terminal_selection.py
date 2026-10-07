"""Freeze terminal selection before an untouched-author confirmation; no retuning."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from confirm_contextual_trajectory import split
from develop_terminal_selection import METRICS, score
from run_raw_trajectory_experiment import (
    key,
    leaf_components,
    ordered_ids,
    rank,
    save,
    select_candidate,
)

from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import bbox
from inkstruct.profile import build_profile, load_profile
from inkstruct.samples import iter_index, sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.terminal_selection import prepare_terminal_candidates
from inkstruct.topology_repair import glyph_curves
from inkstruct.trajectory_experiment import crossing_pairs, invariants

CODE = ['src/inkstruct/terminal_selection.py', 'src/inkstruct/contextual_trajectory.py',
        'src/inkstruct/trajectory_experiment.py', 'src/inkstruct/generate.py',
        'scripts/confirm_terminal_selection.py', 'scripts/develop_terminal_selection.py',
        'scripts/run_raw_trajectory_experiment.py']


def read(path):
    return json.loads(path.read_text())


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    choice = read(args.development / 'frozen_choice.json')
    assert choice['summary_sha256'] == sha256_file(args.development / 'summary.json')
    protocol = read(args.development / 'protocol.json')
    assert choice['protocol_sha256'] == sha256_file(args.development / 'protocol.json')
    for path, expected in protocol['code_sha256'].items():
        assert sha256_file(Path(path)) == expected, path
    database = Path('artifacts/structures/characters.sqlite3')
    repository = StructureRepository(database)
    index = Path('artifacts/samples/wsq/index.jsonl')
    sources_path = Path('profiles/terminal_20261007/source/wsq/profile.json')
    source = load_profile(sources_path).source_trajectories
    by_character = defaultdict(list)
    for sample in source.values():
        by_character[sample.character].append(sample)
    samples = {c: min(group, key=lambda s: rank(s.sample_id)) for c, group in by_character.items()}
    graphs = {c: repository.get(c) for c in samples}
    train_index = args.output / 'wsq_train_index.jsonl'
    with train_index.open('x') as stream:
        for sample in iter_index(index):
            if split(sample.character) == 'train':
                stream.write(json.dumps(asdict(sample), ensure_ascii=False) + '\n')
    profile, profile_path = build_profile('wsq', train_index, repository, args.output / 'profiles_train')
    pool = defaultdict(list)
    for character, sample in samples.items():
        if split(character) != 'train':
            continue
        mapping = {s.standard_stroke_id: s for s in sample.strokes}
        for component in leaf_components(graphs[character]):
            ids = ordered_ids(graphs[character], component)
            confidence = float(np.mean([mapping[k].confidence for k in ids]))
            box = bbox([p for k in ids for p in mapping[k].points])
            if confidence < .55 or min(box[2]-box[0], box[3]-box[1]) < 1e-5:
                continue
            pool[key(graphs[character], component)].append({'character': character,
                'sample_id': sample.sample_id, 'source_sha256': sample.source_sha256,
                'component_id': component.component_id, 'stroke_ids': ids, 'confidence': confidence})
    targets = sorted((c for c in samples if split(c) == 'test'), key=rank)
    groups, rejected = defaultdict(list), []
    for character in targets:
        options = []
        for component in leaf_components(graphs[character]):
            candidates = select_candidate(graphs[character], component, pool, graphs)
            if candidates:
                options.append((component, candidates))
        if not options:
            rejected.append(character)
            continue
        component, candidates = max(options, key=lambda p: (len(p[1]), p[0].path))
        groups[key(graphs[character], component)].append({'id': f'wsq-terminal-U+{ord(character):04X}',
            'character': character, 'target_sample_id': samples[character].sample_id,
            'target_stroke_ids': ordered_ids(graphs[character], component),
            'context': key(graphs[character], component), 'ranked_candidates': candidates})
    tasks = []
    ordered_groups = [groups[k] for k in sorted(groups)]
    while any(ordered_groups) and len(tasks) < protocol['confirmation_cap']:
        for group in ordered_groups:
            if group and len(tasks) < protocol['confirmation_cap']:
                tasks.append(group.pop(0))
    plan = {'writer': 'wsq', 'choice': choice, 'available_test_targets': len(targets),
        'no_compatible_donor': rejected, 'eligible_targets': len(targets)-len(rejected),
        'train_profile_count': profile.sample_count, 'tasks': tasks,
        'index': str(index), 'sources': str(sources_path), 'profile': str(profile_path),
        'database': str(database), 'input_sha256': {str(p): sha256_file(p) for p in [index,
            sources_path, profile_path, database, train_index, args.development / 'frozen_choice.json']},
        'code_sha256': {p: sha256_file(Path(p)) for p in CODE},
        'scope': 'new author confirmation; character-grouped; all parameters frozen from scx development'}
    save(args.output / 'frozen_plan.json', plan)
    print(json.dumps({k: v for k, v in plan.items() if k in ('writer', 'available_test_targets',
        'eligible_targets', 'train_profile_count')}) + f' selected={len(tasks)}', flush=True)


def evaluate(args):
    plan = read(args.output / 'frozen_plan.json')
    for section in ('input_sha256', 'code_sha256'):
        for path, expected in plan[section].items():
            assert sha256_file(Path(path)) == expected, path
    repository = StructureRepository(Path(plan['database']))
    generator = DeterministicGenerator(load_profile(Path(plan['profile'])), repository.metadata()['source_version'], 'adaptive', 1.)
    sources = load_profile(Path(plan['sources'])).source_trajectories
    parameters = plan['choice']['parameters']
    cases = []
    for task in plan['tasks']:
        assert split(task['character']) == 'test'
        assert all(split(c['character']) == 'train' and c['character'] != task['character'] for c in task['ranked_candidates'])
        graph = repository.get(task['character'])
        base = generator.generate(graph)
        prepared = prepare_terminal_candidates(base, graph, task['target_stroke_ids'], task['ranked_candidates'], sources)
        original, old_provenance = prepared.select()
        selected, provenance = prepared.select(parameters['weight'], parameters['reference'])
        outputs = {'A': base, 'D': original, 'E': selected}
        # No reference handwriting is supplied to the candidate preparation/selection boundary.
        target = sources[task['target_sample_id']]
        mapping = {s.standard_stroke_id: s.points for s in target.strokes}
        reference = [mapping[s.stroke_id] for s in graph.strokes]
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in task['target_stroke_ids']]
        metrics = {label: score(glyph, reference, indices) for label, glyph in outputs.items()}
        checks = {label: {'invariants': invariants(glyph, graph),
            'new_crossings_vs_A': sorted(crossing_pairs(glyph_curves(glyph)) - crossing_pairs(glyph_curves(base)))}
            for label, glyph in outputs.items()}
        assert all(not v['invariants'] and not v['new_crossings_vs_A'] for v in checks.values())
        record = {'task': task, 'metrics': metrics, 'reference': reference,
            'reference_sha256': target.source_sha256, 'provenance_D': old_provenance,
            'provenance_E': provenance, 'checks': checks, 'variants': {k: asdict(v) for k, v in outputs.items()}}
        save(args.output / 'cases' / f"{task['id']}.json", record)
        cases.append(record)
    summary = {label: {key: float(np.mean([r['metrics'][label][key] for r in cases])) for key in METRICS}
               for label in ('A', 'D', 'E')}
    for label in ('D', 'E'):
        summary[label].update({'activated': sum(r[f'provenance_{label}']['selected'] is not None for r in cases),
            'angle_better_than_A': sum(r['metrics'][label]['terminal_angle_deg'] < r['metrics']['A']['terminal_angle_deg'] - 1e-9 for r in cases),
            'geometry_better_than_A': sum(r['metrics'][label]['mean_distance'] < r['metrics']['A']['mean_distance'] - 1e-9 for r in cases)})
    summary['cases'] = len(cases)
    summary['different_donor_from_D'] = sum((r['provenance_D']['selected'] or {}).get('candidate') !=
        (r['provenance_E']['selected'] or {}).get('candidate') for r in cases)
    save(args.output / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'evaluate'))
    parser.add_argument('--development', type=Path, default=Path('artifacts/terminal_selection_20261007/development_v1'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.phase == 'prepare' else evaluate)(args)
