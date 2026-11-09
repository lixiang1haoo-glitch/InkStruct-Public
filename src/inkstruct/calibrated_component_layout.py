"""Training-character calibration of an empirical layout reference band."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .learned_component_layout import (
    ComponentLayoutEvidence,
    layout_summary,
    place_with_learned_layout,
)
from .topology_repair import glyph_curves


class CalibratedComponentLayoutEvidence(ComponentLayoutEvidence):
    def __init__(self, index):
        super().__init__(index)
        self.index = index
        self.lookup = {(e['candidate']['sample_id'], e['candidate']['component_id']): e
                       for entries in self.exact.values() for e in entries}

    def predict(self, graph, component):
        prediction = super().predict(graph, component)
        if not prediction.get('available'):
            return prediction
        groups = defaultdict(list)
        for candidate in prediction['reference_sources']:
            groups[candidate['character']].append(self.lookup[candidate['sample_id'], candidate['component_id']]['residual'])
        values = np.asarray([np.median(rows, axis=0) for rows in groups.values()])
        dispersion = 1.4826*np.median(abs(values-np.asarray(prediction['residual'])), axis=0)
        prediction['response_dispersion'] = np.maximum(dispersion, [.01, .01, .05]).tolist()
        return prediction

    def calibrate(self):
        """Character leave-one-out only on indexed training captures.

        Repeats are aggregated within each component, then the maximum component
        score represents that character. The upper empirical 90th percentile is
        a reference band, not a calibrated coverage promise for future glyphs.
        """
        groups = defaultdict(list)
        excluded = []
        for entry in self.lookup.values():
            candidate = entry['candidate']
            graph = self.index.graph(candidate['character'])
            component = next(c for c in graph.components if c.component_id == candidate['component_id'])
            prediction = self.predict(graph, component)
            if not prediction.get('available'):
                excluded.append({'candidate': candidate, 'reason': prediction['reason']})
                continue
            assert graph.character not in prediction['reference_characters']
            z = (entry['residual']-np.asarray(prediction['residual']))/prediction['response_dispersion']
            groups[graph.character, component.component_id].append(float(np.linalg.norm(z)))
        characters = defaultdict(list)
        for (character, _), values in groups.items():
            characters[character].append(float(np.median(values)))
        scores = {character: max(values) for character, values in characters.items()}
        available = len(scores) >= 12
        return {'policy': 'training_character_loo_layout_band_v1', 'available': available,
                'character_scores': scores, 'reference_character_count': len(scores), 'quantile': .90,
                'radius': float(np.quantile(list(scores.values()), .90, method='higher')) if available else None,
                'excluded': excluded,
                'interpretation': 'empirical training reference band; no guaranteed future coverage or aesthetic probability'}


def place_with_calibrated_layout(base, original, metadata, graph, component, sources, prediction, calibration, strength=0.):
    if not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('layout strength must be finite and in [0,1]')
    if strength == 0:
        return original, metadata
    if not calibration.get('available') or not prediction.get('available') or metadata['selected'] is None:
        return original, {**metadata, 'layout_band': {'applied': False, 'reason': 'insufficient calibration, prediction or donor'}}
    ids = set(component.stroke_ids)
    selected = [s for s, stroke in zip(glyph_curves(original), original.strokes, strict=True) if stroke.standard_stroke_id in ids]
    center, span, _ = layout_summary(selected)
    residual = np.r_[center-np.asarray(prediction['center']), np.log(span/prediction['span'])]
    distance = float(np.linalg.norm(residual/prediction['response_dispersion']))
    fraction = max(0., 1-calibration['radius']/max(distance, 1e-12))
    effective = strength*fraction
    detail = {'radius': calibration['radius'], 'distance_before': distance, 'nominal_strength': strength,
              'effective_strength': effective, 'reference_characters': calibration['reference_character_count'],
              'interpretation': calibration['interpretation']}
    if effective == 0:
        return original, {**metadata, 'layout_band': {**detail, 'applied': False, 'reason': 'original placement within training reference band'}}
    output, result = place_with_learned_layout(base, original, metadata, graph, component, sources, prediction, effective)
    applied = result.get('learned_layout', {}).get('applied', False)
    return output, {**result, 'layout_band': {**detail, 'applied': applied,
        'reason': 'move toward training band boundary' if applied else 'existing safety gate rejected adjusted placement'}}
