"""Freeze training-derived layout on development; evaluate observed regression."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from develop_terminal_selection import METRICS
from experiment_component_trust import glyph_from_dict, mean_present, read
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.exemplar_index import ExemplarIndex
from inkstruct.learned_component_layout import (
    ComponentLayoutEvidence,
    layout_summary,
    place_with_learned_layout,
    public_layout,
)
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--stage', choices=['development', 'regression'], required=True)
    parser.add_argument('--development', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config_path = Path('configs/experiments/learned_component_layout_v1.json')
    config, batch = read(config_path), read(args.batch / 'plan.json')
    assert sha256_file(Path(batch['profile'])) == batch['profile_sha256']
    assert sha256_file(DATABASE) == batch['structure_sha256']
    assert read(args.input / 'run_protocol.json')['split'] == ('dev' if args.stage == 'development' else 'test')
    code = [Path(__file__), config_path, Path('src/inkstruct/learned_component_layout.py'),
            Path('src/inkstruct/exemplar_index.py'), Path('src/inkstruct/trajectory_experiment.py'),
            Path('src/inkstruct/exemplar_variation.py'), Path('src/inkstruct/alignment.py')]
    choice = None
    if args.stage == 'regression':
        if args.development is None:
            raise ValueError('frozen development required')
        choice = read(args.development / 'frozen_choice.json')
        assert sha256_file(args.development / 'summary.json') == choice['summary_sha256']
        assert sha256_file(args.development / 'run_protocol.json') == choice['run_protocol_sha256']
        for path, expected in read(args.development / 'run_protocol.json')['code_sha256'].items():
            assert sha256_file(Path(path)) == expected, path
    strengths = config['strengths'] if choice is None else [choice['strength']]
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = [args.batch / 'plan.json', Path(batch['profile']), args.input / 'run_protocol.json']
    inputs += sorted((args.input / 'generated').glob('*.json'))+sorted((args.input / 'cases').glob('*.json'))
    save(args.output / 'run_protocol.json', {'config': config, 'stage': args.stage,
        'scope': 'development' if choice is None else 'previously observed regression, not fresh validation',
        'choice': choice, 'input_sha256': {str(p): sha256_file(p) for p in inputs},
        'code_sha256': {str(p): sha256_file(p) for p in code}})
    repository = StructureRepository(DATABASE)
    profile = load_profile(Path(batch['profile']))
    assert all(batch['split'][s.character] == 'train' for s in profile.source_trajectories.values())
    index = ExemplarIndex(profile, repository)
    evidence = ComponentLayoutEvidence(index)
    generated = []
    for path in sorted((args.input / 'generated').glob('*.json')):
        prior = read(path)  # no target references in these frozen files
        task = prior['task']
        graph = repository.get(task['character'])
        component = next(c for c in graph.components if c.component_id == task['component_id'])
        outputs = {k: glyph_from_dict(prior['outputs'][v]) for k, v in [('A', 'A'), ('D', 'D'), ('H', 'author_0.04')]}
        metadata = {k: {'selected': prior['metadata'][v]['selected'], 'fallback_reason': prior['metadata'][v].get('fallback_reason'),
                       'frozen_selection_file': str(path), 'frozen_selection_label': v}
                    for k, v in [('D', 'D'), ('H', 'author_0.04')]}
        predicted = evidence.predict(graph, component)
        center, span, _ = public_layout(graph, component)
        public = {'available': True, 'policy': 'public_normalized_layout_control', 'center': center.tolist(), 'span': span}
        for strength in strengths:
            for prefix, prediction in [('L', predicted), ('P', public)]:
                for donor in ('D', 'H'):
                    label = f'{prefix}_{donor}_{strength}'
                    outputs[label], metadata[label] = place_with_learned_layout(outputs['A'], outputs[donor], metadata[donor],
                        graph, component, index.sources, prediction, strength)
        checks = {label: {'invariants': invariants(glyph, graph),
                  'new_crossings_vs_A': sorted(crossing_pairs(curves(glyph))-crossing_pairs(curves(outputs['A'])))}
                  for label, glyph in outputs.items()}
        assert all(not x['invariants'] and not x['new_crossings_vs_A'] for x in checks.values())
        payload = {'task': task, 'outputs': {k: asdict(v) for k, v in outputs.items()}, 'metadata': metadata,
                   'predictions': {'learned': predicted, 'public': public}, 'checks': checks}
        save(args.output / 'generated' / path.name, payload)
        generated.append((path.name, graph, outputs, payload))
    rows, excluded = [], []
    for filename, graph, outputs, payload in generated:
        ref_path = args.input / 'cases' / filename
        if not ref_path.exists():
            excluded.append(graph.character)
            continue
        references = read(ref_path)['references']
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in payload['task']['target_stroke_ids']]
        cache, metrics, whole, per_stroke = {}, {}, {}, {}
        for label, glyph in outputs.items():
            xy = curves(glyph)
            key = tuple(tuple(tuple(p) for p in stroke) for stroke in xy)
            if key not in cache:
                all_scores = [[stroke_metrics(stroke, ref['curves'][i]) for i, stroke in enumerate(xy)] for ref in references]
                cache[key] = [{metric: mean_present([r[i][metric] for r in all_scores]) for metric in METRICS} for i in range(len(xy))]
            average = cache[key]
            metrics[label] = {metric: mean_present([average[i][metric] for i in indices]) for metric in METRICS}
            whole[label] = {metric: mean_present([s[metric] for s in average]) for metric in METRICS}
            per_stroke[label] = {graph.strokes[i].stroke_id: average[i] for i in indices}
        prediction_scores = {}
        for name, prediction in payload['predictions'].items():
            if not prediction.get('available'):
                continue
            errors = []
            for ref in references:
                center, span, _ = layout_summary([ref['curves'][i] for i in indices])
                errors.append({'center_error': float(np.linalg.norm(np.asarray(prediction['center'])-center)),
                               'absolute_log_span_error': float(abs(np.log(prediction['span']/span)))})
            prediction_scores[name] = {key: mean_present([v[key] for v in errors]) for key in errors[0]}
        row = {**payload, 'references': references, 'metrics': metrics, 'whole_metrics': whole,
               'stroke_metrics': per_stroke, 'prediction_scores': prediction_scores}
        save(args.output / 'cases' / filename, row)
        rows.append(row)
        print('scored', len(rows), flush=True)
    summary = {label: {metric: mean_present([r['metrics'][label][metric] for r in rows]) for metric in METRICS}
               for label in rows[0]['outputs']}
    for label in rows[0]['metadata']:
        summary[label].update(activated=sum(r['metadata'][label]['selected'] is not None for r in rows),
            layout_applied=sum(r['metadata'][label].get('learned_layout', {}).get('applied', False) for r in rows),
            maximum_character_geometry_ratio=max(r['metrics'][label]['mean_distance']/max(r['metrics']['D']['mean_distance'], 1e-12) for r in rows),
            maximum_stroke_local_error_increase=max(s['max_distance']-r['stroke_metrics']['D'][sid]['max_distance']
                for r in rows for sid, s in r['stroke_metrics'][label].items()))
    save(args.output / 'summary.json', summary)
    save(args.output / 'whole_summary.json', {label: {metric: mean_present([r['whole_metrics'][label][metric] for r in rows]) for metric in METRICS}
                                            for label in summary})
    paired = [r for r in rows if 'learned' in r['prediction_scores']]
    save(args.output / 'prediction_summary.json', {'paired_characters': len(paired),
        'scores': {kind: {key: mean_present([r['prediction_scores'][kind][key] for r in paired])
                  for key in ['center_error', 'absolute_log_span_error']} for kind in ['public', 'learned']}})
    save(args.output / 'coverage.json', {'generated_characters': len(generated), 'scored_characters': len(rows),
        'scored_captures': sum(len(r['references']) for r in rows), 'missing_reference_characters': excluded,
        'prediction_available': sum(r['predictions']['learned'].get('available', False) for r in rows),
        'scope': 'development' if choice is None else 'observed regression only'})
    if choice is None:
        eligible = [label for label, values in summary.items() if label.startswith(('L_', 'P_')) and
            values['activated'] == summary['D']['activated'] and values['mean_distance'] < summary['D']['mean_distance']-1e-12 and
            values['terminal_angle_deg'] <= summary['D']['terminal_angle_deg']+.5 and
            values['maximum_character_geometry_ratio'] <= 1.05+1e-12 and values['maximum_stroke_local_error_increase'] <= .005+1e-12]
        order = {'P_D': 0, 'L_D': 1, 'P_H': 2, 'L_H': 3}
        label = min(eligible, key=lambda k: (summary[k]['mean_distance'], float(k.rsplit('_', 1)[1]), order[k.rsplit('_', 1)[0]])) if eligible else 'D'
        strength = float(label.rsplit('_', 1)[1]) if label != 'D' else 0.
        save(args.output / 'frozen_choice.json', {'label': label, 'strength': strength,
            'summary_sha256': sha256_file(args.output / 'summary.json'),
            'run_protocol_sha256': sha256_file(args.output / 'run_protocol.json')})
        print('frozen', label, strength, flush=True)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
