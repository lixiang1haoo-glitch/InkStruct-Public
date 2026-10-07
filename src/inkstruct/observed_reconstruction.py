"""Explicit reconstruction of captured glyphs, separate from cross-character inference."""
from __future__ import annotations

import math
from dataclasses import asdict

from .canvas_boundary import BOUNDARY_POLICY
from .exemplar_generation import SIMPLIFICATION_EPSILON, SourceComponentGenerator
from .geometry import bbox, path_length
from .geometry_audit import audit_glyph
from .topology_repair import glyph_curves
from .trajectory_experiment import (
    SharedTransform,
    assemble,
    crossing_pairs,
    decode_component,
    invariants,
)

OBSERVED_POLICY = 'observed_whole_glyph_v1'
# Existing local-review boundary, not a learned probability of aesthetic quality.
MIN_MAPPING_CONFIDENCE = .35


def source_rejection(sample, graph):
    ids = [s.stroke_id for s in graph.strokes]
    if sample.stroke_order_status not in ('declared', 'corrected'):
        return 'ambiguous source stroke order'
    if len(sample.strokes) != len(ids) or {s.standard_stroke_id for s in sample.strokes} != set(ids):
        return 'incomplete or duplicate source mapping'
    if len({s.user_order for s in sample.strokes}) != len(ids):
        return 'duplicate captured stroke order'
    for stroke in sample.strokes:
        if not math.isfinite(stroke.confidence) or stroke.confidence < MIN_MAPPING_CONFIDENCE:
            return 'source mapping below existing local-review threshold'
        if len(stroke.points) < 2 or len(stroke.pressure) != len(stroke.points) or len(stroke.t_ms) != len(stroke.points):
            return 'invalid source point channels'
        values = [v for point in stroke.points for v in point] + stroke.pressure + stroke.t_ms
        if not all(math.isfinite(v) for v in values):
            return 'nonfinite source channel'
        if any(not 0 <= v <= 1 for p in stroke.points for v in p) or any(not 0 <= p <= 1 for p in stroke.pressure):
            return 'source coordinates or pressure out of range'
        if any(b < a for a, b in zip(stroke.t_ms, stroke.t_ms[1:])):
            return 'source time reversed within a stroke'
        if path_length(stroke.points) < 1e-9:
            return 'degenerate captured stroke'
    return None


class ObservedSourceGenerator(SourceComponentGenerator):
    """Opt-in observed glyph priority; unavailable/rejected glyphs use existing inference.

    Reconstruct one complete captured glyph with identity scale/translation in
    its retained normalized frame. No target measurements enter the inherited
    cross-character branch. An explicit training whitelist applies to both paths.
    """
    def __init__(self, *args, allowed_characters=None, **kwargs):
        super().__init__(*args, allowed_characters=allowed_characters, **kwargs)
        self.observed = {}
        for sample in self.index.sources.values():
            if allowed_characters is None or sample.character in allowed_characters:
                self.observed.setdefault(sample.character, []).append(sample)

    def generate(self, graph, *, occurrence_id=0):
        checked, accepted = [], []
        for sample in self.observed.get(graph.character, []):
            reason = source_rejection(sample, graph)
            checked.append({'sample_id': sample.sample_id, 'source_sha256': sample.source_sha256,
                            'rejection_reason': reason})
            if reason is None:
                accepted.append(sample)
        if not accepted:
            glyph, diagnostics = super().generate(graph, occurrence_id=occurrence_id)
            diagnostics['observed_reconstruction'] = {'policy': OBSERVED_POLICY, 'used': False,
                'checked_sources': checked, 'reason': 'no eligible captured glyph in the allowed source set',
                'evaluation_scope': 'cross-character inference; target captures unused'}
            return glyph, diagnostics
        sample = min(accepted, key=lambda s: (-min(t.confidence for t in s.strokes),
                     -sum(t.confidence for t in s.strokes)/len(s.strokes), s.sample_id))
        source_map = {s.standard_stroke_id: s for s in sample.strokes}
        ids = [s.stroke_id for s in graph.strokes]
        source = [source_map[sid] for sid in ids]
        base = self.baseline.generate(graph)
        transform = SharedTransform(1., 1., 0., 0.)
        raw, raw_indices, _ = decode_component(source, transform, 'B')
        output = assemble(base, dict(enumerate(raw)), 'observed_raw')
        source_crossings = crossing_pairs(glyph_curves(output))
        retained, fallback = raw_indices, None
        representation = 'observed-raw'
        if self.mode == 'source-simplified':
            decoded, kept, fallback = decode_component(source, transform, 'C', SIMPLIFICATION_EPSILON)
            proposal = assemble(base, dict(enumerate(decoded)), 'observed_simplified')
            if invariants(proposal, graph) or crossing_pairs(glyph_curves(proposal)) != source_crossings:
                fallback = 'simplification changes captured topology or invariants; use complete capture'
            else:
                output, retained = proposal, kept
                representation = 'observed-raw' if fallback else 'observed-simplified'
        errors = invariants(output, graph)
        if errors:
            raise RuntimeError(f'observed reconstruction failed invariants: {errors}')
        output.generator = OBSERVED_POLICY
        for stroke in output.strokes:
            stroke.style_source, stroke.component_key = representation, f'observed:{graph.character}:root'
        # Already bounded; do not call the legacy fitter, which rounds source vertices.
        box = bbox([p for stroke in source for p in stroke.points])
        output.canvas_fit = {'policy': BOUNDARY_POLICY, 'applied': False, 'original_bbox': list(box),
            'max_overflow': 0., 'scale': 1., 'translation': [0., 0.], 'review_required': False,
            'coordinate_frame': 'retained normalized captured whole glyph', 'source_points_unrounded': True}
        candidate = {'character': sample.character, 'sample_id': sample.sample_id,
            'source_sha256': sample.source_sha256, 'component_id': 'observed-root', 'stroke_ids': ids}
        record = {'component_id': 'observed-root', 'canonical': '已采集整字', 'target_stroke_ids': ids,
            'selection': {'selected': {'candidate': candidate, 'transform': asdict(transform)},
                          'candidates': checked, 'fallback_reason': None},
            'retained_source_indices': retained, 'simplification_fallback': fallback,
            'representation': representation, 'fallback_reason': None,
            'source_point_count': sum(len(s.points) for s in source),
            'output_point_count': sum(len(s.points) for s in output.strokes),
            'source_mapping_confidence': {s.standard_stroke_id: s.confidence for s in source}}
        new_vs_A = sorted(source_crossings-crossing_pairs(glyph_curves(base)))
        diagnostics = {'policy': OBSERVED_POLICY, 'mode': self.mode,
            'simplification_epsilon': SIMPLIFICATION_EPSILON if self.mode == 'source-simplified' else None,
            'accepted_component_count': 1, 'accepted_stroke_ids': ids, 'components': [record],
            'fallback_reason': None, 'new_strict_crossings_vs_baseline': new_vs_A,
            'observed_reconstruction': {'policy': OBSERVED_POLICY, 'used': True,
                'evaluation_scope': 'same-character reconstruction; not cross-character generalization',
                'minimum_mapping_confidence': MIN_MAPPING_CONFIDENCE, 'checked_sources': checked,
                'crossings_vs_capture': [], 'captured_crossings_absent_in_A': new_vs_A,
                'crossing_semantics': 'retain authored topology; differences from A are not newly synthesized crossings'},
            'confidence_semantics': 'A scores inherited and uncalibrated; source mapping scores reported separately',
            'geometry_audit': audit_glyph(asdict(output), graph)}
        return output, diagnostics
