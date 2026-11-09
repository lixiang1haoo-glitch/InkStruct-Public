"""Inference-only stroke geometry evidence for fixed whole-component moves."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .counterfactual_layout_risk import CounterfactualLayoutRiskGate
from .topology_repair import glyph_curves
from .trajectory_experiment import stroke_metrics

METRICS = ('mean_distance', 'max_distance', 'endpoint_error', 'terminal_angle_deg', 'absolute_length_error', 'startpoint_error')
SCALES = np.asarray([.05, .05, .05, 30., .25, .05])


def stroke_geometry_features(base, original, proposed, target_ids):
    """D/A and P/A comparisons only; never accepts a target capture."""
    sequence = [s.standard_stroke_id for s in base.strokes]
    if any([s.standard_stroke_id for s in g.strokes] != sequence for g in (original, proposed)):
        raise ValueError('standard stroke IDs/order must match')
    if not target_ids or len(set(target_ids)) != len(target_ids) or not set(target_ids) <= set(sequence):
        raise ValueError('invalid target stroke IDs')
    a, d, p = [glyph_curves(g) for g in (base, original, proposed)]
    evidence, before, after = {}, [], []
    for i, sid in enumerate(sequence):
        if sid not in target_ids:
            continue
        rows = []
        for lines in (a, d, p):
            points = np.asarray(lines[i])
            if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
                raise ValueError('finite stroke polylines required')
        for lines in (d, p):
            metrics = stroke_metrics(lines[i], a[i])
            metrics['startpoint_error'] = float(np.linalg.norm(np.asarray(lines[i][0])-a[i][0]))
            rows.append({key: metrics[key] for key in METRICS})
        evidence[sid] = {'D_vs_A': rows[0], 'P_vs_A': rows[1]}
        before.append([rows[0][key] for key in METRICS])
        after.append([rows[1][key] for key in METRICS])
    x, y = np.asarray(before)/SCALES, np.asarray(after)/SCALES
    delta = y-x
    features = np.r_[x.mean(0), x.max(0), delta.mean(0), delta.max(0)]
    if not np.isfinite(features).all():
        raise ValueError('nonfinite geometry risk features')
    return features.tolist(), evidence


class TrajectoryLayoutRiskGate(CounterfactualLayoutRiskGate):
    """Keep old and new feature blocks separately weighted, one grouped vote."""
    def predict(self, writer, character, features, *, scope='author', threshold=.8, geometry_weight=.5):
        if scope not in ('author', 'pooled') or not 0 <= threshold <= 1 or not 0 <= geometry_weight <= 1:
            raise ValueError('invalid gate scope, threshold or geometry weight')
        groups = defaultdict(list)
        for e in self.examples:
            if e['character'] != character and (scope == 'pooled' or e['writer'] == writer):
                groups[e['writer'], e['character']].append(e)
        detail = {'policy': 'trajectory_layout_risk_v1', 'scope': scope, 'threshold': threshold,
                  'geometry_weight': geometry_weight, 'accepted': False, 'available': False,
                  'reference_count': len(groups), 'component_reference_count': sum(map(len, groups.values()))}
        if len(groups) < 5:
            return {**detail, 'reason': 'fewer than five grouped changed training characters'}
        query = np.asarray(features)
        refs = [e for group in groups.values() for e in group]
        x = np.asarray([e['features'] for e in refs])
        if x.ndim != 2 or x.shape[1] != 46 or query.shape != (46,) or not np.isfinite(x).all() or not np.isfinite(query).all():
            raise ValueError('expected 22 layout plus 24 finite geometry features')
        centers = np.asarray([np.median([e['features'] for e in group], axis=0) for group in groups.values()])
        scale = np.maximum(np.quantile(centers, .75, axis=0)-np.quantile(centers, .25, axis=0), .1)
        nearest = []
        for group in groups.values():
            scored = []
            for e in group:
                z = (np.asarray(e['features'])-query)/scale
                layout = float(np.mean(z[:22]**2))
                geometry = float(np.mean(z[22:]**2))
                # Weight zero exactly recovers the old metric: adding dimensions
                # must not silently dilute its distance or support threshold.
                distance = float(np.sqrt(layout if geometry_weight == 0 else
                    geometry if geometry_weight == 1 else (1-geometry_weight)*layout+geometry_weight*geometry))
                scored.append({**e, 'distance': distance})
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
