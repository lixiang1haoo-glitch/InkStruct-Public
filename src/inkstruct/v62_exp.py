"""v6.2 exp: content admission before v6.1 placement, preserving source ink."""
from __future__ import annotations

import numpy as np

from .contextual_trajectory import anchors
from .geometry import path_length
from .v61_author_strokes import AuthorStrokeFallback, falling_without_uphook, stroke_class
from .v61_author_strokes_batch import BatchAuthorStrokeFallback
from .v61_candidate_expansion import CandidateExpansionGenerator
from .v61_exp import curves
from .v62_semantics import (
    VERSION,
    check_content_variants,
    hook_form,
    stop_keys,
    stroke_compatibility,
)


class SemanticCandidateGenerator(CandidateExpansionGenerator):
    check_variants = staticmethod(check_content_variants)

    def prepare(self, character):
        ctx = super().prepare(character)
        self.semantic_log = []
        for cid, p in list(ctx.baseline_plan.items()):
            ev = self.variant_evidence(ctx, p)
            if not ev['accepted']:
                del ctx.baseline_plan[cid]
                self.semantic_log.append({'removed_inherited_candidate': p.candidate,
                                          'semantic_admission': ev})
        ctx.baseline = self.emit(ctx, ctx.baseline_plan)
        from .trajectory_experiment import crossing_pairs
        from .v61_contacts import contact_pairs
        ctx.baseline_contacts = contact_pairs(curves(ctx.baseline))
        ctx.baseline_crossings = crossing_pairs(curves(ctx.baseline))
        return ctx


def descriptors(entries, kind):
    x = np.asarray([anchors([s.points]) for _, s, _ in entries])
    mean = x.mean(axis=1); centered = x-mean[:, None, :]
    return {'x': x, 'mean': mean, 'centered': centered,
        'denominator': (centered**2).sum(axis=(1, 2)),
        'length': np.asarray([path_length(s.points) for _, s, _ in entries]),
        'first': np.asarray([s.points[0] for _, s, _ in entries]),
        'last': np.asarray([s.points[-1] for _, s, _ in entries]),
        'low': np.asarray([np.min(s.points, axis=0) for _, s, _ in entries]),
        'high': np.asarray([np.max(s.points, axis=0) for _, s, _ in entries]),
        'pie': np.asarray([falling_without_uphook(s.points) if kind == 'pie' else True for _, s, _ in entries]),
        'confidence': np.asarray([s.confidence for _, s, _ in entries])}


class SemanticStrokeMixin:
    def __init__(self, *args):
        super().__init__(*args)
        self.hook_pool = [entry for entries in self.pool.values() for entry in entries
                          if hook_form(entry[2].median)['form'] == 'vertical_bend_hook']

    def select(self, graph, index, current, reference, *, start_anchor=None):
        target = graph.strokes[index].median
        hook = hook_form(target)['form'] == 'vertical_bend_hook'
        stop = graph.strokes[index].stroke_id in stop_keys(graph)
        if not hook and not stop:
            return super().select(graph, index, current, reference, start_anchor=start_anchor)
        kind = stroke_class(target)
        accepted, rejected = [], []
        excluded_roles = [{'character': sample.character, 'sample_id': sample.sample_id,
                           'source_stroke_id': source.standard_stroke_id,
                           'evidence': stroke_compatibility(graph, index, ref.median, source.points)}
                          for sample, source, ref in self.pool[kind]
                          if hook and hook_form(ref.median)['form'] != 'vertical_bend_hook']
        for entry in self.hook_pool if hook else self.pool[kind]:
            sample, source, ref = entry
            ev = stroke_compatibility(graph, index, ref.median, source.points)
            if ev['accepted']:
                accepted.append(entry)
            else:
                rejected.append({'sample_id': sample.sample_id, 'source_stroke_id': source.standard_stroke_id, **ev})
        old = self.pool[kind]
        batch = hasattr(self, 'descriptors')
        old_descriptor = self.descriptors.get(kind) if batch else None
        self.pool[kind] = accepted
        if batch:
            self.descriptors[kind] = descriptors(accepted, kind) if accepted else None
        try:
            piece, evidence = super().select(graph, index, current, reference, start_anchor=start_anchor)
        finally:
            self.pool[kind] = old
            if batch:
                self.descriptors[kind] = old_descriptor
        evidence['semantic_admission'] = {'version': VERSION, 'family': 'vertical_bend_hook' if hook else '止',
            'compatible_candidates': len(accepted), 'rejected_actual_forms': rejected,
            'excluded_reference_roles': excluded_roles,
            'retrieval': 'compatible role across directional buckets; original mapping and geometry gates retained'}
        return piece, evidence


class SemanticAuthorStrokeFallback(SemanticStrokeMixin, AuthorStrokeFallback):
    pass


class SemanticBatchStrokeFallback(SemanticStrokeMixin, BatchAuthorStrokeFallback):
    pass
