"""Versioned, opt-in reference corrections; upstream and captured data stay intact."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from .geometry import bbox, stroke_signature
from .outline_median import flatten_outline, propose_strip_median
from .samples import sha256_file
from .structure_defects import record_hash
from .structures import _component_bbox, _normalise_median, _relations

POLICY = 'unclipped_reference_overlay_v1'


class CorrectedStructureRepository:
    """Restore raw geometry in the legacy frame, avoiding a coordinate-origin confound.

    Unbounded reference coordinates are intentional. Generated output must still
    pass its existing whole-glyph canvas adaptation and protocol checks.
    """
    def __init__(self, base, graphics_path, dictionary_path, config_path):
        self.base, self.path = base, base.path
        config = json.loads(Path(config_path).read_text(encoding='utf-8'))
        if config['policy'] != POLICY:
            raise ValueError('unsupported structure correction policy')
        self.config = config
        for path, expected in [(graphics_path, config['graphics_sha256']), (dictionary_path, config['dictionary_sha256'])]:
            if sha256_file(Path(path)) != expected:
                raise ValueError('upstream source hash mismatch')
        if base.content_sha256() != config['database_content_sha256']:
            raise ValueError('base structure database differs from frozen source')
        with Path(graphics_path).open(encoding='utf-8') as stream:
            self.graphics = {r['character']: r for r in map(json.loads, stream)}
        self.outline_rules = {(r['character'], r['stroke_id']): r for r in config['outline_repairs']}
        self.identity = {'policy': POLICY, 'config_sha256': sha256_file(Path(config_path)),
            'base_content_sha256': config['database_content_sha256'],
            'implementation_sha256': {name: sha256_file(Path(__file__).with_name(name+'.py'))
                for name in ('structure_corrections', 'structures', 'geometry', 'outline_median')}}
        self.digest = record_hash(self.identity)
        self.version = base.metadata().get('source_version', 'unknown')+'+'+POLICY+'-'+self.digest[:12]
        self.events = {}
        self._cache = {}

    def get(self, character):
        if character in self._cache:
            return copy.deepcopy(self._cache[character])
        old = self.base.get(character)
        raw = self.graphics[character]
        if len(old.strokes) != len(raw['medians']):
            raise ValueError('stroke count mismatch with raw source')
        graph = copy.deepcopy(old)
        events = []
        for i, (stroke, median) in enumerate(zip(graph.strokes, raw['medians'], strict=True)):
            if list(map(tuple, stroke.median)) != _normalise_median(median):
                raise ValueError('database median differs from frozen raw source')
            m = np.asarray(median, dtype=float)
            if not np.isfinite(m).all() or np.any((m[:, 0] < 0) | (m[:, 0] > 1024) | (m[:, 1] < -124) | (m[:, 1] > 900)):
                raise ValueError('raw coordinates exceed documented source frame; manual review required')
            corrected = [(float(x/1024), float(1-y/1024)) for x, y in m]
            if corrected != stroke.median:
                events.append({'stroke_id': stroke.stroke_id, 'defect': 'import_clipping',
                    'method': 'exact source coordinate restoration in unchanged legacy frame; no point clamp',
                    'raw_median_sha256': record_hash(median), 'changed_vertices': sum(a != b for a, b in zip(corrected, stroke.median, strict=True)),
                    'rejection': None})
            rule = self.outline_rules.get((character, stroke.stroke_id))
            if rule is not None:
                outline_hash = hashlib.sha256(raw['strokes'][i].encode()).hexdigest()
                median_hash = hashlib.sha256(json.dumps(median, separators=(',', ':')).encode()).hexdigest()
                if outline_hash != rule['outline_sha256'] or median_hash != rule['median_sha256'] or old.source_version != rule['source_version']:
                    raise ValueError('reviewed outline repair identity mismatch')
                method = propose_strip_median if rule['algorithm'] == 'single_strip_outline_median_v1' else propose_sparse_strip
                if rule['algorithm'] not in ('single_strip_outline_median_v1', 'reviewed_single_strip_sparse_v1'):
                    raise ValueError('unsupported outline algorithm')
                points, report = method(raw['strokes'][i], median, count=rule['cross_sections'])
                corrected = [(float(x/1024), float(1-y/1024)) for x, y in points]
                events.append({'stroke_id': stroke.stroke_id, 'defect': ('reviewed_near_empty_source_median' if rule['algorithm'] == 'single_strip_outline_median_v1' else 'reviewed_missing_curvature'),
                    'method': rule['algorithm'], 'outline_sha256': outline_hash, 'raw_median_sha256': median_hash,
                    'report': report, 'rejection': None})
            stroke.median = corrected
            stroke.bbox = bbox(corrected)
            stroke.signature = stroke_signature(corrected)
        for component in graph.components:
            component.bbox = _component_bbox(component.stroke_ids, graph.strokes)
        graph.relations = _relations(graph.strokes)
        graph.source_version = self.version
        self.events[character] = {'graphics_record_sha256': record_hash(raw), 'changes': events,
            'reference_frame': 'legacy origin preserved; raw source y<0 becomes reference y>1; generated canvas fit remains mandatory'}
        self._cache[character] = graph
        return copy.deepcopy(graph)

    def metadata(self):
        return {**self.base.metadata(), 'source_version': self.version, 'correction_policy': POLICY}

    def content_sha256(self):
        return self.digest

    def characters(self):
        return self.base.characters()

    def count(self):
        return self.base.count()

    def iter_graphs(self):
        for character in self.characters():
            yield self.get(character)


def propose_sparse_strip(outline, original, *, count=40):
    """Only reviewed two-point curved strips; preserve both trusted endpoints.

    Multi-interval cuts, invalid anchors or protruding chords reject the proposal.
    This is not a general hook/branch skeletonizer.
    """
    from matplotlib.path import Path as PolygonPath

    from .geometry import path_length, resample
    from .structure_defects import boundary_distances

    anchors = np.asarray(original, dtype=float)
    if anchors.shape != (2, 2) or not np.isfinite(anchors).all() or count < 4:
        raise ValueError('exactly two reviewed finite anchors required')
    polygon = flatten_outline(outline, subdivisions=48)
    shape = PolygonPath(polygon)
    if not shape.contains_points(anchors).all():
        raise ValueError('source anchors are not inside their outline')
    delta = anchors[1]-anchors[0]
    span = float(np.linalg.norm(delta))
    if span < 50:
        raise ValueError('short stroke is not eligible for sparse-strip repair')
    direction = delta/span
    basis = np.column_stack([direction, [-direction[1], direction[0]]])
    local = (polygon-anchors[0])@basis
    mids = []
    for u in np.linspace(0, span, count)[1:-1]:
        a, b = local[:-1], local[1:]
        mask = ((a[:, 0] <= u) & (u < b[:, 0])) | ((b[:, 0] <= u) & (u < a[:, 0]))
        a, b = a[mask], b[mask]
        if len(a) != 2:
            raise ValueError('multiple/empty cross sections: complex shape requires another method')
        values = a[:, 1]+(u-a[:, 0])/(b[:, 0]-a[:, 0])*(b[:, 1]-a[:, 1])
        mids.append([u, float(values.mean())])
    proposal = np.vstack([anchors[0], np.asarray(mids)@basis.T+anchors[0], anchors[1]])
    probes = np.asarray(resample(proposal.tolist(), 1025))
    outside = ~shape.contains_points(probes)
    max_distance = float(boundary_distances(probes[outside], polygon).max()) if outside.any() else 0.
    if max_distance > 1. or path_length(proposal.tolist()) > 1.5*span:
        raise ValueError('proposal fails containment or length guard')
    return proposal.tolist(), {'version': 'reviewed_single_strip_sparse_v1', 'old_length': span,
        'proposed_length': path_length(proposal.tolist()), 'single_interval_sections': count-2,
        'endpoint_shift': 0., 'sampled_outside_max': max_distance, 'probe_count': len(probes),
        'interpretation': 'outline-derived source estimate, not author handwriting'}
