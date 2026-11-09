"""Character-held-out evidence for an author's component shape variation."""
from __future__ import annotations

import hashlib
import json

import numpy as np

from .contextual_trajectory import anchors
from .geometry import path_length
from .terminal_selection import terminal_vector

EVIDENCE_POLICY = 'component_character_loo_shape_v1'
MIN_REFERENCE_CHARACTERS = 8


def normalized_component(curves):
    cloud = np.asarray([p for stroke in curves for p in stroke], dtype=float)
    low, high = cloud.min(0), cloud.max(0)
    span = float((high - low).max())
    if span < 1e-9 or not np.isfinite(cloud).all():
        raise ValueError('invalid component for variation evidence')
    center = (low + high) / 2
    return [((np.asarray(stroke) - center) / span).tolist() for stroke in curves]


def shape_descriptor(curves):
    normalized = normalized_component(curves)
    body = anchors(normalized, 16).reshape(-1)
    directions, lengths = [], []
    for stroke in normalized:
        length = path_length(stroke)
        lengths.append(length)
        for fraction in (.08, .20):
            direction = terminal_vector(stroke, min(.08, fraction * length))
            directions.extend(direction if direction is not None else [0., 0.])
    body = body / np.sqrt(len(body))
    directions = .2 * np.asarray(directions) / np.sqrt(len(directions))
    lengths = .2 * np.asarray(lengths) / np.sqrt(len(lengths))
    return np.concatenate([body, directions, lengths])


def shape_identity(curves):
    values = np.round(anchors(normalized_component(curves), 64), 8).tolist()
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


class ComponentVariationEvidence:
    """Fit character-disjoint nearest-neighbor ranges within exact writer/context.

    Target-character captures are removed before reference counts, deduplication,
    calibration or scoring. Generated source examples are assessed with their
    own donor character excluded as well, so copying a training exemplar cannot
    receive a tautological zero-distance score.
    """
    def __init__(self, index):
        self.groups = {}
        self.cache = {}
        for context, candidates in index.by_key.items():
            entries = []
            for candidate in candidates:
                source = index.sources[candidate['sample_id']]
                mapping = {s.standard_stroke_id: s.points for s in source.strokes}
                curves = [mapping[sid] for sid in candidate['stroke_ids']]
                entries.append({'candidate': candidate, 'descriptor': shape_descriptor(curves),
                                'shape_id': shape_identity(curves)})
            self.groups[context] = entries

    def cohort(self, context, target_character):
        key = context, target_character
        if key in self.cache:
            return self.cache[key]
        entries = [e for e in self.groups.get(context, []) if e['candidate']['character'] != target_character]
        # Copies do not add evidence, even when sample IDs or timestamps differ.
        unique = {}
        for entry in sorted(entries, key=lambda e: (e['candidate']['character'], e['candidate']['sample_id'])):
            unique.setdefault(entry['shape_id'], entry)
        entries = list(unique.values())
        characters = {e['candidate']['character'] for e in entries}
        data = {'policy': EVIDENCE_POLICY, 'reference_characters': len(characters),
                'distinct_shapes': len(entries), 'target_character_excluded': target_character,
                'available': len(characters) >= MIN_REFERENCE_CHARACTERS, 'threshold': None}
        if not data['available']:
            data['reason'] = 'fewer than 8 independent source characters with distinct shapes'
            result = entries, data
        else:
            values = np.asarray([e['descriptor'] for e in entries])
            distances = np.linalg.norm(values[:, None] - values[None, :], axis=2)
            same_character = np.asarray([[a['candidate']['character'] == b['candidate']['character']
                                         for b in entries] for a in entries])
            distances[same_character] = np.inf
            nearest = distances.min(axis=1)
            # One score per source character prevents repeated captures from
            # making one character count as many independent calibration units.
            per_character = [float(np.median([nearest[i] for i, e in enumerate(entries)
                if e['candidate']['character'] == c])) for c in sorted(characters)]
            data['threshold'] = max(float(np.quantile(per_character, .95)), 1e-10)
            data['calibration_scores'] = per_character
            result = entries, data
        self.cache[key] = result
        return result

    def assess(self, context, target_character, curves, *, donor_character=None):
        entries, data = self.cohort(context, target_character)
        result = {k: v for k, v in data.items() if k != 'calibration_scores'}
        if not data['available']:
            return result
        descriptor = shape_descriptor(curves)
        query_identity = shape_identity(curves)
        refs = [e for e in entries if e['candidate']['character'] != donor_character
                and (donor_character is None or e['shape_id'] != query_identity)]
        if not refs:
            result.update(available=False, reason='no independent non-copy reference')
            return result
        distance = min(float(np.linalg.norm(e['descriptor'] - descriptor)) for e in refs)
        result.update({'nearest_other_character_distance': distance,
                       'donor_character_excluded_from_scoring': donor_character,
                       'within_empirical_range': distance <= data['threshold'],
                       'range_ratio': distance / data['threshold'],
                       'interpretation': 'component-shape compatibility with this author/context, not a calibrated aesthetic probability'})
        return result
