"""Verify saved B/C point provenance and classify new crossing warnings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.trajectory_experiment import crossing_pairs


def verify(root):
    sources = load_profile(Path('profiles/source_v1_20261007/scx/profile.json')).source_trajectories
    verified, points = 0, 0
    crossing_cases = []
    for file in sorted((root / 'cases').glob('*.json')):
        case = json.loads(file.read_text())
        for label in ('B', 'C', 'B_xy', 'C_xy'):
            if label not in case['variants']:
                continue
            provenance = case['provenance'][label]
            donor = provenance['donor']
            sample = sources[donor['sample_id']]
            assert sample.source_sha256 == donor['source_sha256']
            stroke_map = {s.standard_stroke_id: s for s in sample.strokes}
            selected = ([stroke_map[k] for k in donor['stroke_ids']]
                        if case['task']['task'] == 'cross' else sample.strokes)
            transform = provenance['transform']
            if not label.endswith('_xy'):
                assert transform['sx'] == transform['sy']
            else:
                assert max(transform['sx'], transform['sy']) / min(transform['sx'], transform['sy']) <= 1.15 + 1e-12
            for index, stroke, retained in zip(case['indices'], selected, provenance['source_indices'], strict=True):
                actual = case['variants'][label]['strokes'][index]['points']
                expected = [(stroke.points[j][0] * transform['sx'] + transform['tx'],
                             stroke.points[j][1] * transform['sy'] + transform['ty']) for j in retained]
                assert len(actual) == len(expected)
                assert np.allclose([(p['x'], p['y']) for p in actual], expected, atol=1e-12, rtol=0)
                assert [p['pressure'] for p in actual] == [stroke.pressure[j] for j in retained]
                assert [p['t_ms'] - actual[0]['t_ms'] for p in actual] == [round(stroke.t_ms[j] - stroke.t_ms[retained[0]]) for j in retained]
                if label.startswith('B'):
                    assert retained == list(range(len(stroke.points)))
                points += len(actual)
            verified += 1
        if case['task']['task'] == 'cross' and case['task']['split'] == 'test':
            reference = crossing_pairs(case['reference'])
            added = case['scores']['B']['aggregate']['new_crossing_pairs_vs_A']
            if added:
                absent = [p for p in added if tuple(p) not in reference]
                external = [p for p in added if not set(p) <= set(case['indices'])]
                crossing_cases.append({'character': case['task']['character'],
                                       'new_vs_A': added, 'also_absent_in_reference': absent,
                                       'involves_external_stroke': external})
    return {'verified_B_C_glyphs': verified, 'verified_source_index_points': points,
            'coordinate_pressure_time_provenance_failures': 0,
            'cross_test_B_crossing_warnings': crossing_cases,
            'results_sha256': sha256_file(root / 'results.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.input)
    with (args.input / 'integrity_verification.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
