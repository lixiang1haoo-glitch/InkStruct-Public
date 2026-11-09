"""Training-only author/context direction cues; whole-source reranking only."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .contextual_trajectory import choose_component, fit_shared_similarity
from .exemplar_index import component_key, shape_descriptor
from .exemplar_variation import source_component
from .geometry import path_length
from .terminal_selection import terminal_vector

POLICY = 'author_context_terminal_v1'
MODES = ('author', 'public_residual')


def complex_direction(points, window):
    vector = terminal_vector(points, window)
    return None if vector is None else complex(*vector)


def circular_cue(character_vectors, minimum=4):
    """Equal weight per character; repeated captures never increase sample size."""
    means = [sum(values)/len(values) for values in character_vectors.values() if values]
    if len(means) < minimum:
        return None
    mean = sum(means)/len(means)
    concentration = abs(mean)
    if concentration < .5:
        return None
    return {'vector': [mean.real/concentration, mean.imag/concentration],
            'concentration': concentration, 'reference_characters': len(means)}


class AuthorTerminalEvidence:
    def __init__(self, index):
        self.index = index
        self.entries = defaultdict(list)
        for context, candidates in index.by_key.items():
            for candidate in candidates:
                graph = index.graph(candidate['character'])
                component = next(c for c in graph.components if c.component_id == candidate['component_id'])
                mapping = {s.standard_stroke_id: s for s in index.sources[candidate['sample_id']].strokes}
                public_map = {s.stroke_id: s.median for s in graph.strokes}
                self.entries[context].append({'candidate': candidate,
                    'descriptor': shape_descriptor(graph, component),
                    'raw': [mapping[s].points for s in candidate['stroke_ids']],
                    'public': [public_map[s] for s in candidate['stroke_ids']]})

    def predict(self, graph, component, target_curves, excluded_character):
        """No target capture argument; excludes both character groups before fitting."""
        excluded = {graph.character, excluded_character}
        descriptor = shape_descriptor(graph, component)
        groups = defaultdict(list)
        for entry in self.entries.get(component_key(graph, component), []):
            if entry['candidate']['character'] not in excluded:
                groups[entry['candidate']['character']].append(entry)
        ranked = sorted(groups, key=lambda c: (
            min(float(np.linalg.norm(e['descriptor']-descriptor, axis=2).mean()) for e in groups[c]), c))[:8]
        windows = [min(.02, .15*path_length(s)) for s in target_curves]
        public_map = {s.stroke_id: s.median for s in graph.strokes}
        target_public = [public_map[s.stroke_id] for s in graph.strokes if s.stroke_id in component.stroke_ids]
        public_fit = fit_shared_similarity(target_public, target_curves)
        public_vectors = [complex_direction(public_fit.apply(s), w) for s, w in zip(target_public, windows, strict=True)]
        observations = {mode: [defaultdict(list) for _ in windows] for mode in MODES}
        records = []
        for character in ranked:
            for entry in groups[character]:
                try:
                    raw_fit = fit_shared_similarity(entry['raw'], target_curves)
                    structure_fit = fit_shared_similarity(entry['public'], target_curves)
                except ValueError:
                    continue
                records.append(entry['candidate'])
                for i, window in enumerate(windows):
                    raw = complex_direction(raw_fit.apply(entry['raw'][i]), window)
                    public = complex_direction(structure_fit.apply(entry['public'][i]), window)
                    if raw is not None:
                        observations['author'][i][character].append(raw)
                    if raw is not None and public is not None and public_vectors[i] is not None:
                        observations['public_residual'][i][character].append(raw*public.conjugate()*public_vectors[i])
        cues = {mode: [circular_cue(group) for group in values] for mode, values in observations.items()}
        return cues, {'excluded_characters': sorted(excluded), 'ranked_reference_characters': ranked,
                      'used_sources': records, 'windows': windows, 'cues': cues}


@dataclass
class AuthorTerminalCandidates:
    original: object
    original_meta: dict
    alternatives: list
    diagnostics: list
    common_supported_strokes: dict

    def select(self, weight=0., mode='author'):
        if not math.isfinite(weight) or weight < 0 or mode not in MODES:
            raise ValueError('invalid author terminal selection parameters')
        if weight == 0 or not self.alternatives or not self.common_supported_strokes[mode]:
            reason = ('disabled' if weight == 0 else 'no common independent direction evidence')
            return self.original, {**self.original_meta, 'policy': POLICY, 'weight': weight, 'mode': mode,
                'context_fallback_reason': reason, 'direction_diagnostics': self.diagnostics}
        glyph, record = min(self.alternatives, key=lambda p: p[1]['score']+weight*p[1]['author_terminal_penalties'][mode])
        return glyph, {'policy': POLICY, 'weight': weight, 'mode': mode, 'selected': record,
            'fallback_reason': None, 'context_fallback_reason': None,
            'common_supported_strokes': self.common_supported_strokes[mode],
            'total_selection_score': record['score']+weight*record['author_terminal_penalties'][mode],
            'direction_diagnostics': self.diagnostics}


def prepare_author_terminal(base, graph, component, candidates, evidence, *, max_candidates=16):
    ids = [s.stroke_id for s in graph.strokes if s.stroke_id in component.stroke_ids]
    original, metadata = choose_component(base, graph, ids, candidates, evidence.index.sources,
                                          max_candidates=max_candidates)
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in ids]
    target = [[(p.x, p.y) for p in base.strokes[i].points] for i in indices]
    alternatives, diagnostics = [], []
    for record in metadata['candidates']:
        if not record.get('accepted'):
            continue
        glyph, _ = source_component(base, ids, record, evidence.index.sources)
        try:
            cues, detail = evidence.predict(graph, component, target, record['candidate']['character'])
        except ValueError as error:
            cues = {mode: [None]*len(ids) for mode in MODES}
            detail = {'reason': str(error), 'cues': cues}
        vectors = [complex_direction([(p.x, p.y) for p in glyph.strokes[i].points],
                   min(.02, .15*path_length(t))) for i, t in zip(indices, target, strict=True)]
        tagged = {**record, 'author_context_evidence': detail, 'author_terminal_penalties': {}}
        per_stroke = {}
        for mode in MODES:
            per_stroke[mode] = [None if cue is None or v is None else
                cue['concentration']*(1-float(np.clip(np.dot([v.real, v.imag], cue['vector']), -1, 1)))
                for cue, v in zip(cues[mode], vectors, strict=True)]
        tagged['author_terminal_per_stroke'] = per_stroke
        alternatives.append((glyph, tagged))
        diagnostics.append(tagged)
    common = {mode: [i for i in range(len(ids)) if alternatives and all(
        r['author_terminal_per_stroke'][mode][i] is not None for _, r in alternatives)] for mode in MODES}
    for _, record in alternatives:
        for mode in MODES:
            record['author_terminal_penalties'][mode] = float(np.mean([
                record['author_terminal_per_stroke'][mode][i] for i in common[mode]])) if common[mode] else 0.
    return AuthorTerminalCandidates(original, metadata, alternatives, diagnostics, common)
