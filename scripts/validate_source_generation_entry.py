"""Regression of the opt-in entry on previously observed, frozen character groups."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from confirm_contextual_trajectory import split

from inkstruct.evaluate import evaluate_run
from inkstruct.generate import generate_run
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import (
    SharedTransform,
    crossing_pairs,
    point_distances,
    stroke_metrics,
)


def read(path):
    return json.loads(path.read_text())


def curves(payload):
    return [[(p['x'], p['y']) for p in s['points']] for s in payload['strokes']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    frozen = read(args.plan)
    database = Path('artifacts/structures/characters.sqlite3')
    assert sha256_file(database) == frozen['structure_sha256']
    repository = StructureRepository(database)
    results = {}
    for writer, dataset in frozen['datasets'].items():
        for key in ('sources', 'train_profile'):
            assert sha256_file(Path(dataset[key])) == dataset[key + '_sha256']
        sources = load_profile(Path(dataset['sources'])).source_trajectories
        train = {s.character for s in sources.values() if split(s.character) == 'train'}
        whitelist = args.output / f'{writer}_train_characters.txt'
        whitelist.write_text(''.join(sorted(train)))
        characters = [task['character'] for task in dataset['tasks']]
        assert not train.intersection(characters)
        runs, manifests = {}, {}
        for mode in ('legacy', 'source-raw', 'source-simplified'):
            options = {} if mode == 'legacy' else {'source_profile_path': Path(dataset['sources']),
                'source_characters_path': whitelist, 'source_nested_views': True}
            manifest, run = generate_run(writer, characters, repository, Path(dataset['train_profile']),
                output_root=args.output / 'runs', run_id=mode, png=False, trajectory_mode=mode, **options)
            assert manifest['failed_count'] == 0
            evaluation = evaluate_run(run, repository)
            assert evaluation['content_safety_passed']
            runs[mode] = run
            manifests[mode] = manifest
        rows, retained_points, complete_points = [], 0, 0
        for task in dataset['tasks']:
            character = task['character']
            path = f'trajectories/U+{ord(character):04X}.json'
            outputs = {mode: read(run / path) for mode, run in runs.items()}
            raw = outputs['source-raw']; simple = outputs['source-simplified']
            raw_meta = raw['source_components']; simple_meta = simple['source_components']
            assert [r.get('selection', {}).get('selected') for r in raw_meta['components']] == [
                r.get('selection', {}).get('selected') for r in simple_meta['components']]
            baseline_crossings = crossing_pairs(curves(outputs['legacy']))
            raw_crossings = crossing_pairs(curves(raw))
            assert not raw_crossings - baseline_crossings
            assert crossing_pairs(curves(simple)) == raw_crossings
            for record in simple_meta['components']:
                selected = record.get('selection', {}).get('selected')
                if not selected:
                    continue
                candidate = selected['candidate']
                assert candidate['character'] in train and candidate['character'] != character
                donor = sources[candidate['sample_id']]
                assert donor.source_sha256 == candidate['source_sha256']
                mapping = {s.standard_stroke_id: s for s in donor.strokes}
                transform = SharedTransform(**selected['transform'])
                assert transform.sx == transform.sy
                for sid, target_id, keep in zip(candidate['stroke_ids'], record['target_stroke_ids'],
                                                record['retained_source_indices'], strict=True):
                    source = mapping[sid]
                    a = next(s for s in raw['strokes'] if s['standard_stroke_id'] == target_id)
                    b = next(s for s in simple['strokes'] if s['standard_stroke_id'] == target_id)
                    expected = transform.apply(source.points)
                    np.testing.assert_allclose([(p['x'], p['y']) for p in a['points']], expected, atol=1e-12, rtol=0)
                    assert [p['pressure'] for p in a['points']] == source.pressure
                    assert [p['pressure'] for p in b['points']] == [source.pressure[i] for i in keep]
                    assert point_distances(expected, [(p['x'], p['y']) for p in b['points']]).max() <= .004 + 1e-12
                    complete_points += len(source.points)
                    retained_points += len(keep)
            # Targets are used only here, after all three complete runs are fixed.
            reference = {s.standard_stroke_id: s.points for s in sources[task['target_sample_id']].strokes}
            metrics = {}
            for mode, payload in outputs.items():
                per_stroke = [stroke_metrics(c, reference[s['standard_stroke_id']])
                    for c, s in zip(curves(payload), payload['strokes'], strict=True)]
                metrics[mode] = {key: float(np.mean([m[key] for m in per_stroke if m[key] is not None]))
                    for key in ('mean_distance', 'terminal_angle_deg')}
            rows.append({'character': character, 'accepted_components': raw_meta['accepted_component_count'],
                'identical_donor_schedule': True, 'no_new_strict_crossings': True,
                'simplification_raw_fallbacks': sum(bool(r.get('simplification_fallback')) for r in simple_meta['components']),
                'metrics_whole_glyph': metrics})
        # Resume must keep every delivered trajectory byte-for-byte identical.
        run = runs['source-raw']
        before = {p.name: sha256_file(p) for p in (run / 'trajectories').glob('*.json')}
        resumed, _ = generate_run(writer, characters, repository, Path(dataset['train_profile']),
            output_root=args.output / 'runs', run_id='source-raw', png=False, trajectory_mode='source-raw',
            source_profile_path=Path(dataset['sources']), source_characters_path=whitelist, source_nested_views=True)
        assert resumed['completed_count'] == len(characters)
        assert before == {p.name: sha256_file(p) for p in (run / 'trajectories').glob('*.json')}
        results[writer] = {'characters': len(rows), 'source_active_characters': sum(r['accepted_components'] > 0 for r in rows),
            'accepted_components': sum(r['accepted_components'] for r in rows),
            'complete_source_points': complete_points, 'simplified_source_points': retained_points,
            'all_invariants_passed': True, 'resume_byte_identical': True,
            'rows': rows, 'run_directories': {m: str(p) for m, p in runs.items()},
            'mean_whole_glyph_metrics': {m: {key: float(np.mean([r['metrics_whole_glyph'][m][key] for r in rows]))
                for key in ('mean_distance', 'terminal_angle_deg')} for m in runs}}
        print(writer, {k: v for k, v in results[writer].items() if k not in ('rows', 'run_directories')}, flush=True)
    summary = {'scope': 'integration regression on already observed cases, not a fresh holdout or tuned comparison',
               'plan_sha256': sha256_file(args.plan), 'results': results}
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
