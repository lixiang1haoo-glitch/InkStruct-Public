"""Generate before reading targets; choose on dev and optionally confirm once."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from develop_terminal_selection import METRICS, score
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.alignment import align_sample
from inkstruct.author_terminal_context import prepare_author_terminal
from inkstruct.author_terminal_hierarchy import HierarchicalAuthorTerminalEvidence
from inkstruct.exemplar_index import ExemplarIndex
from inkstruct.generate import DeterministicGenerator
from inkstruct.profile import load_profile
from inkstruct.samples import iter_index, sha256_file
from inkstruct.source_trajectory import source_trajectory
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--split', choices=['dev', 'test'], required=True)
    parser.add_argument('--development', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = read(args.batch / 'plan.json')
    protocol_path = Path('configs/experiments/author_terminal_hierarchy_v1.json')
    protocol = read(protocol_path)
    for path, expected in [(protocol['index'], protocol['index_sha256']),
        (plan['profile'], plan['profile_sha256']), (plan['train_index'], plan['train_index_sha256']),
        (DATABASE, plan['structure_sha256'])]:
        assert sha256_file(Path(path)) == expected, path
    choice = None
    if args.split == 'test':
        if args.development is None:
            raise ValueError('confirmation requires frozen development')
        choice = read(args.development / 'frozen_choice.json')
        if choice['chosen'] == 'D':
            raise ValueError('negative development; preserve unused test group')
        assert sha256_file(args.development / 'summary.json') == choice['summary_sha256']
        assert sha256_file(args.development / 'run_protocol.json') == choice['run_protocol_sha256']
        frozen = read(args.development / 'run_protocol.json')
        for path, expected in frozen['code_sha256'].items():
            assert sha256_file(Path(path)) == expected, path
        assert sha256_file(args.batch / 'plan.json') == frozen['plan_sha256']
    args.output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), Path('src/inkstruct/author_terminal_context.py'),
            Path('src/inkstruct/contextual_trajectory.py'), Path('src/inkstruct/trajectory_experiment.py'),
            Path('src/inkstruct/author_terminal_hierarchy.py'), protocol_path, Path('src/inkstruct/generate.py'), Path('src/inkstruct/alignment.py'), Path('src/inkstruct/source_trajectory.py')]
    save(args.output / 'run_protocol.json', {'plan_sha256': sha256_file(args.batch / 'plan.json'),
        'code_sha256': {str(p): sha256_file(p) for p in code}, 'split': args.split,
        'development_choice': choice, 'protocol': protocol, 'scope': 'archival data batch, physical author unconfirmed'})
    repository = StructureRepository(DATABASE)
    profile = load_profile(Path(plan['profile']))
    generator = DeterministicGenerator(profile, repository.metadata()['source_version'], 'adaptive', 1.)
    index = ExemplarIndex(profile, repository)
    evidence = HierarchicalAuthorTerminalEvidence(index)
    variants = [(f'{mode}_{weight}', weight, mode) for mode in protocol['reference_modes']
                for weight in protocol['weights'] if weight > 0]
    if choice:
        variants = [(choice['chosen'], choice['weight'], choice['mode'])]
    generated = []
    for task in plan['tasks']:
        if task['split'] != args.split:
            continue
        graph = repository.get(task['character'])
        component = next(c for c in graph.components if c.component_id == task['component_id'])
        for candidate in task['ranked_candidates']:
            assert plan['split'][candidate['character']] == 'train'
        base = generator.generate(graph)
        prepared = prepare_author_terminal(base, graph, component, task['ranked_candidates'], evidence)
        outputs = {'A': base, 'D': prepared.original}
        metadata = {'D': prepared.original_meta}
        for label, weight, mode in variants:
            outputs[label], metadata[label] = prepared.select(weight, mode)
        checks = {k: {'invariants': invariants(v, graph),
                  'new_crossings_vs_A': sorted(crossing_pairs(curves(v))-crossing_pairs(curves(base)))}
                  for k, v in outputs.items()}
        assert all(not v['invariants'] and not v['new_crossings_vs_A'] for v in checks.values())
        saved = {'task': task, 'outputs': {k: asdict(v) for k, v in outputs.items()},
                 'metadata': metadata, 'checks': checks}
        save(args.output / 'generated' / f"{task['id']}.json", saved)
        generated.append((task, graph, outputs, metadata, checks))
        print('generated', len(generated), flush=True)
    # This boundary follows ALL output selection and persistence for the split.
    targets = defaultdict(list)
    selected_characters = {task['character'] for task, *_ in generated}
    for sample in iter_index(Path(protocol['index'])):
        if sample.character in selected_characters:
            targets[sample.character].append(sample)
    rows, rejected = [], []
    for task, graph, outputs, metadata, checks in generated:
        references, sample_metrics, whole_metrics = [], [], []
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in task['target_stroke_ids']]
        for sample in targets[task['character']]:
            try:
                aligned = align_sample(sample, graph)
                actual, reason = source_trajectory(sample, aligned, graph)
            except (KeyError, ValueError) as error:
                actual, reason = None, str(error)
            if actual is None:
                rejected.append({'character': sample.character, 'sample_id': sample.sample_id, 'reason': reason})
                continue
            mapping = {s.standard_stroke_id: s.points for s in actual.strokes}
            reference = [mapping[s.stroke_id] for s in graph.strokes]
            references.append({'sample_id': sample.sample_id, 'source_sha256': sample.source_sha256,
                               'curves': reference})
            sample_metrics.append({k: score(v, reference, indices) for k, v in outputs.items()})
            whole_metrics.append({k: score(v, reference, range(len(graph.strokes))) for k, v in outputs.items()})
        if not references:
            rejected.append({'character': task['character'], 'reason': 'no valid evaluation capture'})
            continue
        def mean_metrics(values, labels):
            return {label: {metric: float(np.mean([m[label][metric] for m in values])) for metric in METRICS}
                    for label in labels}
        row = {'task': task, 'references': references, 'capture_metrics': sample_metrics,
               'metrics': mean_metrics(sample_metrics, outputs), 'whole_metrics': mean_metrics(whole_metrics, outputs),
               'outputs': {k: asdict(v) for k, v in outputs.items()}, 'metadata': metadata, 'checks': checks}
        save(args.output / 'cases' / f"{task['id']}.json", row)
        rows.append(row)
    summary = {label: {metric: float(np.mean([r['metrics'][label][metric] for r in rows])) for metric in METRICS}
               for label in rows[0]['outputs']}
    for label in rows[0]['metadata']:
        summary[label].update(
            activated=sum(r['metadata'][label]['selected'] is not None for r in rows),
            evidence_available=sum(r['metadata'][label].get('context_fallback_reason') is None for r in rows) if label != 'D' else None,
            different_donor_from_D=sum((r['metadata'][label]['selected'] or {}).get('candidate') !=
                (r['metadata']['D']['selected'] or {}).get('candidate') for r in rows))
    save(args.output / 'summary.json', summary)
    save(args.output / 'coverage.json', {'planned_characters': len(generated), 'scored_characters': len(rows),
         'scored_captures': sum(len(r['references']) for r in rows), 'rejected': rejected})
    save(args.output / 'whole_summary.json', {label: {metric: float(np.mean([r['whole_metrics'][label][metric] for r in rows]))
                                                for metric in METRICS} for label in summary})
    if args.split == 'dev':
        eligible = [(label, weight, mode) for label, weight, mode in variants if
            summary[label]['mean_distance'] <= summary['D']['mean_distance']*1.01 and
            summary[label]['activated'] == summary['D']['activated'] and
            summary[label]['terminal_angle_deg'] < summary['D']['terminal_angle_deg']-1e-12]
        chosen = min(eligible, key=lambda t: (summary[t[0]]['terminal_angle_deg'], t[1], t[2])) if eligible else ('D', 0., 'author')
        save(args.output / 'frozen_choice.json', {'chosen': chosen[0], 'weight': chosen[1], 'mode': chosen[2],
             'summary_sha256': sha256_file(args.output / 'summary.json'),
             'run_protocol_sha256': sha256_file(args.output / 'run_protocol.json')})
        print('chosen', chosen, flush=True)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
