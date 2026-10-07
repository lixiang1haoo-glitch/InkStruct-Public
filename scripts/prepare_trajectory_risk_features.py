"""Attach inference-only geometry evidence to unchanged crossfit trial labels."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from experiment_component_trust import glyph_from_dict, read
from run_raw_trajectory_experiment import save

from inkstruct.samples import sha256_file
from inkstruct.trajectory_layout_risk import stroke_geometry_features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prior = read(args.prior / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in prior[group].items():
            assert sha256_file(Path(name)) == expected, name
    manifest = read(args.prior / 'generation_manifest.json')
    for name, expected in manifest.items():
        assert sha256_file(Path(name)) == expected, name
    config = Path('configs/experiments/trajectory_layout_risk_v1.json')
    extra = [config, args.prior / 'run_protocol.json', args.prior / 'generation_manifest.json', args.prior / 'examples.json']
    code = [Path(__file__), Path('src/inkstruct/trajectory_layout_risk.py')]
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / 'run_protocol.json', {'config': read(config), 'prior': str(args.prior),
        'input_sha256': {**prior['input_sha256'], **{str(p): sha256_file(p) for p in extra}},
        'code_sha256': {**prior['code_sha256'], **{str(p): sha256_file(p) for p in code}},
        'contract': 'Only add features from frozen A/D/P; labels, candidates and geometry unchanged'})
    result, cache, coverage = [], {}, Counter()
    for i, e in enumerate(read(args.prior / 'examples.json')):
        path = Path(e['generated_file'])
        assert sha256_file(path) == e['generated_sha256']
        trial = read(path)
        old_path = Path(trial['frozen_input'])
        if old_path not in cache:
            assert sha256_file(old_path) == trial['frozen_input_sha256']
            old = read(old_path)
            cache[old_path] = (glyph_from_dict(old['outputs']['A']), glyph_from_dict(old['outputs']['D']))
        base, original = cache[old_path]
        features, evidence = stroke_geometry_features(base, original, glyph_from_dict(trial['output']), trial['task']['target_stroke_ids'])
        enriched = {**e, 'layout_features': e['features'], 'geometry_features': features,
            'features': e['features']+features, 'geometry_evidence': evidence,
            'frozen_input': str(old_path), 'frozen_input_sha256': trial['frozen_input_sha256']}
        save(args.output / 'examples' / path.name, enriched)
        result.append(enriched)
        coverage[e['writer']] += 1
        if (i+1) % 250 == 0:
            print('features', i+1, flush=True)
    save(args.output / 'examples.json', result)
    save(args.output / 'coverage.json', {'labels': dict(coverage), 'total': len(result),
        'author_character_count': len({(e['writer'], e['character']) for e in result}),
        'feature_dimensions': {'layout': 22, 'geometry': 24}, 'labels_changed': 0, 'outputs_regenerated': 0})
    print('complete', len(result), flush=True)


if __name__ == '__main__':
    main()
