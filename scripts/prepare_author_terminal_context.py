"""Split the unobserved archival batch before building a training-only profile."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from confirm_contextual_trajectory import split
from run_raw_trajectory_experiment import DATABASE, rank, save

from inkstruct.exemplar_index import ExemplarIndex, component_key, ordered_ids
from inkstruct.profile import build_profile
from inkstruct.samples import iter_index, sha256_file
from inkstruct.structures import StructureRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol_path = Path('configs/experiments/author_terminal_context_v1.json')
    protocol = json.loads(protocol_path.read_text())
    source = Path(protocol['index'])
    assert sha256_file(source) == protocol['index_sha256']
    samples = list(iter_index(source))
    characters = sorted({s.character for s in samples})
    assignment = {c: split(c) for c in characters}
    # No target alignment or target profile building occurs in preparation.
    train = args.output / 'train_index.jsonl'
    with train.open('x') as stream:
        for sample in samples:
            if assignment[sample.character] == 'train':
                stream.write(json.dumps(asdict(sample), ensure_ascii=False)+'\n')
    repository = StructureRepository(DATABASE)
    profile, path = build_profile('user_001', train, repository, args.output / 'profiles',
                                  retain_source_trajectories=True)
    assert all(assignment[s.character] == 'train' for s in profile.source_trajectories.values())
    index = ExemplarIndex(profile, repository)
    tasks, exclusions = [], []
    for character in sorted(characters, key=rank):
        if assignment[character] == 'train':
            continue
        try:
            graph = repository.get(character)
        except KeyError:
            exclusions.append({'character': character, 'reason': 'no public structure'})
            continue
        slots = [(c, index.candidates(graph, c)) for c in graph.components
                 if c.path != 'root' and not c.children_ids and len(c.stroke_ids) >= 2 and c.confidence >= .8]
        slots = [(c, candidates) for c, candidates in slots if candidates]
        if not slots:
            exclusions.append({'character': character, 'reason': 'no compatible public component donor'})
            continue
        component, candidates = max(slots, key=lambda pair: (len(pair[1]), pair[0].path))
        tasks.append({'id': f'user001-{assignment[character]}-U+{ord(character):04X}',
            'character': character, 'split': assignment[character], 'context': component_key(graph, component),
            'component_id': component.component_id, 'target_stroke_ids': ordered_ids(graph, component),
            'ranked_candidates': candidates})
    plan = {'protocol': protocol, 'protocol_sha256': sha256_file(protocol_path),
        'profile': str(path), 'profile_sha256': sha256_file(path),
        'train_index': str(train), 'train_index_sha256': sha256_file(train),
        'structure_sha256': sha256_file(DATABASE), 'split': assignment, 'tasks': tasks,
        'exclusions': exclusions, 'character_counts': dict(Counter(assignment.values())),
        'record_counts': dict(Counter(assignment[s.character] for s in samples)),
        'training_profile_count': profile.sample_count,
        'retained_train_sources': len(profile.source_trajectories),
        'task_counts': dict(Counter(t['split'] for t in tasks)),
        'preparation_sha256': sha256_file(Path(__file__))}
    save(args.output / 'plan.json', plan)
    print(json.dumps({k: plan[k] for k in ['character_counts', 'record_counts', 'training_profile_count',
                                         'retained_train_sources', 'task_counts']}, indent=2))


if __name__ == '__main__':
    main()
