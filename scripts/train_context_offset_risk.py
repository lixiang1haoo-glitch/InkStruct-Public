"""Audit numerical-gate mistakes and test shrinkage on public component contexts."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from experiment_component_trust import read
from run_raw_trajectory_experiment import DATABASE, save
from train_grouped_logistic_risk import identity, summarize

from inkstruct.context_offset_risk import base_logits, fit_offset
from inkstruct.exemplar_index import component_key
from inkstruct.grouped_logistic_risk import fit_grouped, meta_fold, sigmoid, validation_cells
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prior = read(args.prior / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in prior[group].items():
            assert sha256_file(Path(name)) == expected, name
    source = Path(prior['training']) / 'examples.json'
    original = read(source)
    repository = StructureRepository(DATABASE)
    rows = []
    for r in original:
        graph = repository.get(r['character'])
        component = next(c for c in graph.components if c.component_id == r['component_id'])
        rows.append({**r, 'context': component_key(graph, component)})
    config_path = Path('configs/experiments/context_offset_risk_v1.json')
    config = read(config_path)
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / 'examples.json', rows)
    files = [source, DATABASE, config_path, args.prior / 'run_protocol.json', args.prior / 'predictions.json',
             args.prior / 'source_audit.json', args.prior / 'summary.json']
    code = [Path(__file__), Path('src/inkstruct/context_offset_risk.py'), Path('src/inkstruct/grouped_logistic_risk.py'),
            Path('scripts/train_grouped_logistic_risk.py'), Path('src/inkstruct/exemplar_index.py'), Path('src/inkstruct/component_style.py'), config_path]
    save(args.output / 'run_protocol.json', {'prior': str(args.prior), 'config': config,
        'input_sha256': {str(p): sha256_file(p) for p in files}, 'code_sha256': {str(p): sha256_file(p) for p in code},
        'scope': 'training-only feature extension; development/regression originals unopened'})
    old_predictions = {tuple(r['identity']): r['scores']['combined_0.1'] for r in read(args.prior / 'predictions.json')}
    false_accepts = []
    for r in rows:
        score = old_predictions[identity(r)]
        if score < .8 or r['safe_benefit']:
            continue
        peers = [p for p in rows if p['fold'] == r['fold'] and meta_fold(p['character']) != meta_fold(r['character'])
                 and p['writer'] == r['writer'] and p['context'] == r['context']]
        false_accepts.append({'identity': identity(r), 'context': r['context'], 'score': score,
            'geometry_ratio': r['geometry_ratio'], 'local_increase': r['local_increase'], 'angle_increase': r['angle_increase'],
            'same_context_training_characters': sorted({p['character'] for p in peers}),
            'failed': [k for k, yes in [('geometry', r['geometry_ratio'] >= 1.-1e-12), ('local', r['local_increase'] > .005+1e-12), ('angle', r['angle_increase'] > .5+1e-12)] if yes]})
    save(args.output / 'numeric_false_accepts.json', false_accepts)
    grid = [('base', None)]+[(m, r) for m in config['modes'] for r in config['regularization']]
    name = lambda m, r: 'base' if m == 'base' else f'{m}_{r}'
    predictions = {name(*pair): {} for pair in grid}
    for generation, heldout, train, valid in validation_cells(rows):
        assert not {r['character'] for r in train} & {r['character'] for r in valid}
        base = fit_grouped(train, view='combined', regularization=.1)
        assert base.payload() == read(args.prior / 'models' / f'{generation}-{heldout}-combined_0.1.json')
        x = [r['features'] for r in valid]
        scores = base.predict(x)
        logits_train, logits_valid = base_logits(base, [r['features'] for r in train]), base_logits(base, x)
        for r, score in zip(valid, scores, strict=True):
            assert float(score) == old_predictions[identity(r)]
            predictions['base'][identity(r)] = float(score)
        for mode, regularization in grid[1:]:
            correction = fit_offset(train, logits_train, mode=mode, regularization=regularization)
            label = name(mode, regularization)
            scores = sigmoid(logits_valid+correction.offset(valid))
            for r, score in zip(valid, scores, strict=True):
                assert identity(r) not in predictions[label]
                predictions[label][identity(r)] = float(score)
            save(args.output / 'models' / f'{generation}-{heldout}-{label}.json', correction.payload())
        print('context validation', generation, heldout, flush=True)
    summary = {}
    for label, mapping in predictions.items():
        assert len(mapping) == len(rows)
        detail = {'all': summarize(rows, [mapping[identity(r)] for r in rows])}
        for field in ('writer', 'fold'):
            detail[field] = {str(value): summarize([r for r in rows if r[field] == value], [mapping[identity(r)] for r in rows if r[field] == value]) for value in sorted({r[field] for r in rows})}
        summary[label] = detail
    selected = min(grid, key=lambda pair: (summary[name(*pair)]['all']['brier'], summary[name(*pair)]['all']['log_loss'],
        ['base', 'author', 'component', 'hierarchical'].index(pair[0]), -(pair[1] or 0)))
    save(args.output / 'summary.json', summary)
    save(args.output / 'predictions.json', [{'identity': identity(r), 'fold': r['fold'], 'safe_benefit': r['safe_benefit'],
        'scores': {label: values[identity(r)] for label, values in predictions.items()}} for r in rows])
    save(args.output / 'frozen_choice.json', {'label': name(*selected), 'mode': selected[0], 'regularization': selected[1], 'threshold': .8,
        'summary_sha256': sha256_file(args.output / 'summary.json'), 'run_protocol_sha256': sha256_file(args.output / 'run_protocol.json'),
        'training_examples_sha256': sha256_file(args.output / 'examples.json')})
    save(args.output / 'coverage.json', {'contexts': len({r['context'] for r in rows}), 'author_contexts': len({(r['writer'], r['context']) for r in rows}),
        'false_accept_rows': len(false_accepts), 'false_accept_groups': len({tuple(r['identity'][:2]) for r in false_accepts}),
        'no_context_groups': len({tuple(r['identity'][:2]) for r in false_accepts if not r['same_context_training_characters']}),
        'failure_combinations': dict(Counter('|'.join(r['failed']) for r in false_accepts))})
    print('frozen', selected, flush=True)
    for label, values in summary.items():
        print(label, values['all'], flush=True)


if __name__ == '__main__':
    main()
