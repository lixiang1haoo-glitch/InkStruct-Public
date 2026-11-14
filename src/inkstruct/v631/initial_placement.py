"""Output-equivalent fast path for the frozen no-field component selector."""
from __future__ import annotations

from dataclasses import asdict

import numpy as np

from ..contextual_trajectory import anchors
from .trace import Donor, emit, observer
from ..geometry import path_length
from ..trajectory_experiment import SharedTransform, assemble, crossing_pairs, invariants


def choose_component_fast(base, graph, target_ids, candidates, sources, *, max_candidates=16,
                          anchor_cache=None, writer=""):
    """Rank cheap placements first, then validate until the best safe one is found.

    Rejected higher-score candidates need not be assembled or intersected.
    Diagnostics label those candidates untested rather than calling them safe.
    The full source points are retained; cached anchors are for matching only.
    """
    if anchor_cache is None:
        anchor_cache = {}
    base_curves = [[(p.x, p.y) for p in s.points] for s in base.strokes]
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in target_ids]
    if len(indices) != len(target_ids) or not indices:
        raise ValueError('target component IDs must be unique and complete')
    target = [base_curves[i] for i in indices]
    y = anchors(target)
    ym = y.mean(axis=0)
    base_crossings = crossing_pairs(base_curves)
    target_lengths = [path_length(s) for s in target]
    proposals, diagnostics = [], []
    for candidate in candidates[:max_candidates]:
        if candidate['character'] == graph.character:
            raise ValueError('cross-character pool contains target character')
        sample = sources[candidate['sample_id']]
        if sample.character != candidate['character'] or sample.source_sha256 != candidate['source_sha256']:
            raise ValueError('donor identity mismatch')
        mapping = {s.standard_stroke_id: s for s in sample.strokes}
        source = [mapping[k] for k in candidate['stroke_ids']]
        if len(source) != len(target):
            diagnostics.append({'candidate': candidate, 'errors': ['stroke count mismatch']})
            continue
        cache_key = (sample.sample_id, sample.source_sha256, tuple(candidate['stroke_ids']))
        if cache_key not in anchor_cache:
            anchor_cache[cache_key] = anchors([s.points for s in source])
        x = anchor_cache[cache_key]
        xm = x.mean(axis=0)
        xc, yc = x - xm, y - ym
        denominator = float(np.sum(xc * xc))
        if denominator < 1e-12 or not np.isfinite(x).all() or not np.isfinite(y).all():
            diagnostics.append({'candidate': candidate, 'errors': ['invalid component geometry']})
            continue
        scale = float(np.sum(xc * yc) / denominator)
        if scale <= 1e-8:
            diagnostics.append({'candidate': candidate, 'errors': ['incompatible component direction']})
            continue
        offset = ym - scale * xm
        transform = SharedTransform(scale, scale, float(offset[0]), float(offset[1]))
        placed = [transform.apply(s.points) for s in source]
        score = float(np.linalg.norm(anchors(placed) - y, axis=1).mean()) + .01 * candidate['score']
        record = {'candidate': candidate, 'score': score, 'transform': asdict(transform),
                  'field': None, 'accepted': None, 'decision': 'not_checked_higher_score'}
        diagnostics.append(record)
        proposals.append((score, placed, source, record))
    validations = 0
    ranked = sorted(proposals, key=lambda p: p[0])
    sink = observer()
    if sink is not None:
        emit(sink, 'component fast', 'ranking', 'ordered', target=target_ids,
             retrieved=len(candidates), budget=max_candidates,
             unexamined=max(0, len(candidates) - max_candidates),
             order=[p[3]['candidate'] for p in ranked],
             precheck_rejected=[r for r in diagnostics if 'transform' not in r])
    for _, placed, source, record in ranked:
        replacements = {i: {'points': p, 'pressure': s.pressure, 'time': s.t_ms}
                        for i, p, s in zip(indices, placed, source, strict=True)}
        glyph = assemble(base, replacements, 'contextual')
        errors = invariants(glyph, graph)
        trial = list(base_curves)
        for i, p in zip(indices, placed, strict=True):
            trial[i] = p
        new_crossings = crossing_pairs(trial) - base_crossings
        lengths = [path_length(p) / max(length, 1e-9) for p, length in zip(placed, target_lengths, strict=True)]
        accepted = not errors and not new_crossings and min(lengths) >= .4 and max(lengths) <= 2.5
        record.update({'errors': errors, 'new_crossings_vs_A': sorted(new_crossings),
                       'length_ratios_vs_A': lengths, 'accepted': accepted,
                       'decision': 'accepted' if accepted else 'rejected'})
        validations += 1
        if sink is not None:
            c = record['candidate']
            donor = Donor(writer, c['character'], c['sample_id'], c['source_sha256'],
                          tuple(c['stroke_ids']), tuple(target_ids))
            emit(sink, 'component fast', 'placement', 'accepted' if accepted else 'rejected',
                 donor=donor, attempt=validations, transform=record['transform'],
                 new_crossings=sorted(new_crossings), length_ratios=lengths, length_limits=[.4, 2.5],
                 protocol=errors, remaining=len(ranked) - validations)
        if accepted:
            return glyph, {'fallback_reason': None, 'selected': record, 'candidates': diagnostics,
                           'fully_validated_candidates': validations}
    return base, {'fallback_reason': 'no topology-compatible complete exemplar',
                  'candidates': diagnostics, 'selected': None,
                  'fully_validated_candidates': validations}
