"""Reproducible near-best whole-exemplar draws, without coordinate noise."""
from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from .component_variation_evidence import ComponentVariationEvidence
from .contextual_trajectory import anchors, choose_component
from .exemplar_generation import SourceComponentGenerator
from .exemplar_index import component_key
from .trajectory_experiment import SharedTransform, assemble

VARIATION_POLICY = 'near_best_exemplar_variation_v1'


def geometry_fingerprint(curves):
    # Matching fingerprint only: never use these 64 anchors as delivered points.
    values = np.round(anchors(curves, 64), 8).tolist()
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def source_component(base, target_ids, record, sources):
    candidate = record['candidate']
    sample = sources[candidate['sample_id']]
    if sample.source_sha256 != candidate['source_sha256']:
        raise ValueError('source identity changed')
    mapping = {s.standard_stroke_id: s for s in sample.strokes}
    source = [mapping[k] for k in candidate['stroke_ids']]
    placed = [SharedTransform(**record['transform']).apply(s.points) for s in source]
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in target_ids]
    replacements = {i: {'points': p, 'pressure': s.pressure, 'time': s.t_ms}
                    for i, p, s in zip(indices, placed, source, strict=True)}
    return assemble(base, replacements, 'contextual'), placed


@dataclass
class VariationPool:
    diagnostics: list[dict]
    distinct: list[dict]
    evidence: dict | None = None

    def eligible(self, margin):
        if not math.isfinite(margin) or not 0 <= margin <= .05:
            raise ValueError('invalid near-best score margin')
        if not self.distinct:
            return [], []
        best = self.distinct[0]['score']
        candidates = [c for c in self.distinct if c['score'] <= best + margin + 1e-12]
        if margin == 0:
            # Zero is deterministic off; it cannot introduce random score ties.
            return candidates[:1], [1.]
        if self.evidence is not None:
            candidates = [c for c in candidates if c.get('component_evidence', {}).get('within_empirical_range')]
            if len(candidates) < 2:
                return self.distinct[:1], [1.]
        weights = [c['candidate']['confidence'] * math.exp(-(c['score'] - best) / margin) for c in candidates]
        total = sum(weights)
        if total <= 0 or not math.isfinite(total):
            raise ValueError('invalid candidate sampling weights')
        return candidates, [w / total for w in weights]

    def select(self, base, target_ids, sources, *, seed, occurrence_id, component_id, margin):
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError('variation seed must be an integer')
        if isinstance(occurrence_id, bool) or not isinstance(occurrence_id, int) or occurrence_id < 0:
            raise ValueError('occurrence ID must be a nonnegative integer')
        candidates, probabilities = self.eligible(margin)
        state = [VARIATION_POLICY, seed, base.writer_id, base.profile_version,
                 base.character, occurrence_id, component_id]
        digest = hashlib.sha256(json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode()).digest()
        uniform = int.from_bytes(digest[:8], 'big') / 2**64
        common = {'policy': VARIATION_POLICY, 'seed': seed, 'occurrence_id': occurrence_id,
            'component_id': component_id, 'margin': margin, 'distinct_safe_candidates': len(self.distinct),
            'component_evidence': self.evidence,
            'eligible_distinct_candidates': len(candidates), 'draw_hash': digest.hex(),
            'probabilities': probabilities,
            'eligible_geometry_ids': [c['geometry_id'] for c in candidates],
            'interpretation': 'cross-character component compatibility; repeated-character distribution unverified'}
        if not candidates:
            return base, {'selected': None, 'candidates': self.diagnostics,
                'fallback_reason': 'no topology-compatible complete exemplar', 'variation': common}
        cumulative = 0.
        selected = candidates[-1]
        for candidate, probability in zip(candidates, probabilities, strict=True):
            cumulative += probability
            if uniform < cumulative:
                selected = candidate
                break
        glyph, _ = source_component(base, target_ids, selected, sources)
        common['reason'] = 'sampled near-best distinct exemplar' if len(candidates) > 1 else 'fewer than two near-best evidenced shapes; deterministic result'
        common['selected_geometry_id'] = selected['geometry_id']
        common['score_regret'] = selected['score'] - self.distinct[0]['score']
        return glyph, {'selected': selected, 'candidates': self.diagnostics,
                       'fallback_reason': None, 'variation': common}


def prepare_variation_pool(base, graph, target_ids, candidates, sources, *, max_candidates=16):
    _, evidence = choose_component(base, graph, target_ids, candidates, sources,
                                  max_candidates=max_candidates)
    accepted = [r for r in evidence['candidates'] if r.get('accepted')]
    # D's stable score order preserves its exact first choice at margin=0.
    accepted.sort(key=lambda r: r['score'])
    unique, fingerprints = [], set()
    for record in accepted:
        _, placed = source_component(base, target_ids, record, sources)
        fingerprint = geometry_fingerprint(placed)
        if fingerprint not in fingerprints:
            fingerprints.add(fingerprint)
            unique.append({**record, 'geometry_id': fingerprint})
    return VariationPool(evidence['candidates'], unique)


class VariedSourceComponentGenerator(SourceComponentGenerator):
    def __init__(self, *args, seed=None, margin=0., **kwargs):
        super().__init__(*args, **kwargs)
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise TypeError('variation seed must be an integer')
        if not math.isfinite(margin) or not 0 <= margin <= .05:
            raise ValueError('invalid near-best score margin')
        self.seed, self.margin = seed, margin
        self.pool_cache = OrderedDict()
        self.evidence = ComponentVariationEvidence(self.index) if seed is not None else None

    def _select_component(self, current, graph, ids, candidates, component, occurrence_id):
        if self.seed is None:
            return super()._select_component(current, graph, ids, candidates, component, occurrence_id)
        coordinates = [[(p.x, p.y) for p in s.points] for s in current.strokes]
        identity = json.dumps([graph.character, ids, coordinates, candidates], sort_keys=True)
        key = hashlib.sha256(identity.encode()).hexdigest()
        if key not in self.pool_cache:
            pool = prepare_variation_pool(current, graph, ids, candidates, self.index.sources)
            context = component_key(self.index.graph(graph.character), component)
            _, pool.evidence = self.evidence.cohort(context, graph.character)
            for record in pool.distinct:
                _, placed = source_component(current, ids, record, self.index.sources)
                record['component_evidence'] = self.evidence.assess(context, graph.character, placed,
                    donor_character=record['candidate']['character'])
            self.pool_cache[key] = pool
        self.pool_cache.move_to_end(key)
        while len(self.pool_cache) > 128:
            self.pool_cache.popitem(last=False)
        return self.pool_cache[key].select(current, ids, self.index.sources, seed=self.seed,
            occurrence_id=occurrence_id, component_id=component.component_id, margin=self.margin)
