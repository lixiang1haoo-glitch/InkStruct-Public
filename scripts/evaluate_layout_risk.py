"""Develop a paired-outcome gate, then regress its frozen choice without retuning."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from experiment_component_trust import glyph_from_dict, mean_present, read
from regress_calibrated_layout_writers import audit_generated
from run_raw_trajectory_experiment import DATABASE, save

from inkstruct.layout_risk import LayoutRiskGate, move_features
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository

ROOT = Path('artifacts/learned_component_layout_20261007')
MULTI = Path('artifacts/layout_multiwriter_20261007/regression_v2')
METRICS = ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error', 'endpoint_error')


def normalize_input(row, writer):
    """Generated files only; this adapter never accepts a reference field."""
    assert 'reference' not in row and 'references' not in row
    labels = {'A': 'A', 'D': 'D', 'B': 'B_D_1.0', 'M': 'M_D_1.0'} if writer == 'user_001' else {k: k for k in ('A', 'D', 'B', 'M')}
    return {'writer': writer, 'task': row['task'], 'outputs': {k: row['outputs'][v] for k, v in labels.items()},
            'metadata': {k: row['metadata'][v] for k, v in labels.items() if k != 'A'}, 'predictions': row['predictions']}, labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--stage', choices=['development', 'regression'], required=True)
    parser.add_argument('--development', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config_path = Path('configs/experiments/crossfit_layout_risk_v1.json')
    config = read(config_path)
    train_protocol = read(args.training / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in train_protocol[group].items():
            assert sha256_file(Path(name)) == expected, name
    examples = read(args.training / 'examples.json')
    gate = LayoutRiskGate(examples)
    choice = None
    if args.stage == 'regression':
        assert args.development is not None
        choice = read(args.development / 'frozen_choice.json')
        for key in ('summary', 'run_protocol'):
            assert sha256_file(args.development / (key+'.json')) == choice[key+'_sha256']
        frozen = read(args.development / 'run_protocol.json')
        assert frozen['training_examples_sha256'] == sha256_file(args.training / 'examples.json')
        for name, expected in frozen['code_sha256'].items():
            assert sha256_file(Path(name)) == expected, name
    arms = [(f'{scope}_{threshold}', scope, threshold) for scope in config['development_scopes'] for threshold in config['development_thresholds']]
    if choice:
        arms = [] if choice['label'] == 'D' else [(choice['label'], choice['scope'], choice['threshold'])]
    inputs = [('user_001', ROOT / ('calibrated_development_v1' if args.stage == 'development' else 'regression_v1'))]
    if args.stage == 'regression':
        inputs += [(writer, MULTI) for writer in ('scx', 'mjb', 'wsq')]
    batch = read(Path('artifacts/author_terminal_context_20261007/batch_v1/plan.json'))
    profiles = {'user_001': Path(batch['profile']), **{w: MULTI / 'training' / (w+'.json') for w in ('scx', 'mjb', 'wsq')}}
    files = [config_path, DATABASE, args.training / 'examples.json', args.training / 'run_protocol.json']
    rows = []
    for writer, folder in inputs:
        for path in sorted((folder / 'generated').glob('*.json')):
            old = read(path)
            if writer != 'user_001' and old['writer'] != writer:
                continue
            row, labels = normalize_input(old, writer)
            rows.append((row, folder, path, labels))
            files.append(path)
            case = folder / 'cases' / path.name
            if case.exists():
                files.append(case)
        files.append(profiles[writer])
    args.output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), Path('src/inkstruct/layout_risk.py'), config_path,
            Path('scripts/regress_calibrated_layout_writers.py')]
    save(args.output / 'run_protocol.json', {'stage': args.stage, 'choice': choice, 'config': config,
        'training_examples_sha256': sha256_file(args.training / 'examples.json'),
        'input_sha256': {str(p): sha256_file(p) for p in files}, 'code_sha256': {str(p): sha256_file(p) for p in code},
        'profiles': {w: str(profiles[w]) for w, _ in inputs}, 'scope': 'observed development/regression; not fresh validation'})
    repository = StructureRepository(DATABASE)
    archives = {w: load_profile(profiles[w]).source_trajectories for w, _ in inputs}
    pending, audit = [], Counter()
    for row, folder, path, labels in rows:
        graph = repository.get(row['task']['character'])
        ids = row['task']['target_stroke_ids']
        component = next(c for c in graph.components if [s.stroke_id for s in graph.strokes if s.stroke_id in c.stroke_ids] == ids)
        changed = row['outputs']['M'] != row['outputs']['D']
        features = move_features(graph, component, glyph_from_dict(row['outputs']['D']), glyph_from_dict(row['outputs']['M']),
            row['predictions']['learned'], row['metadata']['B'].get('layout_band', {})) if changed else None
        decisions, selected_labels = {}, {k: k for k in ('A', 'D', 'B', 'M')}
        for label, scope, threshold in arms:
            decision = gate.predict(row['writer'], graph.character, features, scope=scope, threshold=threshold) if changed else {
                'accepted': False, 'available': False, 'reason': 'frozen M makes no change'}
            source = 'M' if decision['accepted'] else 'D'
            row['outputs'][label] = row['outputs'][source]
            row['metadata'][label] = {**row['metadata'][source], 'layout_risk': decision}
            decisions[label], selected_labels[label] = decision, source
        row['outputs']['off'], row['metadata']['off'] = row['outputs']['D'], row['metadata']['D']
        selected_labels['off'] = 'D'
        row.update(features=features, decisions=decisions, selected_labels=selected_labels,
                   frozen_input=str(path), frozen_input_sha256=sha256_file(path))
        audit.update(audit_generated(row, archives[row['writer']], repository))
        for label, source in selected_labels.items():
            assert asdict(glyph_from_dict(row['outputs'][label])) == row['outputs'][source]
        target_path = args.output / 'generated' / path.name
        save(target_path, row)
        pending.append((target_path, folder / 'cases' / path.name, labels))
    save(args.output / 'generation_manifest.json', {str(p): sha256_file(p) for p, _, _ in pending})
    save(args.output / 'integrity_audit.json', dict(audit))
    groups, excluded = {}, []
    for path, case_path, labels in pending:
        if not case_path.exists():
            excluded.append(path.name)
            continue
        row, old = read(path), read(case_path)
        for k, v in labels.items():
            assert row['outputs'][k] == old['outputs'][v]
        row['metrics'] = {label: {k: old['metrics'][labels[source]][k] for k in METRICS} for label, source in row['selected_labels'].items()}
        row['stroke_metrics'] = {label: old['stroke_metrics'][labels[source]] for label, source in row['selected_labels'].items()}
        row['whole_metrics'] = {label: {k: old['whole_metrics'][labels[source]][k] for k in METRICS} for label, source in row['selected_labels'].items()}
        row['references'] = old['references'] if 'references' in old else [{'curves': old['reference'], 'source_sha256': old['reference_sha256']}]
        save(args.output / 'cases' / path.name, row)
        groups.setdefault(row['writer'], []).append(row)
    summaries = {}
    for writer, group in groups.items():
        summary = {label: {k: mean_present([r['metrics'][label][k] for r in group]) for k in METRICS} for label in group[0]['outputs']}
        for label, s in summary.items():
            s.update(changed_characters=[r['task']['character'] for r in group if r['outputs'][label] != r['outputs']['D']],
                maximum_character_geometry_ratio=max(r['metrics'][label]['mean_distance']/max(r['metrics']['D']['mean_distance'], 1e-12) for r in group),
                maximum_stroke_local_error_increase=max(p['max_distance']-r['stroke_metrics']['D'][sid]['max_distance'] for r in group for sid, p in r['stroke_metrics'][label].items()))
            s['passes_gates'] = s['mean_distance'] < summary['D']['mean_distance']-1e-12 and s['terminal_angle_deg'] <= summary['D']['terminal_angle_deg']+.5 and s['maximum_character_geometry_ratio'] <= 1.05+1e-12 and s['maximum_stroke_local_error_increase'] <= .005+1e-12
        summaries[writer] = {'n': len(group), 'captures': sum(len(r['references']) for r in group), 'component': summary,
            'whole': {label: {k: mean_present([r['whole_metrics'][label][k] for r in group]) for k in METRICS} for label in summary}}
    save(args.output / 'summary.json', summaries)
    save(args.output / 'coverage.json', {'generated': len(pending), 'scored': sum(len(r) for r in groups.values()), 'excluded': excluded})
    if args.stage == 'development':
        summary = summaries['user_001']['component']
        eligible = [(label, scope, threshold) for label, scope, threshold in arms if summary[label]['passes_gates']]
        selected = min(eligible, key=lambda a: (summary[a[0]]['mean_distance'], a[1] != 'author', -a[2])) if eligible else ('D', None, None)
        save(args.output / 'frozen_choice.json', {'label': selected[0], 'scope': selected[1], 'threshold': selected[2],
            'summary_sha256': sha256_file(args.output / 'summary.json'), 'run_protocol_sha256': sha256_file(args.output / 'run_protocol.json')})
        print('frozen', selected, flush=True)
    for writer, s in summaries.items():
        print(writer, {label: {'geometry': v['mean_distance'], 'changed': v['changed_characters'], 'passes': v['passes_gates']} for label, v in s['component'].items()}, flush=True)


if __name__ == '__main__':
    main()
