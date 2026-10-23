"""Freeze risk feature/regularization selection using source-isolated inner folds."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from experiment_component_trust import read
from run_raw_trajectory_experiment import save

from inkstruct.grouped_logistic_risk import fit_grouped, group_weights, validation_cells
from inkstruct.layout_risk import training_fold
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file


def identity(row):
    return row['writer'], row['character'], row['component_id'], row['proposal_id']


def summarize(rows, scores):
    w = group_weights(rows)
    y = np.asarray([r['safe_benefit'] for r in rows], dtype=float)
    p = np.clip(np.asarray(scores), 1e-12, 1-1e-12)
    mask = p >= .8
    return {'rows': len(rows), 'writer_characters': len({(r['writer'], r['character']) for r in rows}),
            'brier': float(w@((p-y)**2)), 'log_loss': float(-w@(y*np.log(p)+(1-y)*np.log(1-p))),
            'accepted_rows': int(mask.sum()), 'accepted_weight': float(w@mask),
            'accepted_writer_characters': len({(r['writer'], r['character']) for r, yes in zip(rows, mask, strict=True) if yes}),
            'safe_fraction_among_accepted': float((w*mask)@y/(w@mask)) if mask.any() else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prior = read(args.training / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in prior[group].items():
            assert sha256_file(Path(name)) == expected, name
    rows = read(args.training / 'examples.json')
    assert len({identity(r) for r in rows}) == len(rows)
    assert all(r['fold'] == training_fold(r['character']) for r in rows)
    config_path = Path('configs/experiments/grouped_logistic_risk_v1.json')
    config = read(config_path)
    args.output.mkdir(parents=True, exist_ok=False)
    files = [args.training / 'run_protocol.json', args.training / 'examples.json', config_path]
    manifests = sorted({Path(r['frozen_input']).parent.parent / 'fold_manifest.json' for r in rows})
    files += manifests
    audits = []
    for path in manifests:
        fold = read(path)
        profile_path = Path(fold['profile'])
        assert sha256_file(profile_path) == fold['profile_sha256']
        profile = load_profile(profile_path)
        assert all(training_fold(s.character) != fold['fold'] for s in profile.source_trajectories.values())
        audits.append({'fold_manifest': str(path), 'generation_fold': fold['fold'],
                       'source_count': len(profile.source_trajectories), 'excluded_entire_target_fold': True})
        files.append(profile_path)
    code = [Path(__file__), Path('src/inkstruct/grouped_logistic_risk.py'), config_path]
    save(args.output / 'run_protocol.json', {'training': str(args.training), 'config': config,
        'input_sha256': {str(p): sha256_file(p) for p in files},
        'code_sha256': {str(p): sha256_file(p) for p in code},
        'scope': 'training-only model selection; existing development/regression references unopened'})
    grid = [(view, reg) for view in config['feature_views'] for reg in config['regularization']]
    predictions = {f'{view}_{reg}': {} for view, reg in grid}
    predictions['constant'] = {}
    splits = []
    for generation, heldout, train, valid in validation_cells(rows):
        assert not {r['character'] for r in train} & {r['character'] for r in valid}
        assert all(r['fold'] == generation for r in train+valid)
        split = {'generation_fold': generation, 'heldout_meta_fold': heldout,
            'train_characters': sorted({r['character'] for r in train}), 'validation_characters': sorted({r['character'] for r in valid}),
            'train_rows': len(train), 'validation_rows': len(valid)}
        splits.append(split)
        x = [r['features'] for r in valid]
        prevalence = float(group_weights(train)@np.asarray([r['safe_benefit'] for r in train]))
        for r in valid:
            predictions['constant'][identity(r)] = prevalence
        for view, reg in grid:
            model = fit_grouped(train, view=view, regularization=reg)
            label = f'{view}_{reg}'
            scores = model.predict(x)
            for r, p in zip(valid, scores, strict=True):
                assert identity(r) not in predictions[label]
                predictions[label][identity(r)] = float(p)
            save(args.output / 'models' / f'{generation}-{heldout}-{label}.json', model.payload())
        print('validation cell', generation, heldout, len(train), len(valid), flush=True)
    summary = {}
    for label, mapping in predictions.items():
        assert len(mapping) == len(rows)
        scores = [mapping[identity(r)] for r in rows]
        detail = {'all': summarize(rows, scores)}
        for field in ('writer', 'fold'):
            detail[field] = {}
            for value in sorted({r[field] for r in rows}):
                selected = [r for r in rows if r[field] == value]
                detail[field][value] = summarize(selected, [mapping[identity(r)] for r in selected])
        summary[label] = detail
    selected = min(grid, key=lambda p: (summary[f'{p[0]}_{p[1]}']['all']['brier'],
        summary[f'{p[0]}_{p[1]}']['all']['log_loss'], {'layout': 22, 'geometry': 24, 'combined': 46}[p[0]], -p[1]))
    label = f'{selected[0]}_{selected[1]}'
    save(args.output / 'summary.json', summary)
    save(args.output / 'splits.json', splits)
    save(args.output / 'predictions.json', [{'identity': identity(r), 'fold': r['fold'], 'safe_benefit': r['safe_benefit'],
        'scores': {k: v[identity(r)] for k, v in predictions.items()}} for r in rows])
    save(args.output / 'source_audit.json', audits)
    save(args.output / 'frozen_choice.json', {'label': label, 'view': selected[0], 'regularization': selected[1], 'threshold': .8,
        'summary_sha256': sha256_file(args.output / 'summary.json'), 'run_protocol_sha256': sha256_file(args.output / 'run_protocol.json'),
        'training_examples_sha256': sha256_file(args.training / 'examples.json')})
    print('frozen', label, flush=True)
    for key, value in summary.items():
        print(key, value['all'], flush=True)


if __name__ == '__main__':
    main()
