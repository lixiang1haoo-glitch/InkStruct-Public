"""Whole-source exemplar index, including validated optional nested views."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from ..component_style import component_context_key
from .component_views import expand_views
from ..geometry import bbox, resample
from .trace import Donor, emit, observer


def ordered_ids(graph, component):
    selected = set(component.stroke_ids)
    return [s.stroke_id for s in graph.strokes if s.stroke_id in selected]


def component_key(graph, component):
    return component_context_key(graph, component) + f'|{len(component.stroke_ids)}'


def shape_descriptor(graph, component):
    mapping = {s.stroke_id: s for s in graph.strokes}
    points = [resample(mapping[k].median, 16) for k in ordered_ids(graph, component)]
    box = bbox([p for s in points for p in s])
    center = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
    span = max(box[2] - box[0], box[3] - box[1], 1e-9)
    return (np.asarray(points) - center) / span


class ExemplarIndex:
    def __init__(self, profile, repository, *, nested_views=False, allowed_characters=None):
        self.writer_id = profile.writer_id
        self.sources = profile.source_trajectories
        self.repository = repository
        self.nested_views = nested_views
        self.graphs = {}
        self.by_key = defaultdict(list)
        for sample in self.sources.values():
            if allowed_characters is not None and sample.character not in allowed_characters:
                continue
            graph = self.graph(sample.character)
            stroke_map = {s.standard_stroke_id: s for s in sample.strokes}
            for component in graph.components:
                if component.path == 'root' or component.children_ids or len(component.stroke_ids) < 2 or component.confidence < .8:
                    continue
                ids = ordered_ids(graph, component)
                confidence = float(np.mean([stroke_map[k].confidence for k in ids]))
                box = bbox([p for k in ids for p in stroke_map[k].points])
                if confidence < .55 or min(box[2] - box[0], box[3] - box[1]) < 1e-5:
                    continue
                self.by_key[component_key(graph, component)].append({
                    'character': sample.character, 'sample_id': sample.sample_id,
                    'source_sha256': sample.source_sha256, 'component_id': component.component_id,
                    'stroke_ids': ids, 'confidence': confidence})

    def graph(self, character):
        if character not in self.graphs:
            graph = self.repository.get(character)
            self.graphs[character] = expand_views(graph, self.repository).graph if self.nested_views else graph
        return self.graphs[character]

    def candidates(self, graph, component):
        target_features = _reference_target_features(graph, component)
        candidates = []
        index = component_key(graph, component)
        entries = self.by_key.get(index, [])
        sink = observer()
        target = tuple(ordered_ids(graph, component)) if sink is not None else ()
        if sink is not None:
            emit(sink, 'component context', 'retrieval', 'found' if entries else 'no candidates',
                 index=index, target=target, count=len(entries))
        for entry in entries:
            donor = None
            if sink is not None:
                donor = Donor(self.writer_id, entry['character'], entry['sample_id'], entry['source_sha256'],
                              tuple(entry['stroke_ids']), target)
            if entry['character'] == graph.character:
                if sink is not None:
                    emit(sink, 'component context', 'admission', 'rejected', donor=donor, reason='same character')
                continue
            source = self.graph(entry['character'])
            source_component = next(n for n in source.components if n.component_id == entry['component_id'])
            shape, aspect_error = reference_compatibility(
                graph, component, source, source_component, target_features=target_features)
            rejected = shape > .18 or aspect_error > .7
            if sink is not None:
                emit(sink, 'component context', 'admission', 'rejected' if rejected else 'accepted',
                     donor=donor, shape=shape, aspect=aspect_error, max_shape=.18, max_aspect=.7)
            if rejected:
                continue
            candidates.append({**entry, 'score': shape + .1 * aspect_error + .03 * (1 - entry['confidence']),
                               'standard_shape_error': shape, 'standard_log_aspect_error': aspect_error})
        return sorted(candidates, key=lambda c: (c['score'], c['sample_id'], c['component_id']))


def _reference_target_features(graph, component):
    descriptor = shape_descriptor(graph, component)
    box = component.bbox
    aspect = max(box[2] - box[0], 1e-8) / max(box[3] - box[1], 1e-8)
    return descriptor, aspect


def reference_compatibility(graph, component, source, source_component, *, target_features=None):
    """Existing reference-only filter features; not predicted author usability."""
    descriptor, aspect = (_reference_target_features(graph, component)
                          if target_features is None else target_features)
    shape = float(np.linalg.norm(shape_descriptor(source, source_component) - descriptor, axis=2).mean())
    box = source_component.bbox
    source_aspect = max(box[2] - box[0], 1e-8) / max(box[3] - box[1], 1e-8)
    return shape, abs(math.log(source_aspect / aspect))
