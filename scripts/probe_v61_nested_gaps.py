"""Small diagnostic-only target-view expansion using the existing exact admission checks."""
from __future__ import annotations

import argparse
import copy
import gzip
import json
from dataclasses import asdict
from pathlib import Path

from generate_v61_library import CORRECTIONS, DB, REVIEW, SOURCES, digest, dump, encoded, generate
from run_v61_exp import check_integrity

from inkstruct.component_views import expand_views
from inkstruct.exemplar_index import ordered_ids
from inkstruct.fast_placement import choose_component_fast
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import SharedTransform
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_admission_exp import AdmissionProbeGenerator
from inkstruct.v61_exp import Placement


def run(out, inventory):
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'protocol.json', {'script_sha256': digest(Path(__file__)), 'inventory': str(inventory),
        'only_change': 'additional target component names passed to existing validated expand_views',
        'all_candidates': 'unchanged exact context, shape, mapping and first-16 filters',
        'layout': 'unchanged whole-component isotropic anchor fit; source-aware guards unchanged',
        'production_changed': False, 'target_originals_used': False})
    base = StructureRepository(DB)
    target = CorrectedStructureRepository(base, *CORRECTIONS)
    summaries = []
    for writer, char in [('user_001', '想'), ('user_001', '清'), ('scx', '想'), ('mjb', '架'), ('wsq', '案')]:
        opportunities = [r for r in json.loads((inventory / f'{writer}.json').read_text()) if r['character'] == char]
        if not opportunities:
            continue
        engine = AdmissionProbeGenerator(load_profile(SOURCES[writer]), base, target)
        ctx, current, original_plan, _ = generate(engine, char, writer, json.loads(REVIEW.read_text()))
        probe = copy.copy(ctx)
        raw = target.get(char)
        view = expand_views(raw, target, allowed=tuple(r['parent_canonical'] for r in opportunities))
        probe.graph = framed_graph(view.graph, reference_frame(raw))
        assert [(s.stroke_id, s.median) for s in probe.graph.strokes] == [(s.stroke_id, s.median) for s in ctx.graph.strokes]
        probe.pools = {**ctx.pools}
        plan, trials = dict(original_plan), []
        for r in opportunities:
            for child in r['children']:
                node = next(n for n in probe.graph.components if n.component_id == child['component_id'])
                ids = tuple(ordered_ids(probe.graph, node))
                if any(set(ids) & set(p.ids) for p in plan.values()):
                    continue
                pool = engine.v6.index.candidates(probe.graph, node)
                _, diag = choose_component_fast(engine.emit(probe, plan), probe.graph, ids, pool, engine.profile.source_trajectories)
                placements = [Placement(node.component_id, ids,
                    tuple(i for i, s in enumerate(probe.graph.strokes) if s.stroke_id in ids),
                    t['candidate'], SharedTransform(**t['transform']), t['score'])
                    for t in diag['candidates'] if 'transform' in t]
                probe.pools[node.component_id] = placements
                for p in sorted(placements, key=lambda p: p.base_score):
                    try:
                        new, result = engine.attempt(probe, plan, p, source_aware=True)
                    except ValueError as exc:
                        trials.append({'candidate': p.candidate, 'accepted': False, 'fallback_reason': str(exc)})
                        continue
                    trials.append(result)
                    if result['accepted']:
                        plan = new
                        break
        glyph = engine.emit(probe, plan)
        row = {'writer': writer, 'character': char, 'before': check_integrity(engine, ctx, current, original_plan),
               'after': check_integrity(engine, probe, glyph, plan), 'view_validation': view.diagnostics,
               'provenance': [asdict(p) for p in plan.values()], 'trials': trials,
               'current_glyph': asdict(current), 'trial_glyph': asdict(glyph)}
        (out / f'{writer}-{ord(char):04X}.json.gz').write_bytes(gzip.compress(encoded(row), mtime=0))
        summaries.append({k: row[k] for k in ('writer', 'character', 'before', 'after')})
    dump(out / 'summary.json', summaries)
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    run(args.output, args.inventory)
