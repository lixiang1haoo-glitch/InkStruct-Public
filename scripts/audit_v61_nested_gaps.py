"""Secondary census of validated target decomposition opportunities, not usable coverage."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from audit_v61_library_fallbacks import source_inventory
from generate_v61_library import CORRECTIONS, DB, SOURCES, WRITERS, digest, dump

from inkstruct.component_views import expand_views
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.v6_exp import V6ExemplarIndex
from inkstruct.v6_integrated_exp import framed_graph


def worker(writer, audit, output):
    base = StructureRepository(DB)
    target = CorrectedStructureRepository(base, *CORRECTIONS)
    profile = load_profile(SOURCES[writer])
    index = V6ExemplarIndex(profile, base)
    inventory = source_inventory(profile, index)
    reliable = {(e['sample_id'], e['component_id']) for entries in inventory.values() for e in entries if not e['mapping_errors']}
    rows = json.loads((Path(audit) / f'{writer}.json').read_text())
    opportunities = []
    for r in rows:
        if r['reason'] not in ('no_declared_identity_count_source', 'only_same_character_source_excluded') or len(r['variant']) != 1:
            continue
        g = target.get(r['character'])
        view = expand_views(g, target, allowed=(r['canonical'],))
        event = next((e for e in view.diagnostics if e['component_id'] == r['component_id'] and e['expanded']), None)
        if event is None:
            continue
        expanded = framed_graph(view.graph, reference_frame(g))
        children = []
        for node in expanded.components:
            if node.component_id not in event['new_component_ids'] or node.children_ids or len(node.stroke_ids) < 2 or node.confidence < .8:
                continue
            pool = [e for e in index.candidates(expanded, node) if (e['sample_id'], e['component_id']) in reliable]
            if pool:
                children.append({'component_id': node.component_id, 'canonical': node.canonical,
                                 'target_stroke_ids': node.stroke_ids, 'candidates': pool})
        if children:
            ids = {sid for n in children for sid in n['target_stroke_ids']}
            assert ids <= set(r['stroke_ids'])
            opportunities.append({'writer': writer, 'character': r['character'], 'parent_component_id': r['component_id'],
                                  'parent_canonical': r['canonical'], 'prior_reason': r['reason'],
                                  'reference_strokes': r['strokes'], 'candidate_covered_strokes': len(ids),
                                  'validation': event, 'children': children})
    dump(Path(output) / f'{writer}.json', opportunities)
    return {'writer': writer, 'parent_slots': len(opportunities),
            'candidate_covered_strokes_not_admitted': sum(r['candidate_covered_strokes'] for r in opportunities),
            'within_no_declared_source_strokes': sum(r['candidate_covered_strokes'] for r in opportunities if r['prior_reason'] == 'no_declared_identity_count_source')}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    dump(args.output / 'protocol.json', {'code_sha256': digest(Path(__file__)), 'audit': str(args.audit),
        'meaning': 'same existing shape/order/map thresholds, expand additional target names; placement not yet checked', 'production_changed': False})
    with ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, WRITERS, [str(args.audit)] * 4, [str(args.output)] * 4))
    dump(args.output / 'summary.json', results)
    print(json.dumps(results), flush=True)


if __name__ == '__main__':
    main()
