"""Diagnostic counterfactuals for fallback causes; no production admission edits.

A role/index bridge is tested only after unchanged identity/count, reliable full
mapping and the existing ordered-reference thresholds. All geometry guards are
then reused. Passing is not human style acceptance.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from audit_v61_library_fallbacks import LIBRARY, identity, source_inventory
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

from inkstruct.contextual_trajectory import anchors, fit_shared_similarity
from inkstruct.exemplar_index import ordered_ids, reference_compatibility
from inkstruct.fast_placement import choose_component_fast
from inkstruct.geometry import bbox
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import SharedTransform
from inkstruct.v61_admission_exp import AdmissionProbeGenerator
from inkstruct.v61_exp import Placement


def correspondence(source, sn, target, tn):
    if identity(sn) != identity(tn) or min(sn.confidence, tn.confidence) < .8:
        raise ValueError('identity/count or component mapping confidence')
    sm = {s.stroke_id: s for s in source.strokes}
    tm = {s.stroke_id: s for s in target.strokes}
    x = [sm[k].median for k in ordered_ids(source, sn)]
    y = [tm[k].median for k in ordered_ids(target, tn)]
    fit = fit_shared_similarity(x, y)
    box = bbox([p for s in y for p in s])
    span = max(box[2] - box[0], box[3] - box[1], 1e-9)
    errors = np.linalg.norm(anchors([fit.apply(s) for s in x]) - anchors(y), axis=1) / span
    shape, aspect = reference_compatibility(target, tn, source, sn)
    evidence = {'mean_error': float(errors.mean()), 'max_error': float(errors.max()),
                'shape': shape, 'log_aspect': aspect}
    if errors.mean() > .08 or errors.max() > .22 or shape > .18 or aspect > .7:
        raise ValueError('ordered reference correspondence: ' + json.dumps(evidence))
    return evidence


def run(out, audit):
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'protocol.json', {'library': str(LIBRARY), 'audit': str(audit),
        'script_sha256': digest(Path(__file__)), 'audit_code_sha256': digest(Path('scripts/audit_v61_library_fallbacks.py')), 'target_originals_used': False,
        'diagnostic_only': True, 'production_changed': False,
        'bridge_only_change': 'allow existing complete component in another context or target whole-root; preserve identity/count and ordered-reference thresholds',
        'tail_only_change': 'consider same frozen eligible pool beyond first 16; all mappings/placement guards unchanged',
        'source_archives': {str(p): digest(p) for p in SOURCES.values()}})
    base = StructureRepository(DB)
    target = CorrectedStructureRepository(base, *CORRECTIONS)
    results = []
    for writer in WRITERS:
        profile = load_profile(SOURCES[writer])
        engine = AdmissionProbeGenerator(profile, base, target)
        inv = source_inventory(profile, engine.v6.index)
        rows = json.loads((audit / f'{writer}.json').read_text())
        # Bounded, already-observed/common diagnostic cases, not a held-out trial.
        wanted = set('架杏呆查案桌想性忙怒忠念意忘把招加叫和哭响中知古看睡青清问闻思苗界墨原')
        tasks = [(r['character'], r['component_id'], 'context_bridge') for r in rows
                 if r['character'] in wanted and r['reason'] == 'context_or_index_scope_restriction']
        if writer == 'user_001':
            tasks += [(c, 'c_root', 'whole_root_target') for c in '田口日目木我同而白雨']
        tasks += [(r['character'], r['component_id'], 'top16_tail') for r in rows if r['eligible_before_top16'] > 16]
        for char, cid, mode in tasks:
            ctx, current, plan, _ = generate(engine, char, writer, json.loads(REVIEW.read_text()))
            saved = json.loads(gzip.decompress((LIBRARY / writer / f'{ord(char):04X}.json.gz').read_bytes()))
            assert stroke_payload(asdict(current)) == stroke_payload(saved['glyph'])
            node = next((n for n in ctx.graph.components if n.component_id == cid), None)
            if node is None:
                continue
            ids = tuple(ordered_ids(ctx.graph, node))
            if any(set(p.ids) & set(ids) for p in plan.values()) and mode != 'whole_root_target':
                continue
            # Whole-target proposal replaces the whole plan, never mixes source
            # strokes with differently placed pieces from the same target.
            start_plan = {} if mode == 'whole_root_target' else plan
            entries = [e for e in inv.get(identity(node), []) if e['character'] != char and not e['mapping_errors']]
            eligible = engine.v6.index.candidates(ctx.graph, node) if mode == 'top16_tail' else []
            tail = {(e['sample_id'], e['component_id']): rank for rank, e in enumerate(eligible[16:], 17)}
            if mode == 'top16_tail':
                entries = [e for e in entries if (e['sample_id'], e['component_id']) in tail]
            proposals, rejects = [], []
            for entry in entries:
                source = engine.v6.index.graph(entry['character'])
                sn = next(n for n in source.components if n.component_id == entry['component_id'])
                try:
                    proof = correspondence(source, sn, ctx.graph, node) if mode != 'top16_tail' else {'same_original_eligible_pool': True, 'original_rank': tail[(entry['sample_id'], entry['component_id'])]}
                except ValueError as exc:
                    rejects.append({'source': entry, 'reason': str(exc)})
                    continue
                shape, aspect = reference_compatibility(ctx.graph, node, source, sn)
                q = {k: entry[k] for k in ('character', 'sample_id', 'source_sha256', 'component_id', 'stroke_ids')}
                q.update(confidence=entry['mean_confidence'], standard_shape_error=shape,
                         standard_log_aspect_error=aspect, score=shape + .1 * aspect + .03 * (1 - entry['mean_confidence']))
                _, diag = choose_component_fast(engine.emit(ctx, start_plan), ctx.graph, ids, [q], profile.source_trajectories)
                trial = diag['candidates'][0]
                if 'transform' not in trial:
                    rejects.append({'source': entry, 'reason': 'no valid isotropic fit'})
                    continue
                p = Placement(cid, ids, tuple(i for i, s in enumerate(ctx.graph.strokes) if s.stroke_id in ids),
                              q, SharedTransform(**trial['transform']), trial['score'])
                proposals.append((p, proof))
            trials, accepted, display = [], None, None
            for p, proof in sorted(proposals, key=lambda item: (item[0].base_score, item[0].candidate['sample_id'])):
                probe_ctx = copy.copy(ctx)
                probe_ctx.pools = {**ctx.pools, cid: [*ctx.pools.get(cid, []), p]}
                next_plan, diag = engine.attempt(probe_ctx, start_plan, p, source_aware=True)
                trial_glyph = engine.emit(probe_ctx, {**start_plan, cid: p})
                trials.append({'source': p.candidate, 'proof': proof, 'diagnostic': diag})
                if display is None:
                    display = (p, trial_glyph, diag)
                if diag['accepted']:
                    integrity = check_integrity(engine, probe_ctx, trial_glyph, next_plan)
                    accepted = {'proposal': asdict(p), 'proof': proof, 'integrity': integrity}
                    display = (p, trial_glyph, diag)
                    break
            result = {'writer': writer, 'character': char, 'component_id': cid, 'canonical': node.canonical,
                      'mode': mode, 'candidate_count': len(entries), 'correspondence_rejections': rejects,
                      'trials': trials, 'accepted': accepted, 'baseline_exact': True,
                      'current_source_strokes': saved['checks']['source_integrity']['source_strokes'],
                      'target_strokes': len(ids)}
            if display:
                p, trial_glyph, diag = display
                result.update(current_glyph=asdict(current), trial_glyph=asdict(trial_glyph),
                              source_curves=[s.points for s in engine.source(p)],
                              displayed_source=p.candidate, displayed_diagnostic=diag)
            path = out / f'{writer}-{ord(char):04X}-{cid}.json.gz'
            path.write_bytes(gzip.compress(encoded(result), mtime=0))
            results.append({k: result[k] for k in ('writer', 'character', 'component_id', 'canonical', 'mode', 'candidate_count', 'accepted', 'current_source_strokes', 'target_strokes')})
            print(writer, char, node.canonical, mode, 'PASS' if accepted else 'NOT PASS', len(entries), flush=True)
    dump(out / 'summary.json', results)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    args = p.parse_args()
    run(args.output, args.audit)
