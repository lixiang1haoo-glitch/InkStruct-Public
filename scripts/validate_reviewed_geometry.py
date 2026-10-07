"""Validate optional reviewed repairs on known cases, a third profile and unchanged controls."""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from run_raw_trajectory_experiment import rank, save

from inkstruct.generate import generate_run
from inkstruct.geometry import path_length
from inkstruct.outline_median import flatten_outline, propose_strip_median
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs


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
    graphics = Path('third_party/makemeahanzi/graphics.txt')
    dictionary = Path('third_party/makemeahanzi/dictionary.txt')
    config_path = Path('configs/geometry_repairs/reviewed_v1.json')
    repository = StructureRepository(database)
    targets = list('丢侈黧瀝')
    controls = sorted((c for c in repository.characters() if c not in targets), key=rank)[:64]
    profiles = {w: Path(f'profiles/{w}/profile.json') for w in ('scx', 'mjb')}
    profiles['wsq'] = Path('profiles/terminal_20261007/source/wsq/profile.json')
    sources = {w: Path(f'profiles/source_v1_20261007/{w}/profile.json') for w in ('scx', 'mjb')}
    inputs = [database, graphics, dictionary, config_path, *profiles.values(), *sources.values()]
    plan = {'targets': targets, 'controls': controls, 'profiles': {k: str(v) for k, v in profiles.items()},
        'input_sha256': {str(p): sha256_file(p) for p in inputs},
        'code_sha256': {str(p): sha256_file(p) for p in [Path(__file__), *[Path('src/inkstruct')/f'{n}.py'
            for n in ('reviewed_geometry', 'generate', 'outline_median', 'topology_repair', 'cli', 'desktop')]]},
        'scope': 'geometry/source correctness and unchanged-output regression; no target handwriting or preference claims'}
    save(args.output/'frozen_plan.json', plan)
    source_audit = []
    for line in graphics.open():
        record = json.loads(line)
        for i, median in enumerate(record['medians']):
            if path_length(median) >= 10:
                continue
            try:
                proposed, report = propose_strip_median(record['strokes'][i], median)
                row = {'character': record['character'], 'stroke_id': f's{i+1}', 'proposed': proposed,
                    'outline': flatten_outline(record['strokes'][i]).tolist(), 'original_median': median, 'report': report}
            except ValueError as error:
                row = {'character': record['character'], 'stroke_id': f's{i+1}', 'rejection': str(error)}
            source_audit.append(row)
    save(args.output/'public_source_audit.json', source_audit)
    summaries = {}
    for writer, profile in profiles.items():
        runs, elapsed = {}, {}
        for label, active in [('A', False), ('R', True)]:
            start = time.perf_counter()
            manifest, runs[label] = generate_run(writer, targets+controls, repository, profile,
                output_root=args.output/'runs', run_id=label, png=False, reviewed_geometry=active)
            assert not manifest['failed'], manifest['failed']
            elapsed[label] = time.perf_counter()-start
            print(writer, label, manifest['completed_count'], flush=True)
        before = {p: sha256_file(p) for p in (runs['R']/'trajectories').glob('*.json')}
        generate_run(writer, targets+controls, repository, profile, output_root=args.output/'runs', run_id='R', png=False, reviewed_geometry=True)
        assert all(sha256_file(p) == digest for p, digest in before.items())
        manifest_before = (runs['R']/'manifest.json').read_bytes()
        try:
            generate_run(writer, targets+controls, repository, profile, output_root=args.output/'runs', run_id='R', png=False)
        except ValueError as error:
            assert 'identity' in str(error)
        else:
            raise AssertionError('changed repair option reused old run')
        assert manifest_before == (runs['R']/'manifest.json').read_bytes()
        writer_rows = []
        for char in targets+controls:
            old = read(runs['A']/'trajectories'/f'U+{ord(char):04X}.json')
            new = read(runs['R']/'trajectories'/f'U+{ord(char):04X}.json')
            report = new.pop('geometry_repairs')
            initial, final = crossing_pairs(curves(old)), crossing_pairs(curves(new))
            assert not final-initial
            changed = report['changed_geometry_ids']
            if not changed:
                assert new == old
            else:
                for left, right in zip(old['strokes'], new['strokes'], strict=True):
                    if left['standard_stroke_id'] not in changed:
                        assert [(p['x'], p['y'], p['pressure']) for p in left['points']] == [(p['x'], p['y'], p['pressure']) for p in right['points']]
                assert set(changed) <= ({'s1'} if char == '黧' else {'s6'} if char == '瀝' else {'s1', 's2', 's6', 's7'})
            if char in controls:
                assert not changed
            else:
                graph = repository.get(char)
                row = {'writer': writer, 'character': char, 'before': old, 'after': new, 'repair': report,
                    'standard': asdict(graph), 'removed_crossings': sorted(initial-final),
                    'before_lengths': [path_length(p) for p in curves(old)], 'after_lengths': [path_length(p) for p in curves(new)]}
                save(args.output/'cases'/f'{writer}-U+{ord(char):04X}.json', row)
                writer_rows.append({k: row[k] for k in ('character', 'repair', 'removed_crossings', 'before_lengths', 'after_lengths')})
        summaries[writer] = {'targets': writer_rows, 'unchanged_controls': len(controls), 'resume_identical': True,
                             'identity_change_rejected': True, 'batch_seconds': elapsed}
    # Combined retained-source path: protect observed glyphs and compare remaining
    # raw source strokes with/without repairs; repairs may only touch generated strokes.
    for writer in ('scx', 'mjb'):
        combo = {}
        chars = list('岛尴丢侈黧瀝')
        for label, active in [('source_off', False), ('source_repaired', True)]:
            result, combo[label] = generate_run(writer, chars, repository, profiles[writer],
                output_root=args.output/'runs', run_id=label, png=False, trajectory_mode='source-raw',
                source_profile_path=sources[writer], source_observed=True, source_nested_views=True,
                reviewed_geometry=active)
            assert not result['failed']
        checked = 0
        for char in chars:
            old = read(combo['source_off']/'trajectories'/f'U+{ord(char):04X}.json')
            new = read(combo['source_repaired']/'trajectories'/f'U+{ord(char):04X}.json')
            for a, b in zip(old['strokes'], new['strokes'], strict=True):
                if a['style_source'].startswith(('source-', 'observed-')):
                    assert [(p['x'], p['y'], p['pressure']) for p in a['points']] == [(p['x'], p['y'], p['pressure']) for p in b['points']]
                    checked += 1
            if char in '岛尴':
                assert not new['geometry_repairs']['applied']
        summaries[writer]['protected_captured_strokes'] = checked
    for section in ('input_sha256', 'code_sha256'):
        for path, expected in plan[section].items():
            assert sha256_file(Path(path)) == expected, path
    save(args.output/'summary.json', summaries)
    print(json.dumps({w: {k: v for k, v in s.items() if k != 'targets'} for w, s in summaries.items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
