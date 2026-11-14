"""Rank and place author strokes with the v6.3.1 fallback policy."""
from collections import Counter
from dataclasses import asdict

import numpy as np

from ..contextual_trajectory import anchors
from .placement import split_relationship_details, split_relationship_failure
from .trace import Donor, emit, observer
from ..geometry import path_length
from ..trajectory_experiment import SharedTransform
from .stroke_sources import (
    PARAMETERS,
    StrokeSources,
    falling_without_uphook,
    stroke_class,
)


def direction_bucket(pool, descriptors, kind):
    return pool[kind], descriptors.get(kind)


def admit_split_candidate(sample, target_character, actual_form_matches):
    if sample.character == target_character:
        return 'same character'
    if not actual_form_matches:
        return 'actual source not pie'
    return None


def rank_placement_reason(descriptors, n, scale, ratio, ends, low, high):
    if descriptors['denominator'][n] < 1e-12 or scale[n] <= 1e-8:
        return 'fit'
    if not PARAMETERS['length_ratio'][0] <= ratio[n] <= PARAMETERS['length_ratio'][1]:
        return 'length ratio'
    if ends[n] > PARAMETERS['max_endpoint_error'] or np.any(low[n] < 0) or np.any(high[n] > 1):
        return 'bounds or endpoints'
    return None


def split_donor(writer, sample, source, slot):
    return Donor(writer, sample.character, sample.sample_id, sample.source_sha256,
                 (source.standard_stroke_id,), (slot,))


class StrokePlacement(StrokeSources):
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
        entries, d = direction_bucket(self.pool, self.descriptors, kind)
        sink = observer()
        slot = graph.strokes[index].stroke_id
        if sink is not None:
            emit(sink, 'single', 'retrieval', 'found' if entries else 'no candidates',
                 target=slot, index=kind, count=len(entries),
                 budget=PARAMETERS['max_candidates'])
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
                reason = admit_split_candidate(sample, graph.character, d['pie'][n])
                stage = 'admission'
                if not reason:
                    stage = 'placement precheck'
                    reason = rank_placement_reason(d, n, scale, ratio, ends, low, high)
                if reason:
                    rejected[reason] += 1
                else:
                    ranked.append((float(scores[n]), sample.sample_id, source.standard_stroke_id, n))
                if sink is not None:
                    donor = split_donor(self.profile.writer_id, sample, source, slot)
                    if stage == 'placement precheck':
                        emit(sink, 'single', 'admission', 'accepted', donor=donor, ordinal=n + 1)
                        emit(sink, 'single', stage, 'rejected' if reason else 'accepted',
                             donor=donor, ordinal=n + 1, reason=reason, scale=float(scale[n]),
                             offset=offset[n].tolist(), length_ratio=float(ratio[n]),
                             endpoint_error=float(ends[n]), endpoint_limit=PARAMETERS['max_endpoint_error'],
                             endpoint_failed=bool(ends[n] > PARAMETERS['max_endpoint_error']),
                             bounds_failed=bool(np.any(low[n] < 0) or np.any(high[n] > 1)),
                             length_ratio_limits=PARAMETERS['length_ratio'],
                             low=low[n].tolist(), high=high[n].tolist(), score=float(scores[n]))
                    else:
                        emit(sink, 'single', stage, 'rejected', donor=donor, ordinal=n + 1, reason=reason)
        ranked.sort()
        budget = PARAMETERS['max_candidates']
        if sink is not None:
            emit(sink, 'single', 'ranking', 'ordered', target=slot, budget=budget,
                 order=[{'donor': asdict(split_donor(self.profile.writer_id, entries[n][0], entries[n][1], slot)), 'score': score}
                        for score, _, _, n in ranked])
        support = {}
        attempted = 0
        for score, _, _, n in ranked[:budget]:
            attempted += 1
            sample, source, _ = entries[n]
            transform = SharedTransform(float(scale[n]), float(scale[n]), *map(float, offset[n]))
            placed = transform.apply(source.points)
            failure = split_relationship_failure(placed, index, current, reference, support)
            unsupported = failure is not None
            if sink is not None:
                emit(sink, 'single', 'placement', 'rejected' if unsupported else 'accepted',
                     donor=split_donor(self.profile.writer_id, sample, source, slot), attempt=attempted, transform=asdict(transform),
                     first_failure={'relation': failure[0], 'neighbor_order': failure[1] + 1}
                     if failure else None,
                     supplemental_relationships=split_relationship_details(placed, index, current, reference))
            if unsupported:
                rejected['new unsupported crossing/contact'] += 1
                continue
            evidence = {'kind': 'author_single_stroke', 'character': sample.character,
                'sample_id': sample.sample_id, 'source_sha256': sample.source_sha256,
                'source_stroke_id': source.standard_stroke_id, 'target_stroke_id': graph.strokes[index].stroke_id,
                'mapping_confidence': source.confidence, 'content_bucket': kind,
                'transform': asdict(transform), 'placement_score': score,
                'source_point_count': len(source.points), 'rejections': dict(rejected)}
            if sink is not None:
                emit(sink, 'single', 'decision', 'adopted', donor=split_donor(self.profile.writer_id, sample, source, slot),
                     attempted=attempted, eligible=len(ranked), untried=len(ranked) - attempted,
                     stop='first accepted placement')
            return {'points': placed, 'pressure': source.pressure, 'time': source.t_ms}, evidence
        if sink is not None:
            emit(sink, 'single', 'decision', 'reference', target=slot, retrieved=len(entries),
                 attempted=attempted, eligible=len(ranked), untried=len(ranked) - attempted,
                 stop=('budget exhausted' if len(ranked) > budget else
                       'all ranked placements rejected' if ranked else
                       'all candidates rejected before ranking' if entries else 'no candidates'))
        return None, {'target_stroke_id': graph.strokes[index].stroke_id, 'content_bucket': kind,
                      'eligible_geometry': len(ranked), 'reason': 'no admitted author stroke',
                      'rejections': dict(rejected)}
