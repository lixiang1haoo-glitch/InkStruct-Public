"""Post-confirmation integrity and score-margin audit; never retunes selection."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import numpy as np
from run_raw_trajectory_experiment import save

from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.trajectory_experiment import SharedTransform


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    plan = json.loads((args.input / 'frozen_plan.json').read_text())
    sources = load_profile(Path(plan['sources'])).source_trajectories
    assert sha256_file(Path(plan['sources'])) == plan['input_sha256'][plan['sources']]
    rows = [json.loads(p.read_text()) for p in sorted((args.input / 'cases').glob('*.json'))]
    counts, thresholds = Counter(), []
    point_count = 0
    for row in rows:
        candidates = [c for c in row['provenance_D']['candidates'] if c.get('accepted')]
        selected = row['provenance_D']['selected']
        counts[f'safe_{len(candidates)}'] += 1
        if len(candidates) > 1:
            counts['multiple_safe'] += 1
            lower = [c for c in candidates if c['terminal_penalties']['structure'] < selected['terminal_penalties']['structure'] - 1e-12]
            if lower:
                thresholds.append(min((c['score']-selected['score']) / (selected['terminal_penalties']['structure']-c['terminal_penalties']['structure']) for c in lower))
            else:
                counts['D_already_min_structure_penalty'] += 1
        chosen = row['provenance_E']['selected']
        if not chosen:
            continue
        candidate = chosen['candidate']
        source = sources[candidate['sample_id']]
        assert source.source_sha256 == candidate['source_sha256']
        mapping = {s.standard_stroke_id: s for s in source.strokes}
        transform = SharedTransform(**chosen['transform'])
        outputs = [s for s in row['variants']['E']['strokes'] if s['standard_stroke_id'] in row['task']['target_stroke_ids']]
        for sid, output in zip(candidate['stroke_ids'], outputs, strict=True):
            stroke = mapping[sid]
            np.testing.assert_allclose([(p['x'], p['y']) for p in output['points']], transform.apply(stroke.points), atol=1e-12, rtol=0)
            assert [p['pressure'] for p in output['points']] == stroke.pressure
            assert [p['t_ms']-output['points'][0]['t_ms'] for p in output['points']] == [round(t-stroke.t_ms[0]) for t in stroke.t_ms]
            point_count += len(stroke.points)
    result = {'identical_D_E_outputs': sum(r['variants']['D'] == r['variants']['E'] for r in rows),
        'confirmed_complete_source_points': point_count, 'counts': dict(counts),
        'minimum_rank_change_weight': min(thresholds) if thresholds else None,
        'median_rank_change_weight': statistics.median(thresholds) if thresholds else None,
        'meaning': 'post-confirmation score-margin audit only; weights not changed, no counterfactual outcome optimization',
        'code_sha256': sha256_file(Path('src/inkstruct/terminal_selection.py'))}
    save(args.output or args.input / 'integrity_and_candidate_audit.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
