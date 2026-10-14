"""Bounded, opt-in coverage ablations; immutable inputs and independently saved arms."""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import numpy as np
from generate_v61_library import (
    CORRECTIONS,
    DB,
    REVIEW,
    SOURCES,
    WRITERS,
    digest,
    dump,
    encoded,
    generate,
)
from run_v61_admission_exp import stroke_payload
from run_v61_exp import check_integrity

from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import (
    angle_degrees,
    at_distance,
    crossing_pairs,
    curve_error,
    invariants,
)
from inkstruct.v61_candidate_expansion import (
    MAX_AXIS_RATIO,
    CandidateExpansionGenerator,
    ExpansionPolicy,
)
from inkstruct.v61_contacts import contact_pairs
from inkstruct.v61_exp import curves

ARMS = {
    'A': ExpansionPolicy(),
    'B_context': ExpansionPolicy(context=True),
    'C_hierarchy': ExpansionPolicy(hierarchy=True),
    'D_nested': ExpansionPolicy(nested=True),
    'E_whole': ExpansionPolicy(whole_target=True),
    'F_combined': ExpansionPolicy(context=True, hierarchy=True, nested=True, whole_target=True),
    'G_axes': ExpansionPolicy(context=True, hierarchy=True, nested=True, whole_target=True, anisotropic=True),
}
CHARS = '而相儒荡叵铜伯饿想加田睡印白雨把闻媷'
LIBRARY = Path('artifacts/v61_full_library_20261014/run_v1')


def evaluate(engine, ctx, glyph, plan, baseline):
    xy, before = curves(glyph), curves(baseline)
    ownership = {i: p.component_id for p in plan.values() for i in p.indices}
    is_external = lambda a, b: ownership.get(a, f'ref{a}') != ownership.get(b, f'ref{b}')
    cross = sorted((a, b) for a, b in crossing_pairs(xy) - crossing_pairs(before) if is_external(a, b))
    contacts = {str(width): sorted((a, b) for a, b in contact_pairs(xy, width) - contact_pairs(before, width)
                                 if is_external(a, b)) for width in (.014, .028, .05)}
    errors = invariants(glyph, ctx.graph)
    degenerate = [i for i, s in enumerate(xy) if path_length(s) < .003]
    assert not errors and not degenerate
    deformation = []
    for p in plan.values():
        angles, lengths = [], []
        for src, dst in zip(engine.source(p), engine.placed(p), strict=True):
            a, b = src.points, dst
            la, lb = path_length(a), path_length(b)
            angles.append(angle_degrees(np.asarray(a[-1]) - at_distance(a, .9 * la),
                                        np.asarray(b[-1]) - at_distance(b, .9 * lb)))
            lengths.append(lb / max(la, 1e-12))
        deformation.append({'component_id': p.component_id, 'axis_ratio': max(p.transform.sx, p.transform.sy) / min(p.transform.sx, p.transform.sy),
                            'terminal_direction_changes_degrees': angles, 'arc_length_ratios': lengths})
    return {'integrity': check_integrity(engine, ctx, glyph, plan), 'protocol': errors,
            'degenerate': degenerate, 'new_cross_component_crossings': cross,
            'new_cross_component_contacts': contacts, 'deformation': deformation,
            'unchanged': stroke_payload(asdict(glyph)) == stroke_payload(asdict(baseline))}


def run(out, writers, chars):
    out.mkdir(parents=True, exist_ok=False)
    inputs = [DB, *CORRECTIONS, REVIEW, *(SOURCES[w] for w in writers)]
    code = list(Path('src/inkstruct').glob('*.py')) + [Path(__file__), Path('scripts/generate_v61_library.py')]
    hashes = {str(p): digest(p) for p in inputs}
    protocol = {'name': 'v6.1 exp candidate expansion', 'git_head': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
                'inputs': hashes, 'code': {str(p): digest(p) for p in code},
                'arms': {k: asdict(v) for k,v in ARMS.items()}, 'axis_ratio_limit': MAX_AXIS_RATIO,
                'cohort': chars, 'writers': writers, 'split': 'development/regression; no fresh holdout claim',
                'target_capture_used_for_selection': False, 'production_changed': False,
                'frozen_before_run': True, 'axis_arm': 'F fixed; only fill remaining gaps, maximum axis ratio 1.35, no tuning to originals',
                'confound': 'expanded pools are reranked with ordered-reference proof; F permits replacing child donors only for strictly greater source coverage; record replacements',
                'gates': 'identity/variant/count and mapping fixed; context labels relaxed only in B/F/G; G separately replaces raw reference-shape gates with bounded ordered-axis correspondence'}
    dump(out/'protocol.json', protocol)
    base = StructureRepository(DB)
    target = CorrectedStructureRepository(base, *CORRECTIONS)
    summary = []
    for writer in writers:
        profile = load_profile(SOURCES[writer])
        engine = CandidateExpansionGenerator(profile, base, target, variant_checks=False)
        folder = out / writer
        folder.mkdir()
        for char in chars:
            ctx, baseline, original_plan, _ = generate(engine, char, writer, json.loads(REVIEW.read_text()))
            saved = json.loads(gzip.decompress((LIBRARY / writer / f'{ord(char):04X}.json.gz').read_bytes()))
            assert stroke_payload(asdict(baseline)) == stroke_payload(saved['glyph']), (writer,char,'baseline drift')
            record = {'writer': writer, 'character': char, 'baseline_exact': True, 'arms': {}}
            fctx, fp = ctx, original_plan
            for arm, policy in ARMS.items():
                start_ctx, start_plan = (fctx, fp) if arm == 'G_axes' else (ctx, original_plan)
                probe, glyph, plan, log = engine.extend(start_ctx, start_plan, policy)
                checks = evaluate(engine, probe, glyph, plan, baseline)
                record['arms'][arm] = {'glyph': asdict(glyph), 'checks': checks, 'provenance': [asdict(p) for p in plan.values()], 'log': log}
                if arm == 'F_combined':
                    _fctx, _fp = probe, plan
            # Evaluation-only original samples are opened AFTER every arm freezes.
            originals = [s for s in profile.source_trajectories.values() if s.character == char]
            record['evaluation_originals'] = [{'sample_id': s.sample_id, 'curves': [t.points for t in s.strokes]} for s in originals]
            for arm, result in record['arms'].items():
                evaluations = []
                xy = [[(p['x'], p['y']) for p in s['points']] for s in result['glyph']['strokes']]
                for original in originals:
                    if len(original.strokes) != len(xy):
                        continue
                    evaluations.append({'sample_id': original.sample_id,
                        'mean_symmetric_polyline_distance': float(np.mean([curve_error(a,b.points)[0] for a,b in zip(xy, original.strokes, strict=True)]))})
                result['original_evaluation'] = evaluations
            path = folder/f'{ord(char):04X}.json.gz'
            path.write_bytes(gzip.compress(encoded(record), mtime=0))
            row = {'writer': writer, 'character': char, 'strokes': len(baseline.strokes), 'arms': {k:v['checks'] for k,v in record['arms'].items()}}
            summary.append(row)
            print(writer, char, {k:v['integrity']['source_strokes'] for k,v in row['arms'].items()}, flush=True)
        dump(folder/'source_view_validation.json', engine.view_log)
    assert hashes == {str(p): digest(p) for p in inputs}, 'input changed during experiment'
    dump(out/'summary.json', summary)
    totals = {arm: {'source_strokes': sum(r['arms'][arm]['integrity']['source_strokes'] for r in summary),
                   'changed_cases': sum(not r['arms'][arm]['unchanged'] for r in summary),
                   'new_external_crossing_cases': sum(bool(r['arms'][arm]['new_cross_component_crossings']) for r in summary),
                   'new_contact_cases': {}}
              for arm in ARMS}
    for arm, total in totals.items():
        total['new_contact_cases'] = {w:sum(bool(r['arms'][arm]['new_cross_component_contacts'][w]) for r in summary) for w in ('0.014','0.028','0.05')}
    dump(out/'totals.json', {'cases':len(summary), 'total_strokes':sum(r['strokes'] for r in summary), 'arms':totals})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--writers', nargs='+', default=WRITERS)
    p.add_argument('--chars', default=CHARS)
    args = p.parse_args()
    run(args.output, args.writers, args.chars)
