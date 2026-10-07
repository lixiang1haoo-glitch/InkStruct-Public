"""Freeze a bounded whole-component aspect option using development captures only."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from develop_terminal_selection import METRICS, score
from run_raw_trajectory_experiment import Experiment, curves, save

from inkstruct.component_aspect import prepare_aspect_candidates
from inkstruct.samples import sha256_file
from inkstruct.trajectory_experiment import crossing_pairs, invariants


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol_path = Path('configs/experiments/component_aspect_v1.json')
    protocol = json.loads(protocol_path.read_text())
    experiment = Experiment(Path('artifacts/raw_trajectory_20261007'))
    protocol['input_hashes'] = {str(p): sha256_file(p) for p in [protocol_path,
        Path('artifacts/raw_trajectory_20261007/plan.json'), Path(__file__),
        Path('src/inkstruct/component_aspect.py'), Path('src/inkstruct/contextual_trajectory.py'),
        Path('src/inkstruct/trajectory_experiment.py'), Path('src/inkstruct/generate.py')]}
    save(args.output / 'protocol.json', protocol)
    cases = []
    for task in experiment.plan['tasks']:
        if task['task'] != 'cross' or task['split'] != 'dev':
            continue
        graph = experiment.repository.get(task['character'])
        base = experiment.training.generate(graph)
        outputs, provenance = {'A': base}, {}
        for cap in protocol['caps']:
            prepared = prepare_aspect_candidates(base, graph, task['target_stroke_ids'],
                task['ranked_candidates'], experiment.sources, cap=cap)
            if cap == 1:
                outputs['D'] = prepared.original
                provenance['D'] = {'selected': prepared.original_record}
            for arm, fixed in [('E', True), ('F', False)]:
                label = f'{arm}_{cap}'
                outputs[label], provenance[label] = prepared.select(fixed_donor=fixed)
        # All candidate choices and placements are fixed before reading the reference.
        sample = experiment.sources[task['target_sample_id']]
        mapping = {s.standard_stroke_id: s.points for s in sample.strokes}
        actual = [mapping[s.stroke_id] for s in graph.strokes]
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in task['target_stroke_ids']]
        metrics = {label: score(glyph, actual, indices) for label, glyph in outputs.items()}
        for glyph in outputs.values():
            assert not invariants(glyph, graph)
            assert not crossing_pairs(curves(glyph)) - crossing_pairs(curves(base))
        record = {'task': task, 'metrics': metrics, 'provenance': provenance,
                  'outputs': {k: asdict(v) for k, v in outputs.items()}, 'reference': actual}
        save(args.output / 'cases' / f"{task['id']}.json", record)
        cases.append(record)
        print('development', len(cases), flush=True)
    summary = {label: {key: float(np.mean([r['metrics'][label][key] for r in cases])) for key in METRICS}
               for label in cases[0]['metrics']}
    for label in cases[0]['provenance']:
        selections = [r['provenance'][label]['selected'] for r in cases]
        summary[label].update(activated=sum(s is not None for s in selections),
            bounded_xy=sum(s is not None and abs(s['transform']['sx']/s['transform']['sy']-1) > 1e-8
                           for s in selections),
            different_donor_from_D=sum((s or {}).get('candidate') !=
                (r['provenance']['D']['selected'] or {}).get('candidate')
                for s, r in zip(selections, cases, strict=True)))
    eligible = [cap for cap in protocol['caps'] if
        summary[f'F_{cap}']['terminal_angle_deg'] <= summary['D']['terminal_angle_deg'] and
        summary[f'F_{cap}']['activated'] >= summary['D']['activated'] and
        summary[f'F_{cap}']['mean_distance'] < summary['D']['mean_distance']-1e-12]
    cap = min(eligible, key=lambda c: (summary[f'F_{c}']['mean_distance'], c)) if eligible else 1.
    save(args.output / 'summary.json', summary)
    save(args.output / 'frozen_choice.json', {'cap': cap, 'cases': len(cases),
        'scope': 'development only', 'summary_sha256': sha256_file(args.output / 'summary.json'),
        'protocol_sha256': sha256_file(args.output / 'protocol.json')})
    print(json.dumps({'chosen_cap': cap, 'summary': summary}, indent=2), flush=True)


if __name__ == '__main__':
    main()
