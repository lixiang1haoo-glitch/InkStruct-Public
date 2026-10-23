"""Character-grouped training layout residuals, independent of target captures."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .alignment import _normalise_glyph_extent
from .component_style import parent_layout
from .exemplar_index import component_key, ordered_ids
from .exemplar_variation import source_component
from .geometry import bbox, path_length
from .topology_repair import glyph_curves
from .trajectory_experiment import crossing_pairs, invariants

LAYOUT_POLICY = 'training_component_layout_residual_v1'


def layout_summary(curves):
    box = np.asarray(bbox([p for s in curves for p in s]), dtype=float)
    size = box[2:]-box[:2]
    span = float(size.max())
    if not np.isfinite(box).all() or min(size) <= 1e-8:
        raise ValueError('nondegenerate 2D component extent required')
    return (box[:2]+box[2:])/2, span, size


def public_layout(graph, component):
    normalized = _normalise_glyph_extent([s.median for s in graph.strokes])
    curves = [s for s, public in zip(normalized, graph.strokes, strict=True) if public.stroke_id in component.stroke_ids]
    center, span, size = layout_summary(curves)
    feature = np.r_[center/.85, np.log(size/.85)/2, np.log(len(curves))/4]
    return center, span, feature


def coarse_context(graph, component):
    return component.role, parent_layout(graph, component)


class ComponentLayoutEvidence:
    def __init__(self, index):
        self.exact = defaultdict(list)
        self.coarse = defaultdict(list)
        for context, candidates in index.by_key.items():
            for candidate in candidates:
                sample = index.sources[candidate['sample_id']]
                graph = index.graph(candidate['character'])
                component = next(c for c in graph.components if c.component_id == candidate['component_id'])
                mapping = {s.standard_stroke_id: s.points for s in sample.strokes}
                raw = [mapping[s] for s in candidate['stroke_ids']]
                try:
                    center, span, feature = public_layout(graph, component)
                    observed_center, observed_span, _ = layout_summary(raw)
                except ValueError:
                    continue
                entry = {'candidate': candidate, 'feature': feature,
                    'residual': np.r_[observed_center-center, math.log(observed_span/span)]}
                self.exact[context].append(entry)
                self.coarse[coarse_context(graph, component)].append(entry)

    def predict(self, graph, component):
        try:
            center, span, feature = public_layout(graph, component)
        except ValueError as error:
            return {'available': False, 'reason': str(error), 'policy': LAYOUT_POLICY}
        tiers = [('exact', self.exact.get(component_key(graph, component), [])),
                 ('role_layout', self.coarse.get(coarse_context(graph, component), []))]
        attempts = []
        for tier, entries in tiers:
            groups = defaultdict(list)
            for entry in entries:
                character = entry['candidate']['character']
                if character == graph.character:
                    continue
                distance = float(np.linalg.norm(entry['feature']-feature))
                if distance <= .5:
                    groups[character].append((distance, entry))
            characters = sorted(groups, key=lambda c: (min(d for d, _ in groups[c]), c))[:8]
            attempts.append({'tier': tier, 'reference_character_count': len(characters)})
            if len(characters) < 4:
                continue
            values, refs = [], []
            for character in characters:
                # One homologous public component per character; repeats share
                # that character's weight rather than adding independent votes.
                component_id = min(groups[character], key=lambda item: (
                    item[0], item[1]['candidate']['component_id']))[1]['candidate']['component_id']
                chosen = [e for _, e in groups[character] if e['candidate']['component_id'] == component_id]
                values.append(np.median([e['residual'] for e in chosen], axis=0))
                refs.extend(e['candidate'] for e in chosen)
            residual = np.median(values, axis=0)
            ratio = math.exp(float(residual[2]))
            detail = {'policy': LAYOUT_POLICY, 'tier': tier, 'attempts': attempts,
                'target_character_excluded': graph.character, 'reference_characters': characters,
                'reference_sources': refs, 'public_center': center.tolist(), 'public_span': span,
                'residual': residual.tolist(), 'span_ratio': ratio}
            if np.linalg.norm(residual[:2]) > .15 or not 2/3 <= ratio <= 1.5:
                return {**detail, 'available': False, 'reason': 'training residual exceeds declared layout limits'}
            return {**detail, 'available': True, 'center': (center+residual[:2]).tolist(), 'span': span*ratio}
        return {'policy': LAYOUT_POLICY, 'available': False,
                'reason': 'fewer than four nearby independent training characters', 'attempts': attempts,
                'target_character_excluded': graph.character}


def place_with_learned_layout(base, original, metadata, graph, component, sources, prediction, strength=0.):
    if not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('layout strength must be finite and in [0,1]')
    if strength == 0:
        return original, metadata
    detail = {'policy': LAYOUT_POLICY, 'strength': strength, 'prediction': prediction, 'applied': False}
    selected = metadata['selected']
    if selected is None or not prediction.get('available'):
        detail['fallback_reason'] = 'no original source donor or no layout evidence'
        return original, {**metadata, 'learned_layout': detail}
    target_ids = ordered_ids(graph, component)
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in target_ids]
    old_curves = [glyph_curves(original)[i] for i in indices]
    old_center, old_span, _ = layout_summary(old_curves)
    center = old_center+strength*(np.asarray(prediction['center'])-old_center)
    ratio = math.exp(strength*math.log(prediction['span']/old_span))
    old = selected['transform']
    transform = {'sx': old['sx']*ratio, 'sy': old['sy']*ratio,
                 'tx': center[0]+ratio*(old['tx']-old_center[0]),
                 'ty': center[1]+ratio*(old['ty']-old_center[1])}
    transform = {k: float(v) for k, v in transform.items()}
    record = {**selected, 'transform': transform}
    proposed, placed = source_component(base, target_ids, record, sources)
    errors = invariants(proposed, graph)
    crossings = crossing_pairs(glyph_curves(proposed))-crossing_pairs(glyph_curves(base))
    lengths = [path_length(s)/max(path_length(glyph_curves(base)[i]), 1e-9) for s, i in zip(placed, indices, strict=True)]
    detail.update({'original_transform': old, 'proposed_transform': transform, 'proposed_center': center.tolist(),
                   'proposed_span': old_span*ratio, 'errors': errors, 'new_crossings_vs_A': sorted(crossings),
                   'length_ratios_vs_A': lengths})
    if errors or crossings or min(lengths) < .4 or max(lengths) > 2.5:
        detail['fallback_reason'] = 'proposed complete component fails existing safety gates'
        return original, {**metadata, 'learned_layout': detail}
    detail.update(applied=True, fallback_reason=None)
    # Preserve original selection evidence, explicitly mark its score as referring
    # to the original placement. Donor selection has not been performed again.
    record['original_placement_score'] = record.pop('score')
    return proposed, {**metadata, 'selected': record, 'learned_layout': detail,
                      'score_semantics': 'donor and selection score frozen before layout correction'}
