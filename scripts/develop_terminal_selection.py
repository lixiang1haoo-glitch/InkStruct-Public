"""Predeclared terminal-direction ablation on the existing scx development group."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_raw_trajectory_experiment import Experiment, curves, save

from inkstruct.samples import sha256_file
from inkstruct.terminal_selection import prepare_terminal_candidates
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics

METRICS = ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error', 'endpoint_error')


def score(glyph, reference, indices):
    rows = [stroke_metrics(curves(glyph)[i], reference[i]) for i in indices]
    return {key: float(np.mean([row[key] for row in rows if row[key] is not None])) for key in METRICS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=Path('artifacts/raw_trajectory_20261007'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol_path = Path('configs/experiments/terminal_selection_v1.json')
    protocol = json.loads(protocol_path.read_text())
    experiment = Experiment(args.baseline)
    protocol['protocol_sha256'] = sha256_file(protocol_path)
    protocol['code_sha256'] = {str(p): sha256_file(p) for p in [
        Path('src/inkstruct/terminal_selection.py'), Path('src/inkstruct/contextual_trajectory.py'),
        Path('src/inkstruct/trajectory_experiment.py'), Path(__file__)]}
    protocol['baseline_plan_sha256'] = sha256_file(args.baseline / 'plan.json')
    save(args.output / 'protocol.json', protocol)
    variants = [('D', 0., 'baseline')] + [(f'{r}_{w}', w, r) for r in protocol['terminal_references']
                for w in protocol['weights'] if w > 0]
    cases = []
    for task in experiment.plan['tasks']:
        if task['task'] != 'cross' or task['split'] != 'dev':
            continue
        graph = experiment.repository.get(task['character'])
        base = experiment.training.generate(graph)
        prepared = prepare_terminal_candidates(base, graph, task['target_stroke_ids'],
            task['ranked_candidates'], experiment.sources)
        outputs = {'A': base}
        provenance = {}
        for label, weight, reference in variants:
            outputs[label], provenance[label] = prepared.select(weight, reference)
        # Only score target handwriting once every selection is finalized.
        sample = experiment.sources[task['target_sample_id']]
        mapping = {s.standard_stroke_id: s.points for s in sample.strokes}
        actual = [mapping[s.stroke_id] for s in graph.strokes]
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in task['target_stroke_ids']]
        metrics = {label: score(glyph, actual, indices) for label, glyph in outputs.items()}
        for glyph in outputs.values():
            assert not invariants(glyph, graph)
            assert not crossing_pairs(curves(glyph)) - crossing_pairs(curves(base))
        record = {'task': task, 'metrics': metrics,
                  'selected': {k: v['selected'] for k, v in provenance.items()},
                  'fallbacks': {k: v['fallback_reason'] for k, v in provenance.items()},
                  'candidate_diagnostics': prepared.diagnostics,
                  'outputs': {k: asdict(v) for k, v in outputs.items()}, 'reference': actual}
        save(args.output / 'cases' / f"{task['id']}.json", record)
        cases.append(record)
        print('development', len(cases), flush=True)
    summary = {label: {key: float(np.mean([r['metrics'][label][key] for r in cases])) for key in METRICS}
               for label in cases[0]['metrics']}
    for label, weight, reference in variants:
        summary[label].update({'weight': weight, 'reference': reference,
            'activated': sum(r['selected'][label] is not None for r in cases),
            'different_donor_from_D': sum((r['selected'][label] or {}).get('candidate') !=
                (r['selected']['D'] or {}).get('candidate') for r in cases)})
    candidates = [label for label, _, _ in variants
        if summary[label]['activated'] == summary['D']['activated']
        and summary[label]['mean_distance'] <= summary['D']['mean_distance'] * 1.01]
    chosen = min(candidates, key=lambda k: (summary[k]['terminal_angle_deg'], summary[k]['mean_distance'],
                                           summary[k]['weight'], summary[k]['reference']))
    if summary[chosen]['terminal_angle_deg'] >= summary['D']['terminal_angle_deg']:
        chosen = 'D'
    save(args.output / 'summary.json', summary)
    save(args.output / 'frozen_choice.json', {'chosen': chosen, 'parameters': summary[chosen],
        'cases': len(cases), 'scope': 'development only',
        'summary_sha256': sha256_file(args.output / 'summary.json'),
        'protocol_sha256': sha256_file(args.output / 'protocol.json')})
    print(json.dumps({'chosen': chosen, 'summary': summary}, indent=2), flush=True)


if __name__ == '__main__':
    main()
