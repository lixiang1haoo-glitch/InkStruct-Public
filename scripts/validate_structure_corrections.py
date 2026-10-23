"""Frozen A/B/C structure experiment; no production defaults or old files change."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from experiment_component_trust import glyph_from_dict, mean_present
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import path_length
from inkstruct.profile import build_profile, load_profile
from inkstruct.samples import sha256_file
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics

GRAPHICS = Path('third_party/makemeahanzi/graphics.txt')
DICTIONARY = Path('third_party/makemeahanzi/dictionary.txt')
CONFIG = Path('configs/structure_overrides/unclipped_reference_v1.json')
REGRESSION = Path('artifacts/layout_multiwriter_20261007/regression_v2')
INDICES = {w: Path('artifacts/contextual_trajectory_20261007/confirmation_v1')/(w+'_train_index.jsonl') for w in ('scx', 'mjb')}
INDICES['wsq'] = Path('artifacts/terminal_selection_20261007/wsq_confirmation_v1/wsq_train_index.jsonl')
ARCHIVES = {w: Path('profiles/source_v1_20261007')/w/'profile.json' for w in ('scx', 'mjb')}
ARCHIVES['wsq'] = Path('profiles/terminal_20261007/source/wsq/profile.json')
METRICS = ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error', 'endpoint_error', 'hook_length_error')


def read(path):
    return json.loads(path.read_text())


def repositories():
    base = StructureRepository(DATABASE)
    return base, CorrectedStructureRepository(base, GRAPHICS, DICTIONARY, CONFIG)


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    base, corrected = repositories()
    files = [DATABASE, GRAPHICS, DICTIONARY, CONFIG, *INDICES.values(), *ARCHIVES.values()]
    files += [REGRESSION/'training'/(w+'.json') for w in INDICES]
    files += sorted((REGRESSION/'cases').glob('*.json'))
    save(out/'protocol.json', {'arms': {'A': 'original reference + fixed existing profile', 'B': 'corrected reference + exactly same profile', 'C': 'corrected reference + rebuilt same-index profile'},
        'parameters': {'component_conditioning': 'adaptive', 'component_strength': 1., 'seed': 0, 'randomness': 'none; deterministic generator'},
        'scope': 'All old character cohorts are regression; 盼 sparse-strip repair is development. No fresh held-out quality claim. Correction rules frozen before generation; no parameter tuning on validation outputs.',
        'input_sha256': {str(p): sha256_file(p) for p in files},
        'code_sha256': {str(p): sha256_file(p) for p in [Path(__file__), *Path('src/inkstruct').glob('*.py')]},
        'correction_identity': corrected.identity})
    counts, failed, unchanged, affected = Counter(), [], [], []
    for i, c in enumerate(base.characters()):
        old = base.get(c)
        try:
            new = corrected.get(c)
        except ValueError as e:
            failed.append({'character': c, 'reason': str(e)})
            continue
        assert [(s.stroke_id, s.order, s.component_path) for s in old.strokes] == [(s.stroke_id, s.order, s.component_path) for s in new.strokes]
        changes = corrected.events[c]['changes']
        counts.update(e['defect'] for e in changes)
        counts['changed_strokes'] += sum(a.median != b.median for a, b in zip(old.strokes, new.strokes, strict=True))
        (affected if changes else unchanged).append(c)
        if (i+1)%1000 == 0:
            print('reference validated', i+1, flush=True)
    save(out/'reference_validation.json', {'counts': dict(counts), 'affected_characters': affected, 'unchanged_characters': unchanged, 'failed': failed})
    save(out/'correction_events.json', corrected.events)
    control = sorted(unchanged, key=lambda c: hashlib.sha256(('structure-controls-v1:'+c).encode()).hexdigest())[:32]
    tasks = []
    for w, index_path in INDICES.items():
        old = load_profile(REGRESSION/'training'/(w+'.json'))
        assert sha256_file(index_path) == old.source_index_sha256
        print('rebuilding', w, flush=True)
        new, path = build_profile(w, index_path, corrected, out/'profiles_C', retain_source_trajectories=True)
        save(out/('profile_C_'+w+'.json'), {'path': str(path), 'sha256': sha256_file(path), 'source_index_sha256': new.source_index_sha256})
        # Retained raw points/pressure/time must not be changed by reference repair.
        old_by_id = old.source_trajectories
        matched, changed_mapping = 0, 0
        for key, sample in new.source_trajectories.items():
            if key not in old_by_id:
                continue
            prior = old_by_id[key]
            a = {s.user_order: asdict(s) for s in prior.strokes}
            b = {s.user_order: asdict(s) for s in sample.strokes}
            assert set(a) == set(b)
            for order, stroke in a.items():
                changed_mapping += stroke.pop('standard_stroke_id') != b[order].pop('standard_stroke_id')
                assert json.dumps({k: stroke[k] for k in ('points', 'pressure', 't_ms', 'arc_parameters')}, sort_keys=True) == json.dumps({k: b[order][k] for k in ('points', 'pressure', 't_ms', 'arc_parameters')}, sort_keys=True), (w, key, order)
            matched += 1
        save(out/('capture_preservation_'+w+'.json'), {'matched_unchanged_captures': matched, 'changed_standard_assignments': changed_mapping,
            'old_count': len(old_by_id), 'new_count': len(new.source_trajectories), 'excluded_samples_C': new.excluded_samples})
        seen = set()
        for p in sorted((REGRESSION/'cases').glob('*.json')):
            r = read(p)
            if r['writer'] == w:
                c = r['task']['character']
                if c not in seen:
                    tasks.append({'writer': w, 'character': c, 'cohort': 'observed_regression', 'old_case': str(p)})
                    seen.add(c)
        for c in '黧瀝盼':
            if c not in seen:
                tasks.append({'writer': w, 'character': c, 'cohort': 'repair_development' if c == '盼' else 'known_source_regression'})
                seen.add(c)
        for c in control:
            if c not in seen:
                tasks.append({'writer': w, 'character': c, 'cohort': 'unmodified_protection'})
                seen.add(c)
    save(out/'tasks.json', tasks)
    print('prepared', len(tasks), flush=True)


def generate(out):
    protocol = read(out/'protocol.json')
    for p, h in {**protocol['input_sha256'], **protocol['code_sha256']}.items():
        assert sha256_file(Path(p)) == h, p
    base, corrected = repositories()
    generators = {}
    for w in INDICES:
        old = load_profile(REGRESSION/'training'/(w+'.json'))
        new = load_profile(Path(read(out/('profile_C_'+w+'.json'))['path']))
        generators[w] = {label: DeterministicGenerator(profile, repo.metadata()['source_version'], component_conditioning='adaptive', component_strength=1.)
            for label, profile, repo in [('A', old, base), ('B', old, corrected), ('C', new, corrected)]}
    manifest = {}
    for i, task in enumerate(read(out/'tasks.json')):
        c, w = task['character'], task['writer']
        original, graph = base.get(c), corrected.get(c)
        outputs = {label: gen.generate(original if label == 'A' else graph) for label, gen in generators[w].items()}
        checks = {label: {'invariants': invariants(g, graph), 'crossings': sorted(crossing_pairs(curves(g))),
            'degenerate_strokes': [s.standard_stroke_id for s in g.strokes if path_length([(p.x, p.y) for p in s.points]) <= 1e-6]} for label, g in outputs.items()}
        row = {'task': task, 'events': corrected.events[c], 'outputs': {k: asdict(v) for k, v in outputs.items()}, 'checks': checks}
        path = out/'generated'/f'{w}-{ord(c):04X}.json'
        save(path, row)
        manifest[str(path)] = sha256_file(path)
        if (i+1)%30 == 0:
            print('generated', i+1, flush=True)
    save(out/'generation_manifest.json', manifest)


def evaluate(out):
    manifest = read(out/'generation_manifest.json')
    archives = {w: load_profile(p).source_trajectories for w, p in ARCHIVES.items()}
    gold = {w: {s.character: s for s in samples.values()} for w, samples in archives.items()}
    summaries, rows = {}, []
    for i, (p, h) in enumerate(manifest.items()):
        assert sha256_file(Path(p)) == h
        row = read(Path(p)); task = row['task']; w, c = task['writer'], task['character']
        glyphs = {k: glyph_from_dict(v) for k, v in row['outputs'].items()}
        ref = gold[w].get(c)
        ids = [s.standard_stroke_id for s in glyphs['A'].strokes]
        if ref is not None and sorted(s.standard_stroke_id for s in ref.strokes) == sorted(ids):
            refs = {s.standard_stroke_id: s.points for s in ref.strokes}
            row['reference'] = [refs[sid] for sid in ids]
            row['reference_identity'] = {'sample_id': ref.sample_id, 'source_sha256': ref.source_sha256, 'archive': str(ARCHIVES[w]), 'scope': 'scoring only; A/B/C generation already sealed'}
            row['stroke_metrics'] = {k: {sid: stroke_metrics(points, refs[sid]) for sid, points in zip(ids, curves(g), strict=True)} for k, g in glyphs.items()}
            row['metrics'] = {k: {m: mean_present([s[m] for s in strokes.values()]) for m in METRICS} for k, strokes in row['stroke_metrics'].items()}
        else:
            row['reference'] = None
        a = row['checks']['A']['crossings']
        row['deltas'] = {k: {'new_crossings': [p for p in row['checks'][k]['crossings'] if p not in a],
            'geometry_changed': curves(glyphs[k]) != curves(glyphs['A'])} for k in ('B', 'C')}
        save(out/'evaluated'/Path(p).name, row)
        rows.append(row)
        if (i+1)%30 == 0:
            print('evaluated', i+1, flush=True)
    for w in INDICES:
        selected = [r for r in rows if r['task']['writer'] == w]
        summary = {'generated': len(selected), 'scored': sum(r['reference'] is not None for r in selected)}
        for group, subset in [('all', selected), ('affected', [r for r in selected if r['events']['changes']]), ('unmodified', [r for r in selected if not r['events']['changes']]), ('regression_gold', [r for r in selected if r['task']['cohort'] == 'observed_regression' and r['reference'] is not None])]:
            summary[group] = {'n': len(subset), 'scored': sum(r['reference'] is not None for r in subset)}
            for label in ('A', 'B', 'C'):
                scored = [r for r in subset if r['reference'] is not None]
                summary[group][label] = {m: mean_present([r['metrics'][label][m] for r in scored]) for m in METRICS}
                summary[group][label].update(invariant_failures=sum(bool(r['checks'][label]['invariants']) for r in subset),
                    degeneracies=sum(len(r['checks'][label]['degenerate_strokes']) for r in subset),
                    new_crossing_characters=sum(bool(r.get('deltas', {}).get(label, {}).get('new_crossings')) for r in subset),
                    changed_characters=sum(r.get('deltas', {}).get(label, {}).get('geometry_changed', False) for r in subset))
        summaries[w] = summary
    save(out/'summary.json', summaries)
    # Prove old data stayed unchanged after both profile builds and generation.
    integrity = {p: sha256_file(Path(p)) == h for p, h in read(out/'protocol.json')['input_sha256'].items()}
    assert all(integrity.values())
    save(out/'input_preservation.json', integrity)
    print(json.dumps(summaries, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=['prepare', 'generate', 'evaluate'], required=True)
    args = parser.parse_args()
    {'prepare': prepare, 'generate': generate, 'evaluate': evaluate}[args.stage](args.output)
