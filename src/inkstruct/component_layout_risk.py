"""Grouped risk evidence from every compatible crossfit component."""
from __future__ import annotations

from collections import defaultdict

import numpy as np


class ComponentLayoutRiskGate:
    """One nearest component vote per author-character, irrespective of count."""
    def __init__(self, examples):
        keys = [(e['writer'], e['character'], e['component_id']) for e in examples]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate author-character-component training outcome')
        self.examples = examples

    def predict(self, writer, character, features, *, scope='author', threshold=.8):
        if scope not in ('author', 'pooled') or not 0 <= threshold <= 1:
            raise ValueError('invalid gate scope or threshold')
        groups = defaultdict(list)
        for e in self.examples:
            if e['character'] != character and (scope == 'pooled' or e['writer'] == writer):
                groups[e['writer'], e['character']].append(e)
        detail = {'policy': 'all_component_layout_risk_v1', 'scope': scope, 'threshold': threshold,
                  'accepted': False, 'available': False, 'reference_count': len(groups),
                  'component_reference_count': sum(map(len, groups.values()))}
        if len(groups) < 5:
            return {**detail, 'reason': 'fewer than five grouped changed training characters'}
        query = np.asarray(features)
        refs = [e for group in groups.values() for e in group]
        x = np.asarray([e['features'] for e in refs])
        if x.ndim != 2 or query.shape != x.shape[1:] or not np.isfinite(x).all() or not np.isfinite(query).all():
            raise ValueError('invalid risk feature shape or values')
        # Each author-character has equal influence on feature scales, even when
        # it has several component observations. Query characters are excluded first.
        centers = np.asarray([np.median([e['features'] for e in group], axis=0) for group in groups.values()])
        scale = np.maximum(np.quantile(centers, .75, axis=0)-np.quantile(centers, .25, axis=0), .1)
        nearest = []
        for group in groups.values():
            scored = [{**e, 'distance': float(np.sqrt(np.mean(((np.asarray(e['features'])-query)/scale)**2)))} for e in group]
            nearest.append(min(scored, key=lambda e: (e['distance'], e['component_id'])))
        neighbors = [e for e in sorted(nearest, key=lambda e: (e['distance'], e['writer'], e['character']))[:8] if e['distance'] <= 2.]
        detail['neighbors'] = neighbors
        if len(neighbors) < 5:
            return {**detail, 'reason': 'fewer than five nearby grouped outcomes'}
        fraction = float(np.mean([e['safe_benefit'] for e in neighbors]))
        ratio = float(np.mean([e['geometry_ratio'] for e in neighbors]))
        accepted = fraction >= threshold and ratio < 1.
        return {**detail, 'available': True, 'accepted': accepted, 'safe_fraction': fraction,
                'mean_geometry_ratio': ratio, 'reason': 'grouped training outcomes support move' if accepted else 'grouped training risk rejects move'}
