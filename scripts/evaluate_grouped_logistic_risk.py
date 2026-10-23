"""Apply a training-frozen risk model to existing development and regression."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from experiment_component_trust import mean_present, read
from regress_calibrated_layout_writers import audit_generated
from report_counterfactual_layout_risk import verify_run
from run_raw_trajectory_experiment import DATABASE, save

from inkstruct.grouped_logistic_risk import GroupedLogisticRiskGate
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository

CONTROL = 'g0.0_pooled_0.6'
METRICS = ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error', 'endpoint_error')
SOURCES = Path('artifacts/trajectory_layout_risk_20261007')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--stage', choices=['development', 'regression'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    training = read(args.training / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in training[group].items():
            assert sha256_file(Path(name)) == expected, name
    choice = read(args.training / 'frozen_choice.json')
    for key in ('summary', 'run_protocol'):
        assert choice[key+'_sha256'] == sha256_file(args.training / (key+'.json'))
    examples_path = Path(training['training']) / 'examples.json'
    assert sha256_file(examples_path) == choice['training_examples_sha256']
    examples = read(examples_path)
    gate = GroupedLogisticRiskGate(examples, view=choice['view'], regularization=choice['regularization'])
    folder = SOURCES / ('development_v2' if args.stage == 'development' else 'regression_v1')
    old_protocol = verify_run(folder)
    files = [args.training / 'run_protocol.json', args.training / 'summary.json', args.training / 'frozen_choice.json',
             examples_path, folder / 'run_protocol.json', folder / 'generation_manifest.json', DATABASE]
    paths = sorted((folder / 'generated').glob('*.json'))
    files += paths
    files += [folder / 'cases' / p.name for p in paths if (folder / 'cases' / p.name).exists()]
    files += [Path(p) for p in old_protocol['profiles'].values()]
    args.output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), Path('src/inkstruct/grouped_logistic_risk.py'), Path('scripts/regress_calibrated_layout_writers.py')]
    save(args.output / 'run_protocol.json', {'stage': args.stage, 'training': str(args.training), 'frozen_source': str(folder),
        'choice': choice, 'profiles': old_protocol['profiles'], 'input_sha256': {str(p): sha256_file(p) for p in files},
        'code_sha256': {str(p): sha256_file(p) for p in code},
        'scope': 'Observed cohorts; all parameters selected in training-only inner validation, no development tuning'})
    archives = {w: load_profile(Path(p)).source_trajectories for w, p in old_protocol['profiles'].items()}
    repository = StructureRepository(DATABASE)
    pending, audit = [], Counter()
    for path in paths:
        old = read(path)
        assert 'references' not in old and 'metrics' not in old
        character = old['task']['character']
        decision = gate.predict(character, old['features'], threshold=choice['threshold']) if old['features'] is not None else {
            'available': False, 'accepted': False, 'reason': 'frozen M makes no change'}
        source = 'M' if decision['accepted'] else 'D'
        selected = {k: k for k in ('A', 'D', 'M', CONTROL)}
        selected.update(G=source, off='D')
        row = {k: old[k] for k in ('writer', 'task', 'predictions', 'features')}
        row['outputs'] = {k: old['outputs'][v] for k, v in selected.items()}
        row['metadata'] = {k: old['metadata'][v] for k, v in selected.items() if k != 'A'}
        row['metadata']['G'] = {**row['metadata']['G'], 'logistic_risk': decision}
        row.update(decision=decision, selected_labels=selected, frozen_input=str(path), frozen_input_sha256=sha256_file(path))
        if old['features'] is not None:
            model = gate.cache[character][0]
            save(args.output / 'models' / (old['task']['id']+'.json'), {'model': model.payload(),
                'excluded_character': character, 'training_identities': [[r['writer'], r['character'], r['component_id'], r['proposal_id']]
                    for r in gate.examples if r['character'] != character]})
        audit.update(audit_generated(row, archives[row['writer']], repository))
        for label, frozen_label in selected.items():
            assert row['outputs'][label] == old['outputs'][frozen_label]
        target = args.output / 'generated' / path.name
        save(target, row)
        pending.append(target)
    save(args.output / 'generation_manifest.json', {str(p): sha256_file(p) for p in pending})
    save(args.output / 'integrity_audit.json', dict(audit))
    groups, excluded = {}, []
    for path in pending:
        case_path = folder / 'cases' / path.name
        if not case_path.exists():
            excluded.append(path.name)
            continue
        row, old = read(path), read(case_path)
        for label, frozen_label in row['selected_labels'].items():
            assert row['outputs'][label] == old['outputs'][frozen_label]
        for key in ('metrics', 'stroke_metrics', 'whole_metrics'):
            row[key] = {k: old[key][v] for k, v in row['selected_labels'].items()}
        row['references'] = old['references']
        save(args.output / 'cases' / path.name, row)
        groups.setdefault(row['writer'], []).append(row)
    summaries = {}
    for writer, rows in groups.items():
        summary = {label: {k: mean_present([r['metrics'][label][k] for r in rows]) for k in METRICS} for label in rows[0]['outputs']}
        for label, s in summary.items():
            s.update(changed_characters=[r['task']['character'] for r in rows if r['outputs'][label] != r['outputs']['D']],
                maximum_character_geometry_ratio=max(r['metrics'][label]['mean_distance']/max(r['metrics']['D']['mean_distance'], 1e-12) for r in rows),
                maximum_stroke_local_error_increase=max(p['max_distance']-r['stroke_metrics']['D'][sid]['max_distance'] for r in rows for sid, p in r['stroke_metrics'][label].items()))
            s['passes_gates'] = s['mean_distance'] < summary['D']['mean_distance']-1e-12 and s['terminal_angle_deg'] <= summary['D']['terminal_angle_deg']+.5 and s['maximum_character_geometry_ratio'] <= 1.05+1e-12 and s['maximum_stroke_local_error_increase'] <= .005+1e-12
        summaries[writer] = {'n': len(rows), 'captures': sum(len(r['references']) for r in rows), 'component': summary,
            'whole': {label: {k: mean_present([r['whole_metrics'][label][k] for r in rows]) for k in METRICS} for label in summary}}
    save(args.output / 'summary.json', summaries)
    save(args.output / 'coverage.json', {'generated': len(pending), 'scored': sum(len(r) for r in groups.values()), 'excluded': excluded})
    for writer, s in summaries.items():
        print(writer, {k: v for k, v in s['component']['G'].items()}, flush=True)


if __name__ == '__main__':
    main()
