"""Place complete source components on the reference glyph."""
from __future__ import annotations

import copy
from dataclasses import asdict

from ..component_style import component_context_key
from .component_index import ordered_ids
from .initial_placement import choose_component_fast
from ..geometry_audit import audit_glyph
from ..topology_repair import glyph_curves
from ..trajectory_experiment import (
    SharedTransform,
    crossing_pairs,
    decode_component,
    invariants,
)

SOURCE_POLICY = 'complete_source_components_v1'


class SourceComponentGenerator:
    """Select and place complete recorded components, preserving every source vertex."""

    def _select_component(self, current, graph, ids, candidates):
        return choose_component_fast(current, graph, ids, candidates, self.index.sources,
                                     anchor_cache=self.anchor_cache, writer=self.baseline.profile.writer_id)

    def generate(self, graph):
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
            raw, selection = self._select_component(current, graph, ids, candidates)
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
            'simplification_epsilon': None,
            'accepted_component_count': sum(bool(r.get('selection', {}).get('selected')) for r in reports),
            'accepted_stroke_ids': [s.stroke_id for s in graph.strokes if s.stroke_id in accepted_ids],
            'components': reports,
            'fallback_reason': None if accepted_ids else 'no complete component accepted; baseline retained',
            'confidence_semantics': 'glyph/stroke confidence inherited from A; not calibrated for source placement; source mapping scores are separate evidence, not quality probabilities',
            'new_strict_crossings_vs_baseline': sorted(new_crossings),
            'geometry_audit': audit_glyph(asdict(current), graph)}
        return current, diagnostics
