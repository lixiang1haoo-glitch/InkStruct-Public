"""Read-only fallback census: existing archive identity, mapping and admission evidence.

Absence means absence from declared full source views, not proof that no latent
subcomponent exists. Exclusive stroke-weighted causes are separate from multi-
label candidate rejections. Target captures are never used.
"""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from generate_v61_library import CORRECTIONS, DB, SOURCES, WRITERS, digest, dump

from inkstruct.exemplar_index import component_key, ordered_ids
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.v6_exp import V6ExemplarIndex
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_collection import public_view

LIBRARY = Path('artifacts/v61_full_library_20261014/run_v1')


def identity(node):
    return node.canonical, node.glyph_variant, len(node.stroke_ids)


def source_inventory(profile, index):
    inventory = defaultdict(list)
    for sample in profile.source_trajectories.values():
        graph = index.graph(sample.character)
        mapping = {s.standard_stroke_id: s for s in sample.strokes}
        full_order = [s.standard_stroke_id for s in sample.strokes] == [s.stroke_id for s in graph.strokes]
        for node in graph.components:
            ids = ordered_ids(graph, node)
            if not ids:
                continue
            errors = []
            if not full_order or sample.stroke_order_status not in ('declared', 'corrected'):
                errors.append('archive_order_or_ids')
            if node.confidence < .8:
                errors.append('component_mapping_confidence')
            if any(k not in mapping for k in ids):
                errors.append('missing_stroke_id')
                scores = [0.]
            else:
                scores = [mapping[k].confidence for k in ids]
                if min(scores) < .3 or np.mean(scores) < .55:
                    errors.append('stroke_mapping_confidence')
            entry = {'character': sample.character, 'sample_id': sample.sample_id,
                     'source_sha256': sample.source_sha256, 'component_id': node.component_id,
                     'stroke_ids': ids, 'context': component_key(graph, node),
                     'root': node.path == 'root', 'nonleaf': bool(node.children_ids),
                     'min_confidence': min(scores), 'mean_confidence': float(np.mean(scores)),
                     'mapping_errors': errors}
            inventory[identity(node)].append(entry)
    return inventory


def classify(*, scheduled, target_reliable, raw, cross, reliable, trials, same_context, roots):
    """Exclusive first-obstacle labels, not counts of proven false rejections."""
    if not target_reliable:
        return 'target_structure_mapping_unresolved'
    if not scheduled:
        return 'target_not_scheduled_with_source' if reliable else 'target_not_scheduled_no_reliable_declared_source'
    if not raw:
        return 'no_declared_identity_count_source'
    if not cross:
        return 'only_same_character_source_excluded'
    if not reliable:
        return 'source_mapping_unreliable'
    if trials:
        return 'actual_placement_rejected'
    if same_context:
        return 'reference_shape_or_fit_gate'
    if roots:
        return 'root_bridge_mapping_or_reference_gate'
    return 'context_or_index_scope_restriction'


def audit_writer(writer, root_string):
    out = Path(root_string)
    base = StructureRepository(DB)
    target = CorrectedStructureRepository(base, *CORRECTIONS)
    profile = load_profile(SOURCES[writer])
    index = V6ExemplarIndex(profile, base)
    inventory = source_inventory(profile, index)
    canonical_inventory = defaultdict(list)
    for key, values in inventory.items():
        canonical_inventory[key[0]].extend(values)
    rows, root_opportunities, count, reasons, omitted = [], [], Counter(), Counter(), Counter()
    chars = base.characters()
    for number, char in enumerate(chars, 1):
        record_path = LIBRARY / writer / f'{ord(char):04X}.json.gz'
        d = json.loads(gzip.decompress(record_path.read_bytes()))
        glyph = d['glyph']
        fallback = {s['standard_stroke_id'] for s in glyph['strokes'] if 'reference' in s['style_source']}
        count['all_strokes'] += len(glyph['strokes'])
        count['source_strokes'] += len(glyph['strokes']) - len(fallback)
        if not fallback:
            continue
        graph = framed_graph(public_view(target, char), reference_frame(target.get(char)))
        nodes = {n.component_id: n for n in graph.components}
        root_node = next(n for n in graph.components if n.path == 'root')
        root_sources = [r for r in inventory.get(identity(root_node), [])
                        if not r['mapping_errors'] and r['character'] != char]
        if root_sources:
            root_opportunities.append({'writer': writer, 'character': char, 'fallback_strokes': len(fallback),
                'all_strokes': len(glyph['strokes']), 'target_confidence': root_node.confidence,
                'source_components': root_sources, 'note': 'whole-component-to-root alternative not tested by current path'})
        parts = d['baseline_selection']['components']
        covered = set()
        slots = []
        for part in parts:
            ids = set(part['target_stroke_ids']) & fallback
            if ids:
                assert ids == set(part['target_stroke_ids']), 'partial component fallback'
                slots.append((nodes[part['component_id']], ids, True, part))
                assert not covered & ids
                covered |= ids
        for node in sorted(graph.components, key=lambda n: len(n.stroke_ids)):
            ids = set(node.stroke_ids) & (fallback - covered)
            if ids:
                # A residual group can have structural ambiguity; never call it
                # an available complete component if only part of node remains.
                slots.append((node, ids, False, {}))
                covered |= ids
        assert covered == fallback
        for node, ids, scheduled, part in slots:
            complete_target = ids == set(node.stroke_ids)
            raw = inventory.get(identity(node), []) if complete_target else []
            cross = [r for r in raw if r['character'] != char]
            reliable = [r for r in cross if not r['mapping_errors']]
            context = component_key(graph, node)
            same_context = [r for r in index.by_key.get(context, []) if r['character'] != char]
            trials, root_logs = [], []
            for stage in d['expansion'].values():
                trials += [t for t in stage['placement']
                           if set((t.get('source_mapping_evidence') or {}).get('target_ids', [])) == ids]
                root_logs += [t for t in stage['root_mapping'] if t['component_id'] == node.component_id]
            reason = classify(scheduled=scheduled, target_reliable=complete_target and node.confidence >= .8,
                              raw=raw, cross=cross, reliable=reliable, trials=trials,
                              same_context=same_context, roots=root_logs)
            canonical_other = [r for r in canonical_inventory.get(node.canonical, []) if r['character'] != char]
            if reason == 'no_declared_identity_count_source' and canonical_other:
                reason = 'identity_variant_or_stroke_count_mismatch'
            gates = Counter(t['fallback_reason'] for t in trials if not t['accepted'])
            root_rejections = Counter(t.get('rejected') for t in root_logs if t.get('rejected'))
            # Log full same-context counts, including omitted candidates past 16.
            eligible_count = 0
            if scheduled and same_context:
                eligible_count = len(index.candidates(graph, node))
            if eligible_count > 16:
                omitted['fallback_slots_with_more_than_16_candidates'] += 1
            row = {'writer': writer, 'character': char, 'component_id': node.component_id,
                   'canonical': node.canonical, 'variant': node.glyph_variant, 'context': context,
                   'stroke_ids': sorted(ids, key=lambda x: int(x[1:])), 'strokes': len(ids),
                   'scheduled': scheduled, 'complete_target': complete_target,
                   'target_confidence': node.confidence, 'reason': reason,
                   'same_canonical_other_samples': len(canonical_other), 'same_identity_samples': len(raw), 'cross_character_samples': len(cross),
                   'reliable_identity_samples': len(reliable), 'same_context_indexed': len(same_context),
                   'eligible_before_top16': eligible_count,
                   'actual_rejection_reasons': dict(gates), 'root_rejections': dict(root_rejections),
                   'reliable_sources': reliable,
                   'unreliable_sources': [r for r in cross if r['mapping_errors']],
                   'library_record_sha256': digest(record_path)}
            rows.append(row)
            count[reason] += len(ids)
            reasons.update(gates)
        if number % 1000 == 0:
            print(writer, number, 'fallback slots', len(rows), flush=True)
            target._cache.clear()
    assert sum(v for k, v in count.items() if k not in ('all_strokes', 'source_strokes')) == count['all_strokes'] - count['source_strokes']
    dump(out / f'{writer}.json', rows)
    dump(out / f'{writer}_root_opportunities.json', root_opportunities)
    summary = {'writer': writer, 'stroke_partition': dict(count), 'slot_counts': dict(Counter(r['reason'] for r in rows)),
               'candidate_rejection_counts_not_exclusive': dict(reasons), **omitted,
               'source_samples': len(profile.source_trajectories),
               'whole_target_source_components_exist': len(root_opportunities),
               'whole_target_source_components_with_reliable_target': sum(r['target_confidence'] >= .8 for r in root_opportunities)}
    dump(out / f'{writer}_summary.json', summary)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {'library': str(LIBRARY), 'library_protocol_sha256': digest(LIBRARY / 'protocol.json'),
                'source_archives': {str(p): digest(p) for p in SOURCES.values()},
                'audit_code_sha256': digest(Path(__file__)), 'production_changed': False,
                'absence_scope': 'declared original and already-validated nested source nodes, all roots and nonleaves included',
                'not_done': 'no inference of latent unannotated subcomponents; no target-original style judgment'}
    dump(args.output / 'protocol.json', manifest)
    with ProcessPoolExecutor(max_workers=4) as pool:
        summaries = list(pool.map(audit_writer, WRITERS, [str(args.output)] * 4))
    dump(args.output / 'summary.json', summaries)
    print(json.dumps(summaries, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
