"""Batch descriptor acceleration for the opt-in author stroke experiment.

Same buckets, isotropic fit, score and admission limits as AuthorStrokeFallback.
Only retrieval descriptors are vectorized; output retains every source vertex.
"""
from collections import Counter
from dataclasses import asdict

import numpy as np

from .contextual_trajectory import anchors
from .geometry import path_length
from .trajectory_experiment import SharedTransform, crossing_pairs
from .v61_author_strokes import (
    PARAMETERS,
    AuthorStrokeFallback,
    falling_without_uphook,
    stroke_class,
)
from .v61_contacts import contact_pairs


class BatchAuthorStrokeFallback(AuthorStrokeFallback):
    def __init__(self, *args):
        super().__init__(*args)
        self.descriptors = {}
        for kind, entries in self.pool.items():
            x = np.asarray([anchors([s.points]) for _, s, _ in entries])
            mean = x.mean(axis=1)
            centered = x - mean[:, None, :]
            self.descriptors[kind] = {
                'x': x, 'mean': mean, 'centered': centered, 'denominator': (centered ** 2).sum(axis=(1, 2)),
                'length': np.asarray([path_length(s.points) for _, s, _ in entries]),
                'first': np.asarray([s.points[0] for _, s, _ in entries]),
                'last': np.asarray([s.points[-1] for _, s, _ in entries]),
                'low': np.asarray([np.min(s.points, axis=0) for _, s, _ in entries]),
                'high': np.asarray([np.max(s.points, axis=0) for _, s, _ in entries]),
                'pie': np.asarray([falling_without_uphook(s.points) if kind == 'pie' else True for _, s, _ in entries]),
                'confidence': np.asarray([s.confidence for _, s, _ in entries])}

    def select(self, graph, index, current, reference, *, start_anchor=None):
        target = reference[index]
        kind = stroke_class(graph.strokes[index].median)
        entries = self.pool[kind]
        d = self.descriptors.get(kind)
        rejected = Counter()
        ranked = []
        if d is not None:
            y = anchors([target]); ym = y.mean(axis=0)
            scale = np.sum(d['centered'] * (y - ym), axis=(1, 2)) / np.maximum(d['denominator'], 1e-300)
            offset = ym - scale[:, None] * d['mean']
            if start_anchor is not None:
                offset = np.asarray(start_anchor) - scale[:, None] * d['first']
            ratio = scale * d['length'] / max(path_length(target), 1e-9)
            first = scale[:, None] * d['first'] + offset
            last = scale[:, None] * d['last'] + offset
            ends = np.maximum(np.linalg.norm(first-target[0], axis=1), np.linalg.norm(last-target[-1], axis=1))
            low = scale[:, None] * d['low'] + offset
            high = scale[:, None] * d['high'] + offset
            scores = np.linalg.norm(scale[:, None, None] * d['x'] + offset[:, None, :] - y, axis=2).mean(axis=1) + .01*(1-d['confidence'])
            for n, (sample, source, _) in enumerate(entries):
                reason = None
                if sample.character == graph.character:
                    reason = 'same character'
                elif not d['pie'][n]:
                    reason = 'actual source not pie'
                elif d['denominator'][n] < 1e-12 or scale[n] <= 1e-8:
                    reason = 'fit'
                elif not PARAMETERS['length_ratio'][0] <= ratio[n] <= PARAMETERS['length_ratio'][1]:
                    reason = 'length ratio'
                elif ends[n] > PARAMETERS['max_endpoint_error'] or np.any(low[n] < 0) or np.any(high[n] > 1):
                    reason = 'bounds or endpoints'
                if reason:
                    rejected[reason] += 1
                else:
                    ranked.append((float(scores[n]), sample.sample_id, source.standard_stroke_id, n))
        ranked.sort()
        support = {}
        for score, _, _, n in ranked[:PARAMETERS['max_candidates']]:
            sample, source, _ = entries[n]
            transform = SharedTransform(float(scale[n]), float(scale[n]), *map(float, offset[n]))
            placed = transform.apply(source.points)
            unsupported = False
            for j in range(len(current)):
                if j == index:
                    continue
                if j not in support:
                    old, ref = [current[index], current[j]], [reference[index], reference[j]]
                    support[j] = (bool(crossing_pairs(old) or crossing_pairs(ref)),
                                  bool(contact_pairs(old) or contact_pairs(ref)))
                cross, contact = support[j]
                after = [placed, current[j]]
                if ((not cross and crossing_pairs(after)) or (not contact and contact_pairs(after))):
                    unsupported = True
                    break
            if unsupported:
                rejected['new unsupported crossing/contact'] += 1
                continue
            evidence = {'kind': 'author_single_stroke', 'character': sample.character,
                'sample_id': sample.sample_id, 'source_sha256': sample.source_sha256,
                'source_stroke_id': source.standard_stroke_id, 'target_stroke_id': graph.strokes[index].stroke_id,
                'mapping_confidence': source.confidence, 'content_bucket': kind,
                'transform': asdict(transform), 'placement_score': score,
                'source_point_count': len(source.points), 'rejections': dict(rejected)}
            return {'points': placed, 'pressure': source.pressure, 'time': source.t_ms}, evidence
        return None, {'target_stroke_id': graph.strokes[index].stroke_id, 'content_bucket': kind,
                      'eligible_geometry': len(ranked), 'reason': 'no admitted author stroke',
                      'rejections': dict(rejected)}
