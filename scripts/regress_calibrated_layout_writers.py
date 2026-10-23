"""Frozen layout rule on existing scx/mjb/wsq cohorts; never fresh validation."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from confirm_contextual_trajectory import split
from experiment_component_trust import glyph_from_dict, mean_present, read
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.calibrated_component_layout import (
    CalibratedComponentLayoutEvidence,
    place_with_calibrated_layout,
)
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.learned_component_layout import place_with_learned_layout, public_layout
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics

METRICS = ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error',
           'endpoint_error', 'hook_length_error', 'length_ratio')
CONTEXT = Path('artifacts/contextual_trajectory_20261007/confirmation_v1')
TERMINAL = Path('artifacts/terminal_selection_20261007/wsq_confirmation_v1')
DEVELOPMENT = Path('artifacts/learned_component_layout_20261007/calibrated_development_v1')


def sanitize_case(row):
    """Allowlist inference inputs. No gold, metrics, or target capture identifiers."""
    task = {k: row['task'][k] for k in ('id', 'character', 'target_stroke_ids')}
    provenance = row['provenance_D'] if 'provenance_D' in row else row['provenance']
    return {'task': task, 'outputs': {k: row['variants'][k] for k in ('A', 'D')},
            'metadata': {'D': {k: provenance[k] for k in ('selected', 'fallback_reason')}}}


def training_sources(archive):
    """Filter the existing per-capture raw archive BEFORE constructing evidence."""
    return {k: s for k, s in archive.items() if split(s.character) == 'train'}


def audit_generated(row, sources, repository):
    graph = repository.get(row['task']['character'])
    ids = row['task']['target_stroke_ids']
    indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
    raw_points = 0
    refs = row['predictions']['learned'].get('reference_sources', [])
    for ref in refs:
        source = sources[ref['sample_id']]
        assert source.character == ref['character'] != graph.character
        assert split(source.character) == 'train' and source.source_sha256 == ref['source_sha256']
    cross = crossing_pairs(curves(glyph_from_dict(row['outputs']['A'])))
    for label, payload in row['outputs'].items():
        glyph = glyph_from_dict(payload)
        assert not invariants(glyph, graph)
        assert not crossing_pairs(curves(glyph))-cross
        if label == 'A':
            continue
        selected = row['metadata'][label]['selected']
        assert (selected or {}).get('candidate') == (row['metadata']['D']['selected'] or {}).get('candidate')
        if selected is None:
            assert payload == row['outputs']['D']
            continue
        candidate = selected['candidate']
        source = sources[candidate['sample_id']]
        assert source.source_sha256 == candidate['source_sha256']
        assert source.character != graph.character and split(source.character) == 'train'
        mapping = {s.standard_stroke_id: s for s in source.strokes}
        t = selected['transform']
        assert t['sx'] == t['sy'] and t['sx'] > 0
        for i, sid in zip(indices, candidate['stroke_ids'], strict=True):
            points, raw = payload['strokes'][i]['points'], mapping[sid]
            np.testing.assert_allclose([(p['x'], p['y']) for p in points],
                np.asarray(raw.points)*t['sx']+[t['tx'], t['ty']], atol=1e-12, rtol=0)
            np.testing.assert_array_equal([p['pressure'] for p in points], raw.pressure)
            np.testing.assert_allclose(np.diff([p['t_ms'] for p in points]), np.diff(raw.t_ms), atol=1e-8, rtol=0)
            raw_points += len(points)
        for i in range(len(glyph.strokes)):
            if i not in indices:
                assert curves(glyph)[i] == curves(glyph_from_dict(row['outputs']['D']))[i]
    assert row['outputs']['off'] == row['outputs']['D']
    return {'outputs': len(row['outputs']), 'source_points': raw_points, 'reference_uses': len(refs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    choice = read(DEVELOPMENT / 'frozen_choice.json')
    assert choice['label'] == 'M_D_1.0' and choice['strength'] == 1.
    assert sha256_file(DEVELOPMENT / 'summary.json') == choice['summary_sha256']
    assert sha256_file(DEVELOPMENT / 'run_protocol.json') == choice['run_protocol_sha256']
    frozen_code = read(DEVELOPMENT / 'run_protocol.json')['code_sha256']
    for p, expected in frozen_code.items():
        assert sha256_file(Path(p)) == expected, p
    context, terminal = read(CONTEXT / 'frozen_plan.json'), read(TERMINAL / 'frozen_plan.json')
    assert sha256_file(DATABASE) == context['structure_sha256'] == terminal['input_sha256'][str(DATABASE)]
    datasets = {}
    for writer, d in context['datasets'].items():
        for key in ('sources', 'train_profile'):
            assert sha256_file(Path(d[key])) == d[key+'_sha256']
        datasets[writer] = {'sources': d['sources'], 'profile': d['train_profile'], 'folder': CONTEXT,
                            'tasks': d['tasks']}
    for key in ('sources', 'profile'):
        assert sha256_file(Path(terminal[key])) == terminal['input_sha256'][terminal[key]]
    datasets['wsq'] = {'sources': terminal['sources'], 'profile': terminal['profile'], 'folder': TERMINAL,
                       'tasks': terminal['tasks']}
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = [CONTEXT / 'frozen_plan.json', TERMINAL / 'frozen_plan.json', DEVELOPMENT / 'frozen_choice.json',
              DEVELOPMENT / 'summary.json', DEVELOPMENT / 'run_protocol.json', DATABASE]
    for d in datasets.values():
        inputs += [Path(d['sources']), Path(d['profile'])]
        inputs += [d['folder'] / 'cases' / (t['id']+'.json') for t in d['tasks']]
    save(args.output / 'run_protocol.json', {'scope': 'observed multiwriter regression only; no retuning',
        'frozen_choice': choice, 'input_sha256': {str(p): sha256_file(p) for p in inputs},
        'code_sha256': {**frozen_code, str(Path(__file__)): sha256_file(Path(__file__)),
                        'scripts/confirm_contextual_trajectory.py': sha256_file(Path('scripts/confirm_contextual_trajectory.py'))},
        'design': 'Fixed A/D outputs and D donor; M public destination at B learned effective strength; author-specific training LOO calibration; all outputs saved before target scoring',
        'cohort_limitation': 'Inherited cohorts used raw eligibility in prior experiments; reference data exist in old files, removed by allowlist before inference',
        'arms': ['A', 'D', 'B', 'M', 'off'],
        'quality_gates': 'same development gates: strictly lower mean geometry, angle <=D+0.5deg, each character geometry <=1.05D, each stroke max error <=D+0.005, same source activation'})
    repository = StructureRepository(DATABASE)
    pending, audits, coverage = [], Counter(), {}
    for writer, d in datasets.items():
        archive = load_profile(Path(d['sources']))
        sources = training_sources(archive.source_trajectories)
        profile = replace(load_profile(Path(d['profile'])), source_trajectories=sources,
                          trajectory_schema=archive.trajectory_schema)
        assert archive.writer_id == profile.writer_id == writer
        del archive
        save(args.output / 'training' / (writer+'.json'), asdict(profile))
        evidence = CalibratedComponentLayoutEvidence(ExemplarIndex(profile, repository))
        calibration = evidence.calibrate()
        assert all(split(c) == 'train' for c in calibration['character_scores'])
        save(args.output / 'calibration' / (writer+'.json'), calibration)
        coverage[writer] = {'training_captures': len(sources), 'training_characters': len({s.character for s in sources.values()}),
            'calibration_characters': calibration['reference_character_count'], 'radius': calibration['radius'],
            'prediction_tiers': Counter(), 'fallbacks': Counter()}
        print(writer, 'calibration', calibration['reference_character_count'], calibration['radius'], flush=True)
        for task in d['tasks']:
            path = d['folder'] / 'cases' / (task['id']+'.json')
            clean = sanitize_case(read(path))
            assert split(clean['task']['character']) == 'test'
            save(args.output / 'inference_inputs' / path.name, clean)
            # All functions below receive only the sanitized record and train-only sources.
            row = read(args.output / 'inference_inputs' / path.name)
            graph = repository.get(row['task']['character'])
            component = next(c for c in graph.components if ordered_ids(graph, c) == row['task']['target_stroke_ids'])
            base, original = [glyph_from_dict(row['outputs'][k]) for k in ('A', 'D')]
            meta = row['metadata']['D']
            predicted = evidence.predict(graph, component)
            center, span, _ = public_layout(graph, component)
            public = {'available': True, 'policy': 'public_normalized_layout_control', 'center': center.tolist(), 'span': span}
            b, bm = place_with_calibrated_layout(base, original, meta, graph, component, sources, predicted, calibration, 1.)
            effective = bm.get('layout_band', {}).get('effective_strength', 0.)
            m, mm = place_with_learned_layout(base, original, meta, graph, component, sources, public, effective)
            off, offm = place_with_calibrated_layout(base, original, meta, graph, component, sources, predicted, calibration, 0.)
            row['outputs'].update({k: asdict(v) for k, v in [('B', b), ('M', m), ('off', off)]})
            row['metadata'].update(B=bm, M=mm, off=offm)
            row.update(writer=writer, predictions={'learned': predicted, 'public': public})
            audits.update(audit_generated(row, sources, repository))
            save(args.output / 'generated' / path.name, row)
            pending.append((path, args.output / 'generated' / path.name))
            coverage[writer]['prediction_tiers'][predicted.get('tier') if predicted.get('available') else 'unavailable'] += 1
            reason = mm.get('learned_layout', {}).get('fallback_reason')
            if row['outputs']['M'] == row['outputs']['D']:
                reason = reason or bm.get('layout_band', {}).get('reason', 'unchanged')
                coverage[writer]['fallbacks'][reason] += 1
    # The complete three-writer generation boundary is closed before any gold scoring.
    save(args.output / 'generation_manifest.json', {str(p): sha256_file(p) for _, p in pending})
    save(args.output / 'integrity_audit.json', dict(audits))
    save(args.output / 'coverage.json', coverage)
    groups = {w: [] for w in datasets}
    for old_path, new_path in pending:
        row, old = read(new_path), read(old_path)
        reference = old['reference']
        indices = [i for i, s in enumerate(row['outputs']['A']['strokes']) if s['standard_stroke_id'] in row['task']['target_stroke_ids']]
        cache, metrics, whole, stroke_scores = {}, {}, {}, {}
        for label, payload in row['outputs'].items():
            xy = curves(glyph_from_dict(payload))
            key = tuple(tuple(tuple(p) for p in s) for s in xy)
            if key not in cache:
                cache[key] = [stroke_metrics(p, r) for p, r in zip(xy, reference, strict=True)]
            scores = cache[key]
            metrics[label] = {k: mean_present([scores[i][k] for i in indices]) for k in METRICS}
            whole[label] = {k: mean_present([s[k] for s in scores]) for k in METRICS}
            stroke_scores[label] = {row['outputs']['A']['strokes'][i]['standard_stroke_id']: scores[i] for i in indices}
        row.update(reference=reference, reference_sha256=old.get('reference_sha256', old.get('reference_source_sha256')),
                   metrics=metrics, whole_metrics=whole, stroke_metrics=stroke_scores)
        save(args.output / 'cases' / new_path.name, row)
        groups[row['writer']].append(row)
        print('scored', row['writer'], len(groups[row['writer']]), flush=True)
    summaries = {}
    for writer, rows in groups.items():
        summary = {label: {k: mean_present([r['metrics'][label][k] for r in rows]) for k in METRICS}
                   for label in ('A', 'D', 'B', 'M')}
        for label, result in summary.items():
            result.update(changed_characters=[r['task']['character'] for r in rows if r['outputs'][label] != r['outputs']['D']],
                maximum_character_geometry_ratio=max(r['metrics'][label]['mean_distance']/max(r['metrics']['D']['mean_distance'], 1e-12) for r in rows),
                maximum_stroke_local_error_increase=max(s['max_distance']-r['stroke_metrics']['D'][sid]['max_distance'] for r in rows for sid, s in r['stroke_metrics'][label].items()))
            result['passes_prior_quality_gates'] = (result['mean_distance'] < summary['D']['mean_distance']-1e-12 and
                result['terminal_angle_deg'] <= summary['D']['terminal_angle_deg']+.5 and
                result['maximum_character_geometry_ratio'] <= 1.05+1e-12 and result['maximum_stroke_local_error_increase'] <= .005+1e-12)
        summaries[writer] = {'n': len(rows), 'component': summary,
            'whole': {label: {k: mean_present([r['whole_metrics'][label][k] for r in rows]) for k in METRICS} for label in summary}}
    save(args.output / 'summary.json', summaries)
    print('complete', {w: {'n': s['n'], 'D': s['component']['D']['mean_distance'], 'M': s['component']['M']['mean_distance'],
                          'changed': s['component']['M']['changed_characters']} for w, s in summaries.items()}, flush=True)


if __name__ == '__main__':
    main()
