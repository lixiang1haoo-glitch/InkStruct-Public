"""Opt-in full author-stroke fallback; never imported by production generation.

Stroke synthesis is explicitly weaker than intact-component reuse. Descriptors
are used for retrieval only: every delivered source point/pressure/time survives.
An incomplete diagnostic can be rendered, but cannot pass author-only export.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict

import numpy as np

from .contextual_trajectory import anchors, fit_shared_similarity
from .geometry import path_length, stroke_signature
from .positional_variants import key_form
from .trajectory_experiment import SharedTransform, assemble, at_distance, crossing_pairs
from .v61_contacts import contact_pairs

PARAMETERS = {'mapping_min': .55, 'sample_mapping_min': .30,
              'max_candidates': 32, 'max_endpoint_error': .10,
              'length_ratio': [.65, 1.45], 'brush_width': .028}


def falling_without_uphook(points):
    length = path_length(points)
    tail = np.asarray(points[-1]) - at_distance(points, .85 * length)
    return key_form(points)['form'] == 'left_falling' and tail[1] >= -.02 * length


def stroke_class(points):
    """Conservative reference-content bucket, not a Chinese-stroke ontology.

    Exact directional signatures retain complex turns/hooks. A broad falling
    bucket handles curved pie; it cannot accept an upward terminal hook.
    """
    sig = stroke_signature(points)
    if falling_without_uphook(points) and sig.turns <= 1 and not set(sig.directions) & set('↑↗↖→'):
        return 'pie'
    if sig.directions == '→':
        return 'heng'
    if sig.directions in ('↓', '↘↓') and not sig.hook:
        return 'shu'
    if sig.directions == '↘':
        return 'diagonal_short' if path_length(points) < .22 else 'diagonal_long'
    return f'complex:{sig.directions}:{sig.hook}'


def valid_source(stroke):
    p = np.asarray(stroke.points)
    return (len(p) >= 2 and len(p) == len(stroke.pressure) == len(stroke.t_ms)
            and np.isfinite(p).all() and np.isfinite(stroke.pressure).all()
            and np.isfinite(stroke.t_ms).all()
            and min(stroke.pressure) >= 0 and max(stroke.pressure) <= 1
            and all(a <= b for a, b in zip(stroke.t_ms, stroke.t_ms[1:]))
            and path_length(stroke.points) > 1e-6)


def pair_changes(before, after, reference):
    """All actual polyline pairs, independent of provenance ownership."""
    old, new, ref = map(crossing_pairs, (before, after, reference))
    oc, nc, rc = (contact_pairs(c, .028) for c in (before, after, reference))
    return {'new_crossings': sorted(new - old),
            'unsupported_crossings': sorted(new - old - ref),
            'new_contacts': sorted(nc - oc), 'unsupported_contacts': sorted(nc - oc - rc)}


def retain_source_relationships(changes, retained_indices):
    """Unmodified strokes of ONE source component retain their internal topology.

    The replaced key and every other component remain outside this allowance.
    Call only after verifying that these strokes share the saved source transform.
    """
    result = dict(changes)
    retained = set(retained_indices)
    for kind in ('crossings', 'contacts'):
        result['inherited_source_' + kind] = [pair for pair in changes['unsupported_' + kind]
                                              if set(pair) <= retained]
        result['unsupported_' + kind] = [pair for pair in changes['unsupported_' + kind]
                                         if not set(pair) <= retained]
    return result


class AuthorStrokeFallback:
    def __init__(self, profile, repository):
        if profile.trajectory_schema != 'source_trajectory_v1':
            raise ValueError('full source archive required')
        if profile.build_identity.get('structure_sha256') != repository.content_sha256():
            raise ValueError('source mapping version mismatch')
        self.profile = profile
        self.pool = defaultdict(list)
        self.rejected = Counter()
        for sample in sorted(profile.source_trajectories.values(), key=lambda s: s.sample_id):
            graph = repository.get(sample.character)
            if (sample.stroke_order_status not in ('declared', 'corrected')
                    or [s.standard_stroke_id for s in sample.strokes] != [s.stroke_id for s in graph.strokes]
                    or min(s.confidence for s in sample.strokes) < PARAMETERS['sample_mapping_min']):
                self.rejected['sample mapping'] += 1
                continue
            for s, ref in zip(sample.strokes, graph.strokes, strict=True):
                if s.confidence < PARAMETERS['mapping_min'] or not valid_source(s):
                    self.rejected['stroke mapping or invalid capture'] += 1
                    continue
                self.pool[stroke_class(ref.median)].append((sample, s, ref))

    def select(self, graph, index, current, reference, *, start_anchor=None):
        target = reference[index]
        kind = stroke_class(graph.strokes[index].median)
        ranked, rejected = [], Counter()
        for sample, source, ref in self.pool[kind]:
            if sample.character == graph.character:  # Exclude every same-character repeat.
                rejected['same character'] += 1
                continue
            if kind == 'pie' and not falling_without_uphook(source.points):
                rejected['actual source not pie'] += 1
                continue
            try:
                transform = fit_shared_similarity([source.points], [target])
            except ValueError:
                rejected['fit'] += 1
                continue
            if start_anchor is not None:
                transform = SharedTransform(transform.sx, transform.sy,
                    start_anchor[0] - transform.sx * source.points[0][0],
                    start_anchor[1] - transform.sy * source.points[0][1])
            placed = transform.apply(source.points)
            length_ratio = path_length(placed) / max(path_length(target), 1e-9)
            if not PARAMETERS['length_ratio'][0] <= length_ratio <= PARAMETERS['length_ratio'][1]:
                rejected['length ratio'] += 1
                continue
            endpoint = max(math.dist(placed[0], target[0]), math.dist(placed[-1], target[-1]))
            if endpoint > PARAMETERS['max_endpoint_error'] or not np.all((np.array(placed) >= 0) & (np.array(placed) <= 1)):
                rejected['bounds or endpoints'] += 1
                continue
            # Geometry score is a placement prior, not an author-style score.
            score = float(np.linalg.norm(anchors([placed]) - anchors([target]), axis=1).mean())
            ranked.append((score + .01 * (1 - source.confidence), sample, source, transform, placed))
        ranked.sort(key=lambda r: (r[0], r[1].sample_id, r[2].standard_stroke_id))
        # Baseline/reference support only permits existing relationships. It does
        # not assert that font topology is the author's true intended topology.
        for score, sample, source, transform, placed in ranked[:PARAMETERS['max_candidates']]:
            trial = [*current]
            trial[index] = placed
            # Only pairs involving this stroke can change; avoid rescanning the
            # complete glyph for every candidate.
            others = [j for j in range(len(current)) if j != index]
            unsupported = False
            for j in others:
                changes = pair_changes([current[index], current[j]], [placed, current[j]],
                                       [reference[index], reference[j]])
                if changes['unsupported_crossings'] or changes['unsupported_contacts']:
                    unsupported = True
                    break
            if unsupported:
                rejected['new unsupported crossing/contact'] += 1
                continue
            provenance = {'kind': 'author_single_stroke', 'character': sample.character,
                'sample_id': sample.sample_id, 'source_sha256': sample.source_sha256,
                'source_stroke_id': source.standard_stroke_id,
                'target_stroke_id': graph.strokes[index].stroke_id,
                'mapping_confidence': source.confidence, 'content_bucket': kind,
                'transform': asdict(transform), 'placement_score': score,
                'source_point_count': len(source.points), 'rejections': dict(rejected)}
            return {'points': placed, 'pressure': source.pressure, 'time': source.t_ms}, provenance
        return None, {'target_stroke_id': graph.strokes[index].stroke_id,
                      'content_bucket': kind, 'eligible_geometry': len(ranked),
                      'reason': 'no admitted author stroke', 'rejections': dict(rejected)}

    def fill(self, glyph, graph, reference, provenance):
        from .v61_exp import curves
        current = curves(glyph)
        replacements, result, log = {}, dict(provenance), []
        for i in range(len(current)):
            if i in result:
                continue
            replacement, evidence = self.select(graph, i, current, reference)
            log.append(evidence)
            if replacement:
                replacements[i] = replacement
                current[i] = replacement['points']
                result[i] = evidence
        generated = assemble(glyph, replacements, 'author_single_stroke')
        for i, p in result.items():
            if i in replacements:
                generated.strokes[i].confidence = p['mapping_confidence']
                generated.strokes[i].component_key = None
        missing = [s.standard_stroke_id for i, s in enumerate(generated.strokes) if i not in result]
        return generated, result, {'author_only_ready': not missing, 'missing': missing, 'trials': log}


def require_author_only(glyph, provenance):
    """The explicit author-only route fails closed, never silently emits a font."""
    if set(provenance) != set(range(len(glyph.strokes))):
        raise ValueError('author-only output incomplete; collect or approve missing stroke sources')
    return glyph
