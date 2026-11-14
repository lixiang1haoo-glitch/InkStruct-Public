"""Apply v6.3.1 semantic rules before placement."""
from __future__ import annotations

import numpy as np

from ..contextual_trajectory import anchors
from .trace import Donor, emit, observer
from ..geometry import path_length
from .stroke_sources import falling_without_uphook, stroke_class
from .stroke_placement import StrokePlacement
from .components import ComponentSearch
from .component_plan import curves
from .content_rules import (
    VERSION,
    check_content_variants,
    hook_form,
    stop_keys,
    stroke_compatibility,
)


class SemanticComponentSearch(ComponentSearch):
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
        from ..trajectory_experiment import crossing_pairs
        from .contacts import contact_pairs
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
        entries = self.hook_pool if hook else self.pool[kind]
        sink = observer()
        slot = graph.strokes[index].stroke_id
        route = 'vertical bend hook index' if hook else 'stop key direction bucket'
        if sink is not None:
            emit(sink, 'single semantic', 'retrieval', 'found' if entries else 'no candidates',
                 target=slot, index=route, count=len(entries), excluded_roles=excluded_roles)
        for entry in entries:
            sample, source, ref = entry
            ev = stroke_compatibility(graph, index, ref.median, source.points)
            if sink is not None:
                donor = Donor(self.profile.writer_id, sample.character, sample.sample_id, sample.source_sha256,
                              (source.standard_stroke_id,), (slot,))
                emit(sink, 'single semantic', 'admission', 'accepted' if ev['accepted'] else 'rejected',
                     donor=donor, evidence=ev)
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


class SemanticStrokePlacement(SemanticStrokeMixin, StrokePlacement):
    pass
