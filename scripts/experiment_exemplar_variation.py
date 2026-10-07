"""Freeze cross-character component evidence and validate reproducible whole-source draws."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from confirm_contextual_trajectory import split
from develop_terminal_selection import METRICS, score
from run_raw_trajectory_experiment import SOURCE_PROFILE, Experiment, curves, rank, save

from inkstruct.component_variation_evidence import ComponentVariationEvidence
from inkstruct.exemplar_index import ExemplarIndex, component_key, ordered_ids
from inkstruct.exemplar_variation import prepare_variation_pool, source_component
from inkstruct.generate import DeterministicGenerator
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants

ROOT = Path('artifacts/exemplar_variation_20261007')
PROTOCOL = Path('configs/experiments/exemplar_variation_v1.json')
PRIOR = Path('artifacts/terminal_selection_20261007/wsq_confirmation_v1/frozen_plan.json')
CODE = [Path(__file__), *[Path('src/inkstruct') / f'{name}.py' for name in (
    'component_variation_evidence', 'exemplar_variation', 'exemplar_generation', 'exemplar_index',
    'contextual_trajectory', 'terminal_selection', 'trajectory_experiment', 'generate')]]


def read(path):
    return json.loads(Path(path).read_text())


def verify(plan):
    for section in ('input_sha256', 'code_sha256'):
        for path, digest in plan[section].items():
            assert sha256_file(Path(path)) == digest, path


def prepare(phase, output, development):
    output.mkdir(parents=True, exist_ok=False)
    protocol = read(PROTOCOL)
    inputs = [PROTOCOL]
    if phase == 'development':
        experiment = Experiment(Path('artifacts/raw_trajectory_20261007'))
        tasks = [t for t in experiment.plan['tasks'] if t['task'] == 'cross' and t['split'] == 'dev']
        source_path, profile_path = SOURCE_PROFILE, Path(experiment.plan['train_profile'])
        database = Path('artifacts/structures/characters.sqlite3')
        choice = None
        inputs.append(Path('artifacts/raw_trajectory_20261007/plan.json'))
    else:
        dev_plan = read(development / 'frozen_plan.json')
        verify(dev_plan)
        choice = read(development / 'frozen_choice.json')
        assert choice['summary_sha256'] == sha256_file(development / 'summary.json')
        prior = read(PRIOR)
        for path, digest in prior['input_sha256'].items():
            assert sha256_file(Path(path)) == digest, path
        source_path, profile_path, database = map(Path, (prior['sources'], prior['profile'], prior['database']))
        source_profile = load_profile(source_path)
        repository = StructureRepository(database)
        allowed = {s.character for s in source_profile.source_trajectories.values() if split(s.character) == 'train'}
        index = ExemplarIndex(source_profile, repository, allowed_characters=allowed)
        excluded = {t['character'] for t in prior['tasks']}
        samples = {}
        for sample in sorted(source_profile.source_trajectories.values(), key=lambda s: rank(s.sample_id)):
            samples.setdefault(sample.character, sample)
        tasks = []
        for character in sorted(samples, key=rank):
            if split(character) != 'test' or character in excluded:
                continue
            graph = index.graph(character)
            options = [(c, index.candidates(graph, c)) for c in graph.components
                       if c.path != 'root' and not c.children_ids and len(c.stroke_ids) >= 2 and c.confidence >= .8]
            options = [(c, candidates) for c, candidates in options if candidates]
            if not options:
                continue
            component, candidates = max(options, key=lambda p: (len(p[1]), p[0].path))
            tasks.append({'id': f'wsq-variation-U+{ord(character):04X}', 'character': character,
                'target_sample_id': samples[character].sample_id, 'target_stroke_ids': ordered_ids(graph, component),
                'context': component_key(graph, component), 'ranked_candidates': candidates})
        inputs += [PRIOR, development / 'frozen_choice.json', development / 'summary.json']
    inputs += [source_path, profile_path, database]
    plan = {'phase': phase, 'protocol': protocol, 'choice': choice, 'tasks': tasks,
            'sources': str(source_path), 'profile': str(profile_path), 'database': str(database),
            'input_sha256': {str(p): sha256_file(p) for p in inputs},
            'code_sha256': {str(p): sha256_file(p) for p in CODE}}
    save(output / 'frozen_plan.json', plan)
    print(f'Frozen {phase}: {len(tasks)} characters', flush=True)


def evaluate(output):
    plan = read(output / 'frozen_plan.json')
    verify(plan)
    source_profile = load_profile(Path(plan['sources']))
    repository = StructureRepository(Path(plan['database']))
    generator = DeterministicGenerator(load_profile(Path(plan['profile'])), repository.metadata()['source_version'], 'adaptive', 1.)
    allowed = {s.character for s in source_profile.source_trajectories.values() if split(s.character) == 'train'}
    index = ExemplarIndex(source_profile, repository, allowed_characters=allowed)
    evidence = ComponentVariationEvidence(index)
    margins = plan['protocol']['margins'] if plan['phase'] == 'development' else [0., plan['choice']['margin']]
    margins = sorted(set(margins))
    rows = []
    for task in plan['tasks']:
        assert task['character'] not in allowed
        assert all(c['character'] in allowed for c in task['ranked_candidates'])
        graph = repository.get(task['character'])
        base = generator.generate(graph)
        ids = task['target_stroke_ids']
        pool = prepare_variation_pool(base, graph, ids, task['ranked_candidates'], index.sources)
        _, pool.evidence = evidence.cohort(task['context'], task['character'])
        for record in pool.distinct:
            _, placed = source_component(base, ids, record, index.sources)
            record['component_evidence'] = evidence.assess(task['context'], task['character'], placed,
                donor_character=record['candidate']['character'])
        outputs, provenance = {'A': base}, {}
        for label, seed, occurrence, margin in [('D', 0, 0, 0.)] + [
                (f'V{i+1}', seed, i, margins[-1]) for i, seed in enumerate(plan['protocol']['seeds'])]:
            outputs[label], provenance[label] = pool.select(base, ids, index.sources, seed=seed,
                occurrence_id=occurrence, component_id=task['context'], margin=margin)
        alternatives = [(record, source_component(base, ids, record, index.sources)[0]) for record in pool.distinct]
        checks = {label: {'invariants': invariants(glyph, graph), 'new_crossings_vs_A': sorted(
            crossing_pairs(curves(glyph)) - crossing_pairs(curves(base)))} for label, glyph in outputs.items()}
        assert all(not r['invariants'] and not r['new_crossings_vs_A'] for r in checks.values())
        # The target capture is read only after references, candidates and outputs are fixed.
        target = index.sources[task['target_sample_id']]
        mapping = {s.standard_stroke_id: s.points for s in target.strokes}
        actual = [mapping[s.stroke_id] for s in graph.strokes]
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
        metrics = {label: score(glyph, actual, indices) for label, glyph in outputs.items()}
        alternative_metrics = {r['geometry_id']: score(g, actual, indices) for r, g in alternatives}
        expected = {}
        for margin in margins:
            candidates, probabilities = pool.eligible(margin)
            expected[str(margin)] = {k: sum(p * alternative_metrics[c['geometry_id']][k]
                for c, p in zip(candidates, probabilities, strict=True)) if candidates else metrics['A'][k]
                for k in METRICS}
            expected[str(margin)]['eligible'] = len(candidates)
        reference_evidence = evidence.assess(task['context'], task['character'], [actual[i] for i in indices])
        row = {'task': task, 'metrics': metrics, 'expected': expected, 'reference': actual,
               'reference_sha256': target.source_sha256, 'reference_evidence': reference_evidence,
               'cohort': pool.evidence, 'pool': pool.distinct, 'checks': checks,
               'variants': {k: asdict(g) for k, g in outputs.items()}, 'provenance': provenance}
        save(output / 'cases' / f"{task['id']}.json", row)
        rows.append(row)
        print(plan['phase'], len(rows), task['character'], flush=True)
    summary = {'cases': len(rows), 'metrics': {label: {k: float(np.mean([r['metrics'][label][k] for r in rows]))
        for k in METRICS} for label in rows[0]['metrics']}, 'expected': {},
        'evidence_available': sum(r['reference_evidence']['available'] for r in rows),
        'heldout_component_in_range': sum(bool(r['reference_evidence'].get('within_empirical_range')) for r in rows),
        'observed_multiple_shapes': sum(len({r['provenance'][f'V{i+1}']['variation'].get('selected_geometry_id')
             for i in range(5)}) > 1 for r in rows)}
    for margin in margins:
        summary['expected'][str(margin)] = {k: float(np.mean([r['expected'][str(margin)][k] for r in rows])) for k in METRICS}
        summary['expected'][str(margin)]['multiple_eligible'] = sum(r['expected'][str(margin)]['eligible'] > 1 for r in rows)
    summary['metrics']['V_mean'] = {k: float(np.mean([r['metrics'][f'V{i+1}'][k] for r in rows for i in range(5)])) for k in METRICS}
    save(output / 'summary.json', summary)
    if plan['phase'] == 'development':
        baseline = summary['expected']['0.0']
        passing = [m for m in margins if summary['expected'][str(m)]['mean_distance'] <= baseline['mean_distance']*1.01
            and summary['expected'][str(m)]['terminal_angle_deg'] <= baseline['terminal_angle_deg']+.5]
        save(output / 'frozen_choice.json', {'margin': max(passing), 'summary_sha256': sha256_file(output / 'summary.json'),
                                           'plan_sha256': sha256_file(output / 'frozen_plan.json')})
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare-development', 'prepare-confirmation', 'evaluate'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--development', type=Path, default=ROOT / 'development_v1')
    args = parser.parse_args()
    if args.action == 'evaluate':
        evaluate(args.output)
    else:
        prepare(args.action.removeprefix('prepare-'), args.output, args.development)
