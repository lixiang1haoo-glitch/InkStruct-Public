"""Replay frozen complete candidates, tune trust radius on dev, then regress."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from develop_terminal_selection import METRICS
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.author_terminal_context import MODES, AuthorTerminalCandidates
from inkstruct.component_trust import prepare_component_trust
from inkstruct.component_trust_translation import translate_prepared_candidates
from inkstruct.exemplar_variation import source_component
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics


def read(path):
    return json.loads(path.read_text())


def glyph_from_dict(value):
    return GeneratedGlyph(**{**value, 'strokes': [GeneratedStroke(**{**s,
        'points': [GeneratedPoint(**p) for p in s['points']]}) for s in value['strokes']]})


def restore_candidates(row, sources):
    base = glyph_from_dict(row['outputs']['A'])
    original = glyph_from_dict(row['outputs']['D'])
    records = row['metadata']['author_0.04']['direction_diagnostics']
    alternatives = [(source_component(base, row['task']['target_stroke_ids'], r, sources)[0], r) for r in records]
    count = len(row['task']['target_stroke_ids'])
    common = {mode: [i for i in range(count) if alternatives and all(
        r['author_terminal_per_stroke'][mode][i] is not None for _, r in alternatives)] for mode in MODES}
    prepared = AuthorTerminalCandidates(original, row['metadata']['D'], alternatives, records, common)
    restored, _ = prepared.select(.04, 'author')
    assert asdict(restored) == row['outputs']['author_0.04'], 'frozen H replay changed'
    return base, prepared


def mean_present(values):
    finite = [v for v in values if v is not None]
    return float(np.mean(finite)) if finite else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--stage', choices=['development', 'regression'], required=True)
    parser.add_argument('--development', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config_path = Path('configs/experiments/component_trust_translation_v1.json')
    config = read(config_path)
    batch = read(args.batch / 'plan.json')
    assert sha256_file(Path(batch['profile'])) == batch['profile_sha256']
    assert sha256_file(DATABASE) == batch['structure_sha256']
    expected_split = 'dev' if args.stage == 'development' else 'test'
    assert read(args.input / 'run_protocol.json')['split'] == expected_split
    code = [Path(__file__), config_path, Path('src/inkstruct/component_trust.py'),
            Path('src/inkstruct/component_trust_translation.py'), Path('src/inkstruct/author_terminal_context.py'), Path('src/inkstruct/exemplar_variation.py'),
            Path('src/inkstruct/trajectory_experiment.py')]
    frozen = None
    if args.stage == 'regression':
        if args.development is None:
            raise ValueError('regression requires development freeze')
        frozen = read(args.development / 'frozen_choice.json')
        assert sha256_file(args.development / 'summary.json') == frozen['summary_sha256']
        assert sha256_file(args.development / 'run_protocol.json') == frozen['run_protocol_sha256']
        for path, expected in read(args.development / 'run_protocol.json')['code_sha256'].items():
            assert sha256_file(Path(path)) == expected, path
    radii = config['radii'] if frozen is None else [frozen['radius']]
    inputs = [args.batch / 'plan.json', Path(batch['profile']), args.input / 'run_protocol.json']
    inputs += sorted((args.input / 'generated').glob('*.json')) + sorted((args.input / 'cases').glob('*.json'))
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / 'run_protocol.json', {'protocol': config, 'stage': args.stage,
        'previously_observed': True, 'choice': frozen, 'source_input': str(args.input),
        'input_sha256': {str(p): sha256_file(p) for p in inputs},
        'code_sha256': {str(p): sha256_file(p) for p in code}})
    sources = load_profile(Path(batch['profile'])).source_trajectories
    repository = StructureRepository(DATABASE)
    generated = []
    for path in sorted((args.input / 'generated').glob('*.json')):
        row = read(path)  # contains no target captures
        task = row['task']
        graph = repository.get(task['character'])
        base, prepared = restore_candidates(row, sources)
        trust = prepare_component_trust(prepared, task['target_stroke_ids'])
        translated = translate_prepared_candidates(base, graph, task['target_stroke_ids'], prepared, sources)
        translated_trust = prepare_component_trust(translated, task['target_stroke_ids'])
        h, hmeta = prepared.select(.04, 'author')
        outputs = {'A': base, 'D': prepared.original, 'H': h}
        metadata = {'D': prepared.original_meta, 'H': hmeta}
        fixed = [(g, r) for g, r in translated.alternatives if hmeta['selected'] is not None
                 and r['candidate'] == hmeta['selected']['candidate']]
        if fixed:
            outputs['P'], record = fixed[0]
            metadata['P'] = {**hmeta, 'selected': record, 'total_selection_score':
                record['score']+.04*record['author_terminal_penalties']['author']}
        else:
            outputs['P'], metadata['P'] = h, hmeta
        for radius in radii:
            label = f'T_{radius}'
            outputs[label], metadata[label] = trust.select(radius)
            outputs[f'R_{radius}'], metadata[f'R_{radius}'] = translated_trust.select(radius)
        checks = {label: {'invariants': invariants(glyph, graph),
                  'new_crossings_vs_A': sorted(crossing_pairs(curves(glyph))-crossing_pairs(curves(base)))}
                  for label, glyph in outputs.items()}
        assert all(not v['invariants'] and not v['new_crossings_vs_A'] for v in checks.values())
        payload = {'task': task, 'outputs': {k: asdict(v) for k, v in outputs.items()},
                   'metadata': metadata, 'checks': checks}
        save(args.output / 'generated' / path.name, payload)
        generated.append((path.name, graph, outputs, payload))
    # All choices are now fixed and persisted; reference reads begin below.
    rows, excluded = [], []
    for filename, graph, outputs, payload in generated:
        reference_path = args.input / 'cases' / filename
        if not reference_path.exists():
            excluded.append({'character': graph.character, 'reason': 'no reliable reference in frozen source evaluation'})
            continue
        references = read(reference_path)['references']
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in payload['task']['target_stroke_ids']]
        cache, metrics, per_stroke, whole = {}, {}, {}, {}
        for label, glyph in outputs.items():
            coordinates = curves(glyph)
            key = tuple(tuple(tuple(p) for p in s) for s in coordinates)
            if key not in cache:
                raw = [[stroke_metrics(stroke, reference['curves'][i]) for i, stroke in enumerate(coordinates)]
                       for reference in references]
                averaged = [{metric: mean_present([r[i][metric] for r in raw]) for metric in METRICS}
                            for i in range(len(coordinates))]
                cache[key] = averaged
            averaged = cache[key]
            metrics[label] = {metric: mean_present([averaged[i][metric] for i in indices]) for metric in METRICS}
            whole[label] = {metric: mean_present([r[metric] for r in averaged]) for metric in METRICS}
            per_stroke[label] = {graph.strokes[i].stroke_id: averaged[i] for i in indices}
        record = {**payload, 'metrics': metrics, 'whole_metrics': whole, 'stroke_metrics': per_stroke,
                  'references': references}
        save(args.output / 'cases' / filename, record)
        rows.append(record)
        print('scored', len(rows), flush=True)
    summary = {label: {metric: mean_present([r['metrics'][label][metric] for r in rows]) for metric in METRICS}
               for label in rows[0]['outputs']}
    for label in rows[0]['metadata']:
        summary[label].update(
            activated=sum(r['metadata'][label]['selected'] is not None for r in rows),
            changed_from_D=sum((r['metadata'][label]['selected'] or {}).get('candidate') !=
                              (r['metadata']['D']['selected'] or {}).get('candidate') for r in rows),
            changed_from_H=sum((r['metadata'][label]['selected'] or {}).get('candidate') !=
                              (r['metadata']['H']['selected'] or {}).get('candidate') for r in rows),
            maximum_character_geometry_ratio=max(r['metrics'][label]['mean_distance']/max(r['metrics']['D']['mean_distance'], 1e-12) for r in rows),
            maximum_stroke_local_error_increase=max(s['max_distance']-r['stroke_metrics']['D'][sid]['max_distance']
                 for r in rows for sid, s in r['stroke_metrics'][label].items()))
    save(args.output / 'summary.json', summary)
    save(args.output / 'whole_summary.json', {label: {metric: mean_present([r['whole_metrics'][label][metric] for r in rows])
                                                     for metric in METRICS} for label in summary})
    save(args.output / 'coverage.json', {'generated_characters': len(generated), 'scored_characters': len(rows),
        'scored_captures': sum(len(r['references']) for r in rows), 'excluded': excluded,
        'scope': 'development' if args.stage == 'development' else 'previously observed regression; no fresh validation'})
    if args.stage == 'development':
        eligible = [radius for radius in radii if
            summary[f'R_{radius}']['activated'] == summary['D']['activated'] and
            summary[f'R_{radius}']['mean_distance'] <= summary['D']['mean_distance']*1.01 and
            summary[f'R_{radius}']['maximum_character_geometry_ratio'] <= 1.05+1e-12 and
            summary[f'R_{radius}']['maximum_stroke_local_error_increase'] <= .005+1e-12 and
            summary[f'R_{radius}']['terminal_angle_deg'] < summary['D']['terminal_angle_deg']-1e-12]
        radius = min(eligible, key=lambda r: (summary[f'R_{r}']['terminal_angle_deg'], r)) if eligible else 0.
        save(args.output / 'frozen_choice.json', {'radius': radius, 'label': f'R_{radius}',
            'summary_sha256': sha256_file(args.output / 'summary.json'),
            'run_protocol_sha256': sha256_file(args.output / 'run_protocol.json')})
        print('frozen radius', radius, flush=True)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
