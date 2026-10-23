"""Experimental whole-exemplar reranking by terminal direction; no point editing."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .contextual_trajectory import choose_component, fit_shared_similarity
from .geometry import path_length
from .trajectory_experiment import SharedTransform, assemble, at_distance

TERMINAL_POLICY = 'terminal_direction_selection_v1'


def terminal_vector(points, window):
    length = path_length(points)
    if not math.isfinite(window) or window <= 0 or length <= 1e-10:
        return None
    vector = np.asarray(points[-1]) - at_distance(points, max(0., length - window))
    norm = float(np.linalg.norm(vector))
    return None if not math.isfinite(norm) or norm <= 1e-10 else vector / norm


def direction_penalty(strokes, reference):
    if len(strokes) != len(reference):
        raise ValueError('terminal comparison needs complete matching components')
    scores = []
    per_stroke = []
    for points, target in zip(strokes, reference, strict=True):
        window = min(.02, .15 * path_length(target))
        a, b = terminal_vector(points, window), terminal_vector(target, window)
        penalty = None if a is None or b is None else float(1 - np.clip(np.dot(a, b), -1, 1))
        per_stroke.append({'window': window, 'penalty': penalty})
        if penalty is not None:
            scores.append(penalty)
    return float(np.mean(scores)) if scores else 0., per_stroke


@dataclass
class TerminalCandidates:
    base: object
    diagnostics: list[dict]
    alternatives: list[tuple[object, dict]]

    def select(self, weight=0., reference='baseline'):
        if not math.isfinite(weight) or weight < 0 or reference not in ('baseline', 'structure'):
            raise ValueError('invalid terminal selection parameters')
        if not self.alternatives:
            return self.base, {'policy': TERMINAL_POLICY, 'weight': weight, 'reference': reference,
                'selected': None, 'fallback_reason': 'no topology-compatible complete exemplar',
                'candidates': self.diagnostics}
        glyph, selected = min(self.alternatives,
            key=lambda item: item[1]['score'] + weight * item[1]['terminal_penalties'][reference])
        return glyph, {'policy': TERMINAL_POLICY, 'weight': weight, 'reference': reference,
            'selected': selected,
            'total_selection_score': selected['score'] + weight * selected['terminal_penalties'][reference],
            'fallback_reason': None, 'candidates': self.diagnostics}


def prepare_terminal_candidates(base, graph, target_ids, candidates, sources, *, max_candidates=16):
    """Freeze exactly D's safe alternatives; target handwriting is not an argument.

    Generated A or transformed public standard medians supply direction cues.
    Candidate source geometry, pressure, timing and fitted placements are fixed.
    """
    _, evidence = choose_component(base, graph, target_ids, candidates, sources,
                                  max_candidates=max_candidates)
    if not any(r.get('accepted') for r in evidence['candidates']):
        return TerminalCandidates(base, evidence['candidates'], [])
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in target_ids]
    baseline = [[(p.x, p.y) for p in base.strokes[i].points] for i in indices]
    public = [graph.strokes[i].median for i in indices]
    public_reason = None
    try:
        mapping = fit_shared_similarity(public, baseline)
        structural_reference = [mapping.apply(s) for s in public]
    except ValueError as exc:
        structural_reference = None
        public_reason = str(exc)
    references = {'baseline': baseline, 'structure': structural_reference}
    diagnostics, alternatives = [], []
    for original in evidence['candidates']:
        record = dict(original)
        diagnostics.append(record)
        if not record.get('accepted'):
            continue
        candidate = record['candidate']
        sample = sources[candidate['sample_id']]
        source_map = {s.standard_stroke_id: s for s in sample.strokes}
        strokes = [source_map[s] for s in candidate['stroke_ids']]
        transform = SharedTransform(**record['transform'])
        placed = [transform.apply(s.points) for s in strokes]
        record['terminal_penalties'], record['terminal_details'] = {}, {}
        for label, reference in references.items():
            penalty, details = (direction_penalty(placed, reference) if reference is not None
                                else (0., [{'unavailable': public_reason}]))
            record['terminal_penalties'][label] = penalty
            record['terminal_details'][label] = details
        replacements = {i: {'points': p, 'pressure': s.pressure, 'time': s.t_ms}
                        for i, p, s in zip(indices, placed, strokes, strict=True)}
        glyph = assemble(base, replacements, 'contextual')
        alternatives.append((glyph, record))
    return TerminalCandidates(base, diagnostics, alternatives)
