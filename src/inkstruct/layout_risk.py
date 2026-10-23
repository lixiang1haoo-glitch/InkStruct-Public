"""Experimental paired-outcome gate for whole-component layout moves."""
from __future__ import annotations

import hashlib
import math

import numpy as np

from .alignment import _normalise_glyph_extent
from .geometry import bbox
from .learned_component_layout import layout_summary, public_layout
from .topology_repair import glyph_curves


def training_fold(character):
    """All writers and repeats of a character share one deterministic fold."""
    return int(hashlib.sha256(('layout-risk-v1:'+character).encode()).hexdigest()[:8], 16) % 3


def _relation(selected, other):
    a, b = np.asarray(bbox(selected)), np.asarray(bbox(other))
    centers = (a[:2]+a[2:]-b[:2]-b[2:])/2
    # Positive gap = separation; negative gap = projected overlap.
    gap = np.maximum(a[:2]-b[2:], b[:2]-a[2:])
    return np.r_[centers, gap]


def move_features(graph, component, original, proposed, prediction, band):
    """No target capture argument: only public structure and frozen generation."""
    ids = set(component.stroke_ids)
    selected = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
    outside = [i for i, s in enumerate(graph.strokes) if s.stroke_id not in ids]
    if not outside:
        raise ValueError('layout risk requires another component')
    d, m = glyph_curves(original), glyph_curves(proposed)
    dc, ds, _ = layout_summary([d[i] for i in selected])
    mc, ms, _ = layout_summary([m[i] for i in selected])
    pc, ps, public_feature = public_layout(graph, component)
    public = _normalise_glyph_extent([s.median for s in graph.strokes])
    # Nearest disjoint public leaf, selected without source handwriting.
    neighbors = [c for c in graph.components if not c.children_ids and set(c.stroke_ids).isdisjoint(ids) and c.stroke_ids]
    if not neighbors:
        neighbor_ids = {graph.strokes[i].stroke_id for i in outside}
    else:
        def distance(c):
            points = [p for i, s in enumerate(graph.strokes) if s.stroke_id in c.stroke_ids for p in public[i]]
            box = np.asarray(bbox(points))
            return float(np.linalg.norm((box[:2]+box[2:])/2-pc)), c.component_id
        neighbor_ids = set(min(neighbors, key=distance).stroke_ids)
    adjacent = [i for i, s in enumerate(graph.strokes) if s.stroke_id in neighbor_ids]
    flat = lambda lines, indices: [p for i in indices for p in lines[i]]
    public_relation = _relation(flat(public, selected), flat(public, adjacent))
    old_relation = _relation(flat(d, selected), flat(d, adjacent))
    new_relation = _relation(flat(m, selected), flat(m, adjacent))
    features = np.r_[public_feature, (dc-pc)/.1, math.log(ds/ps)/.25,
        (mc-dc)/.05, math.log(ms/ds)/.15,
        band.get('distance_before', 0.)/max(band.get('radius', 1.), 1e-9),
        band.get('effective_strength', 0.), float(prediction.get('tier') == 'exact'),
        (old_relation-public_relation)/.1, (new_relation-old_relation)/.05]
    if not np.isfinite(features).all():
        raise ValueError('nonfinite layout risk features')
    return features.tolist()


class LayoutRiskGate:
    """Nearest paired training outcomes, never a naturalness probability."""
    def __init__(self, examples):
        identities = [(e['writer'], e['character']) for e in examples]
        if len(set(identities)) != len(identities):
            raise ValueError('one grouped training outcome per writer and character required')
        self.examples = examples

    def predict(self, writer, character, features, *, scope='author', threshold=.8):
        if scope not in ('author', 'pooled') or not 0 <= threshold <= 1:
            raise ValueError('invalid gate scope or threshold')
        refs = [e for e in self.examples if e['character'] != character and (scope == 'pooled' or e['writer'] == writer)]
        detail = {'policy': 'crossfit_layout_risk_v1', 'scope': scope, 'threshold': threshold,
                  'accepted': False, 'available': False, 'reference_count': len(refs)}
        if len(refs) < 5:
            return {**detail, 'reason': 'fewer than five independent changed training characters'}
        x, query = np.asarray([e['features'] for e in refs]), np.asarray(features)
        if x.ndim != 2 or query.shape != x.shape[1:] or not np.isfinite(x).all() or not np.isfinite(query).all():
            raise ValueError('invalid risk feature shape or values')
        scale = np.maximum(np.quantile(x, .75, axis=0)-np.quantile(x, .25, axis=0), .1)
        distances = np.sqrt(np.mean(((x-query)/scale)**2, axis=1))
        order = sorted(range(len(refs)), key=lambda i: (distances[i], refs[i]['writer'], refs[i]['character']))[:8]
        neighbors = [{**refs[i], 'distance': float(distances[i])} for i in order if distances[i] <= 2.]
        detail['neighbors'] = neighbors
        if len(neighbors) < 5:
            return {**detail, 'reason': 'fewer than five nearby paired outcomes'}
        fraction = float(np.mean([r['safe_benefit'] for r in neighbors]))
        ratio = float(np.mean([r['geometry_ratio'] for r in neighbors]))
        accepted = fraction >= threshold and ratio < 1.
        return {**detail, 'available': True, 'accepted': accepted, 'safe_fraction': fraction,
                'mean_geometry_ratio': ratio, 'reason': 'training outcomes support move' if accepted else 'paired training risk rejects move'}
