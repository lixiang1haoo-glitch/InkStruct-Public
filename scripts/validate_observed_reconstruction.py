"""Exercise persisted observed reconstruction, fallback and source conservation on real captures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from run_raw_trajectory_experiment import rank, save

from inkstruct.generate import generate_run
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import (
    crossing_pairs,
    point_distances,
    protected_indices,
    stroke_metrics,
)


def read(path):
    return json.loads(path.read_text())


def curves(glyph):
    return [[(p['x'], p['y']) for p in s['points']] for s in glyph['strokes']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    database = Path('artifacts/structures/characters.sqlite3')
    repository = StructureRepository(database)
    plan = {'scope': 'known-character reconstruction; not generalization or parameter tuning',
            'minimum_mapping_confidence': .35, 'epsilon': .004, 'authors': {},
            'code_sha256': {str(p): sha256_file(p) for p in [Path(__file__), *[
                Path('src/inkstruct')/f'{name}.py' for name in ('observed_reconstruction', 'exemplar_generation',
                'generate', 'trajectory_experiment', 'cli', 'desktop')]]},
            'input_sha256': {str(database): sha256_file(database)}}
    for writer in ('scx', 'mjb'):
        source_path = Path(f'profiles/source_v1_20261007/{writer}/profile.json')
        base_path = Path(f'profiles/{writer}/profile.json')
        sources = load_profile(source_path).source_trajectories
        characters = list(dict.fromkeys(['岛', '尴']+[s.character for s in sorted(sources.values(), key=lambda s: rank(s.sample_id))]))[:64]
        plan['authors'][writer] = {'source': str(source_path), 'base': str(base_path), 'characters': characters,
                                  'absent_originals': ['丢', '侈', '徼', '黧']}
        plan['input_sha256'].update({str(p): sha256_file(p) for p in (source_path, base_path)})
    save(args.output / 'frozen_plan.json', plan)
    summary = {}
    for writer, setup in plan['authors'].items():
        sources = load_profile(Path(setup['source'])).source_trajectories
        by_character = {s.character: s for s in sources.values()}
        runs, manifests = {}, {}
        for label, mode in [('A', 'legacy'), ('B', 'source-raw'), ('C', 'source-simplified')]:
            options = {} if label == 'A' else {'trajectory_mode': mode, 'source_profile_path': Path(setup['source']), 'source_observed': True}
            manifests[label], runs[label] = generate_run(writer, setup['characters']+setup['absent_originals'], repository,
                Path(setup['base']), output_root=args.output / 'runs', run_id=label, png=False, **options)
            assert not manifests[label]['failed'], manifests[label]['failed']
            print(writer, label, manifests[label]['completed_count'], flush=True)
        for label in ('B', 'C'):
            before = {p: sha256_file(p) for p in (runs[label]/'trajectories').glob('*.json')}
            generate_run(writer, setup['characters']+setup['absent_originals'], repository, Path(setup['base']),
                output_root=args.output/'runs', run_id=label, png=False,
                trajectory_mode='source-raw' if label == 'B' else 'source-simplified',
                source_profile_path=Path(setup['source']), source_observed=True)
            assert all(sha256_file(p) == digest for p, digest in before.items())
        rows, retained = [], 0
        raw_points, simple_points = 0, 0
        for character in setup['characters']:
            outputs = {k: read(p/'trajectories'/f'U+{ord(character):04X}.json') for k, p in runs.items()}
            reconstructed = outputs['B']['source_components']['observed_reconstruction']['used']
            assert reconstructed == outputs['C']['source_components']['observed_reconstruction']['used']
            graph = repository.get(character)
            reference_map = {s.standard_stroke_id: s for s in by_character[character].strokes}
            reference = [reference_map[s.stroke_id].points for s in graph.strokes]
            metrics = {k: [stroke_metrics(points, actual) for points, actual in zip(curves(v), reference, strict=True)] for k, v in outputs.items()}
            if reconstructed:
                retained += 1
                for i, standard in enumerate(graph.strokes):
                    source = reference_map[standard.stroke_id]
                    raw, simple = outputs['B']['strokes'][i]['points'], outputs['C']['strokes'][i]['points']
                    kept = outputs['C']['source_components']['components'][0]['retained_source_indices'][i]
                    np.testing.assert_array_equal([(p['x'], p['y']) for p in raw], source.points)
                    assert [p['pressure'] for p in raw] == source.pressure
                    np.testing.assert_array_equal([(p['x'], p['y']) for p in simple], [source.points[j] for j in kept])
                    assert [p['pressure'] for p in simple] == [source.pressure[j] for j in kept]
                    np.testing.assert_array_equal(np.diff([p['t_ms'] for p in raw]), np.diff(source.t_ms))
                    np.testing.assert_array_equal(np.diff([p['t_ms'] for p in simple]), np.diff([source.t_ms[j] for j in kept]))
                    assert protected_indices(source.points).issubset(kept)
                    assert point_distances(source.points, [(p['x'], p['y']) for p in simple]).max() <= .004+1e-12
                    raw_points += len(raw)
                    simple_points += len(simple)
                assert crossing_pairs(curves(outputs['B'])) == crossing_pairs(reference) == crossing_pairs(curves(outputs['C']))
            case = {'writer': writer, 'character': character, 'reconstructed': reconstructed,
                    'reference': reference, 'reference_sha256': by_character[character].source_sha256,
                    'variants': outputs, 'metrics': metrics}
            save(args.output/'cases'/f'{writer}-U+{ord(character):04X}.json', case)
            rows.append(case)
        fallbacks = {}
        # A target absent from the source profile must remain byte-for-byte equal
        # to existing cross-character inference apart from explicit diagnostics.
        for character in setup['absent_originals']:
            for label, mode in [('B', 'source-raw'), ('C', 'source-simplified')]:
                _, off_run = generate_run(writer, [character], repository, Path(setup['base']),
                    output_root=args.output/'runs', run_id=f'off-{label}', png=False,
                    trajectory_mode=mode, source_profile_path=Path(setup['source']))
                off = read(off_run/'trajectories'/f'U+{ord(character):04X}.json')
                on = read(runs[label]/'trajectories'/f'U+{ord(character):04X}.json')
                assert not on['source_components']['observed_reconstruction']['used']
                off.pop('source_components'); on.pop('source_components')
                assert off == on
            fallbacks[character] = True
        summary[writer] = {'cases': len(rows), 'observed': retained, 'fallback': len(rows)-retained,
            'verified_raw_points': raw_points, 'simplified_points': simple_points, 'absent_capture_regression': fallbacks,
            'resume_identical': True, 'metrics_observed_only': {k: {metric: float(np.mean([
                np.mean([v[metric] for v in r['metrics'][k] if v[metric] is not None]) for r in rows if r['reconstructed']]))
                for metric in ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error', 'endpoint_error')}
                for k in ('A', 'B', 'C')},
            'rejected_characters': [r['character'] for r in rows if not r['reconstructed']]}
    save(args.output/'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
