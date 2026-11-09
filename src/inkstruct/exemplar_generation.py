"""Explicit, auditable source-component generation; legacy defaults stay unchanged."""
from __future__ import annotations

import copy
from dataclasses import asdict

from .component_style import component_context_key
from .exemplar_index import ExemplarIndex, ordered_ids
from .fast_placement import choose_component_fast
from .geometry_audit import audit_glyph
from .source_trajectory import TRAJECTORY_SCHEMA
from .topology_repair import glyph_curves
from .trajectory_experiment import (
    SharedTransform,
    assemble,
    crossing_pairs,
    decode_component,
    invariants,
)

SOURCE_POLICY = 'complete_source_components_v1'
SIMPLIFICATION_EPSILON = .004  # Fixed simplification threshold; normalized output units.


class SourceComponentGenerator:
    """Wrap a fixed adaptive baseline and change only disjoint complete components.

    Candidate selection always uses complete points. Simplification is applied
    after selection with the same transform, and falls back to that raw component
    if it changes whole-glyph strict crossing pairs. No target capture is read.
    """

    def __init__(self, baseline, source_profile, repository, *, mode='source-raw',
                 nested_views=False, allowed_characters=None):
        if mode not in ('source-raw', 'source-simplified'):
            raise ValueError('unknown source trajectory mode')
        if baseline.profile.writer_id != source_profile.writer_id:
            raise ValueError('source profile writer does not match requested writer')
        if baseline.component_mode != 'adaptive' or baseline.component_strength != 1.:
            raise ValueError('source generation requires fixed adaptive baseline at strength 1')
        if source_profile.trajectory_schema != TRAJECTORY_SCHEMA or not source_profile.source_trajectories:
            raise ValueError('source generation requires a retained-source trajectory profile')
        if source_profile.build_identity.get('structure_sha256') != repository.content_sha256():
            raise ValueError('source mappings use a different structure database; rebuild source profile')
        self.baseline, self.mode = baseline, mode
        self.index = ExemplarIndex(source_profile, repository, nested_views=nested_views,
                                   allowed_characters=allowed_characters)
        self.anchor_cache = {}

    def _select_component(self, current, graph, ids, candidates, component, occurrence_id):
        return choose_component_fast(current, graph, ids, candidates, self.index.sources,
                                     anchor_cache=self.anchor_cache)

    def generate(self, graph, *, occurrence_id=0):
        base = self.baseline.generate(graph)
        current = base
        view = self.index.graph(graph.character)
        used, reports, accepted_ids = set(), [], set()
        # Leaf paths are stable; only non-overlapping complete groups are eligible.
        components = sorted((n for n in view.components if n.path != 'root'
                             and not n.children_ids and len(n.stroke_ids) >= 2), key=lambda n: n.path)
        for component in components:
            ids = ordered_ids(view, component)
            record = {'component_id': component.component_id, 'canonical': component.canonical,
                      'target_stroke_ids': ids}
            reports.append(record)
            if used.intersection(ids):
                record['fallback_reason'] = 'overlapping component view'
                continue
            used.update(ids)
            candidates = self.index.candidates(view, component)
            if not candidates:
                record['fallback_reason'] = 'no compatible cross-character source component'
                continue
            raw, selection = self._select_component(current, graph, ids, candidates, component, occurrence_id)
            record['selection'] = selection
            record['fallback_reason'] = selection['fallback_reason']
            if selection['fallback_reason']:
                continue
            selected = selection['selected']
            candidate = selected['candidate']
            sample = self.index.sources[candidate['sample_id']]
            mapping = {s.standard_stroke_id: s for s in sample.strokes}
            source = [mapping[k] for k in candidate['stroke_ids']]
            transform = SharedTransform(**selected['transform'])
            _, retained, _ = decode_component(source, transform, 'B')
            current = raw
            record['simplification_fallback'] = None
            record['retained_source_indices'] = retained
            record['source_point_count'] = sum(len(s.points) for s in source)
            record['output_point_count'] = record['source_point_count']
            record['source_mapping_confidence'] = {target_id: s.confidence
                for target_id, s in zip(ids, source, strict=True)}
            record['representation'] = 'source-raw'
            for stroke in current.strokes:
                if stroke.standard_stroke_id in ids:
                    stroke.style_source = 'source-raw'
                    stroke.component_key = component_context_key(view, component)
            accepted_ids.update(ids)
        # Freeze the complete raw donor/layout schedule before any simplification.
        # Thus raw and simplified runs have exactly the same candidate choices,
        # even when earlier simplified outlines would affect a later safety gate.
        if self.mode == 'source-simplified':
            for record in reports:
                selected = record.get('selection', {}).get('selected')
                if not selected:
                    continue
                candidate = selected['candidate']
                sample = self.index.sources[candidate['sample_id']]
                mapping = {s.standard_stroke_id: s for s in sample.strokes}
                source = [mapping[k] for k in candidate['stroke_ids']]
                decoded, retained, fallback = decode_component(source,
                    SharedTransform(**selected['transform']), 'C', SIMPLIFICATION_EPSILON)
                ids = record['target_stroke_ids']
                indices = [i for i, s in enumerate(current.strokes) if s.standard_stroke_id in ids]
                proposal = assemble(current, dict(zip(indices, decoded, strict=True)), 'source_simplified')
                if invariants(proposal, graph) or crossing_pairs(glyph_curves(proposal)) != crossing_pairs(glyph_curves(current)):
                    record['simplification_fallback'] = 'simplification changes whole-glyph topology or invariants; use raw component'
                    continue
                current = proposal
                record['simplification_fallback'] = fallback
                record['retained_source_indices'] = retained
                record['output_point_count'] = sum(len(s['points']) for s in decoded)
                record['representation'] = 'source-raw' if fallback else 'source-simplified'
                for i in indices:
                    current.strokes[i].style_source = record['representation']
        errors = invariants(current, graph)
        new_crossings = crossing_pairs(glyph_curves(current)) - crossing_pairs(glyph_curves(base))
        if errors or new_crossings:
            raise RuntimeError(f'source generator failed final checks: {errors}, {sorted(new_crossings)}')
        if accepted_ids:
            current.generator = SOURCE_POLICY
            # The baseline was fitted once. Source placements are verified in
            # bounds, never refitted/rounded (which would alter original corners).
            current.canvas_fit = copy.deepcopy(base.canvas_fit)
            current.canvas_fit['source_placements_verified_in_bounds'] = True
        diagnostics = {'policy': SOURCE_POLICY, 'mode': self.mode,
            'simplification_epsilon': SIMPLIFICATION_EPSILON if self.mode == 'source-simplified' else None,
            'accepted_component_count': sum(bool(r.get('selection', {}).get('selected')) for r in reports),
            'accepted_stroke_ids': [s.stroke_id for s in graph.strokes if s.stroke_id in accepted_ids],
            'components': reports,
            'fallback_reason': None if accepted_ids else 'no complete component accepted; baseline retained',
            'confidence_semantics': 'glyph/stroke confidence inherited from A; not calibrated for source placement; source mapping scores are separate evidence, not quality probabilities',
            'new_strict_crossings_vs_baseline': sorted(new_crossings),
            'geometry_audit': audit_glyph(asdict(current), graph)}
        return current, diagnostics
