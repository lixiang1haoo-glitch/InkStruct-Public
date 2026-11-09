"""Local risk diagnostics, deliberately separate from protocol validity.

Warnings are review candidates, not assertions that the author's writing is
wrong. Source topology and source length are imperfect structural references.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from .geometry import bbox, path_length
from .trajectory_experiment import crossing_pairs

AUDIT_VERSION = 'local_geometry_audit_v1'


def audit_glyph(glyph, graph, *, low_confidence_threshold=0.35):
    value = asdict(glyph) if is_dataclass(glyph) else glyph
    strokes = value['strokes']
    expected_ids = [s.stroke_id for s in graph.strokes]
    if [s['standard_stroke_id'] for s in strokes] != expected_ids:
        raise ValueError('audit requires matching standard stroke IDs/order')
    curves = [[(float(p['x']), float(p['y'])) for p in s['points']] for s in strokes]
    standard = [s.median for s in graph.strokes]
    output_box, standard_box = bbox([p for c in curves for p in c]), bbox([p for c in standard for p in c])
    output_span = max(output_box[2] - output_box[0], output_box[3] - output_box[1])
    standard_span = max(standard_box[2] - standard_box[0], standard_box[3] - standard_box[1], 1e-9)
    scale = max(output_span / standard_span, 1e-9)
    source_crossings = crossing_pairs(standard)
    output_crossings = crossing_pairs(curves)
    warnings = [{'kind': 'extra_strict_crossing',
                 'stroke_ids': [expected_ids[i], expected_ids[j]],
                 'meaning': 'not present in standard centerlines; author variation may be valid'}
                for i, j in sorted(output_crossings - source_crossings)]
    lengths = []
    for stroke, raw, generated in zip(graph.strokes, standard, curves, strict=True):
        source_length, generated_length = path_length(raw), path_length(generated)
        ratio = generated_length / max(source_length * scale, 1e-9)
        entry = {'stroke_id': stroke.stroke_id, 'source_length': source_length,
                 'output_length': generated_length, 'glyph_scale_adjusted_length_ratio': ratio}
        lengths.append(entry)
        if source_length < .01:
            warnings.append({'kind': 'tiny_source_stroke', **entry})
        if generated_length < .003:
            warnings.append({'kind': 'near_point_stroke', **entry})
        if generated_length < 1e-4 or ratio < .1:
            warnings.append({'kind': 'severe_shortening', **entry})
    confidence = {s['standard_stroke_id']: float(s['confidence']) for s in strokes}
    return {'schema_version': AUDIT_VERSION,
            'min_stroke_confidence': min(confidence.values(), default=None),
            'low_confidence_threshold': low_confidence_threshold,
            'low_confidence_stroke_ids': [k for k, v in confidence.items() if v < low_confidence_threshold],
            'style_sources': {s['standard_stroke_id']: s.get('style_source', 'unknown') for s in strokes},
            'geometry_warnings': warnings,
            'structure_warnings': list(graph.component_warnings),
            'stroke_lengths': lengths,
            'interpretation': 'risk screening only; protocol pass does not establish visual quality'}
