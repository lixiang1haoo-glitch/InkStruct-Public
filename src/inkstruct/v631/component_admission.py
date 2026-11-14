"""Admit complete source components and evaluate their placement."""
from __future__ import annotations

from dataclasses import asdict

import numpy as np

from ..contextual_trajectory import anchors, fit_shared_similarity
from .placement import component_boundary_contacts, crossing_delta
from .trace import Donor, emit, observer
from .component_index import component_key, ordered_ids, reference_compatibility
from .initial_placement import choose_component_fast
from ..geometry import bbox, path_length
from ..trajectory_experiment import SharedTransform, crossing_pairs, invariants
from .contacts import BRUSH_WIDTH
from .component_plan import Placement, ComponentPlan, curves


def ordered_root_correspondence(source, target, node):
    """Reuse nested-view thresholds, preserving every standard ID and order."""
    ids = ordered_ids(target,node)
    if source.character != node.glyph_variant or source.character != node.canonical:
        raise ValueError('root identity or glyph variant differs')
    if source.component_warnings or len(source.strokes)!=len(ids) or node.confidence<.8:
        raise ValueError('incomplete structure or stroke count mismatch')
    root=next(n for n in source.components if n.path=='root')
    if set(root.stroke_ids)!={s.stroke_id for s in source.strokes} or root.confidence<.8:
        raise ValueError('root does not own the complete standard character')
    mapping={s.stroke_id:s for s in target.strokes}
    x=[s.median for s in source.strokes];y=[mapping[k].median for k in ids]
    transform=fit_shared_similarity(x,y)
    bounds=bbox([p for s in y for p in s])
    span=max(bounds[2]-bounds[0],bounds[3]-bounds[1],1e-9)
    errors=np.linalg.norm(anchors([transform.apply(s) for s in x])-anchors(y),axis=1)/span
    shape,aspect=reference_compatibility(target,node,source,root)
    if errors.mean()>.08 or errors.max()>.22 or shape>.18 or aspect>.7:
        raise ValueError('ordered root/component correspondence exceeds existing thresholds')
    return {'source_ids':[s.stroke_id for s in source.strokes],'target_ids':ids,
        'reference_mean_error':float(errors.mean()),'reference_max_error':float(errors.max()),
        'shape_error':shape,'log_aspect_error':aspect,'reference_transform':asdict(transform),
        'source_version':source.source_version,'target_version':target.source_version}


def classify_crossings(before, after, source, indices, reviewed_local_pairs=()):
    """Only unchanged, explicitly reviewed source-internal pairs can be exempt."""
    indices=tuple(indices)
    raw=crossing_pairs(source)
    placed=crossing_pairs([after[i] for i in indices])
    inherited={(indices[a],indices[b]) for a,b in raw & set(map(tuple,reviewed_local_pairs))}
    extra=crossing_delta(before, after)
    return {'source_internal_pairs':sorted(raw),'placed_internal_pairs':sorted(placed),
        'internal_topology_preserved':raw==placed,'new_pairs':sorted(extra),
        'reviewed_inherited_pairs':sorted(extra&inherited),'unexplained_new_pairs':sorted(extra-inherited)}


class ComponentAdmission(ComponentPlan):
    def source_graph(self, character):
        return self.v6.index.graph(character)

    def verify_complete_source(self, ctx, proposal):
        """Recheck identity/ownership; source topology is evidence, not a waiver."""
        q=proposal.candidate
        source=self.source(proposal)  # Hash and character identity checks.
        sample=self.profile.source_trajectories[q['sample_id']]
        graph=self.source_graph(sample.character)
        node=next(n for n in graph.components if n.component_id==q['component_id'])
        source_ids=[s.standard_stroke_id for s in sample.strokes]
        if (sample.stroke_order_status not in ('declared','corrected')
                or source_ids!=[s.stroke_id for s in graph.strokes]
                or len(source_ids)!=len(set(source_ids))):
            raise ValueError('complete ordered archive mapping required')
        if q['stroke_ids']!=ordered_ids(graph,node) or node.confidence<.8:
            raise ValueError('source component must own all its ordered strokes')
        if min(s.confidence for s in source)<.30 or np.mean([s.confidence for s in source])<.55:
            raise ValueError('source mapping below unchanged admission threshold')
        if tuple(ctx.graph.strokes[i].stroke_id for i in proposal.indices)!=proposal.ids:
            raise ValueError('target indices differ from ordered standard IDs')
        if len(source)!=len(proposal.ids) or len(set(proposal.ids))!=len(proposal.ids):
            raise ValueError('source/target stroke identity is not one-to-one')
        if 'root_bridge' in q:
            target=next(n for n in ctx.graph.components if n.component_id==proposal.component_id)
            evidence=ordered_root_correspondence(graph,ctx.graph,target)
            if evidence['target_ids']!=list(proposal.ids):
                raise ValueError('root bridge target ownership differs')
        elif not any(p.candidate==q and p.ids==proposal.ids and p.indices==proposal.indices
                     for p in ctx.pools.get(proposal.component_id,())):
            raise ValueError('candidate absent from frozen reliable role/mapping pool')
        return {'complete_ordered_mapping':True,'source_component_id':node.component_id,
                'source_ids':q['stroke_ids'],'target_ids':list(proposal.ids),
                'minimum_mapping_confidence':min(s.confidence for s in source),
                'mean_mapping_confidence':float(np.mean([s.confidence for s in source]))}

    def root_proposals(self, ctx, allowed_contexts):
        proposals=[];log=[]
        for part in ctx.baseline_meta['components']:
            cid=part['component_id']
            node=next((n for n in ctx.graph.components if n.component_id==cid),None)
            if node is None:  # Nested admission is outside this root-bridge probe.
                continue
            if component_key(ctx.graph,node) not in allowed_contexts or cid in ctx.baseline_plan:
                continue
            for sample in self.profile.source_trajectories.values():
                if sample.character!=node.glyph_variant or sample.character==ctx.character:
                    continue
                record={'character':ctx.character,'component_id':cid,'sample_id':sample.sample_id}
                log.append(record)
                try:
                    source=self.v6.mapping_repository.get(sample.character)
                    evidence=ordered_root_correspondence(source,ctx.graph,node)
                    record['mapping']=evidence
                    if sample.stroke_order_status not in ('declared','corrected'):
                        raise ValueError('source order is ambiguous')
                    if [s.standard_stroke_id for s in sample.strokes]!=evidence['source_ids']:
                        raise ValueError('source archive IDs/order do not match root record')
                    confidences=[s.confidence for s in sample.strokes]
                    if min(confidences)<.30 or np.mean(confidences)<.55:
                        raise ValueError('source mapping below unchanged admission threshold')
                    bounds=bbox([p for s in sample.strokes for p in s.points])
                    if min(bounds[2]-bounds[0],bounds[3]-bounds[1])<1e-5:
                        raise ValueError('source component has negligible extent')
                    candidate={'character':sample.character,'sample_id':sample.sample_id,
                        'source_sha256':sample.source_sha256,
                        'component_id':next(n.component_id for n in source.components if n.path=='root'),
                        'stroke_ids':evidence['source_ids'],'confidence':float(np.mean(confidences)),
                        'score':evidence['shape_error']+.1*evidence['log_aspect_error']+.03*(1-np.mean(confidences)),
                        'root_bridge':evidence}
                    _,diag=choose_component_fast(ctx.baseline,ctx.graph,evidence['target_ids'],[candidate],
                                                self.profile.source_trajectories, writer=self.profile.writer_id)
                    trial=diag['candidates'][0]
                    record['original_placement_diagnostic']=trial
                    if 'transform' not in trial:
                        raise ValueError('no finite positive isotropic root fit')
                    ids=tuple(evidence['target_ids'])
                    proposals.append(Placement(cid,ids,tuple(i for i,s in enumerate(ctx.graph.strokes) if s.stroke_id in ids),
                        candidate,SharedTransform(**trial['transform']),trial['score']))
                    record['proposal_created']=True
                except ValueError as error:
                    record['rejected']=str(error)
        return sorted(proposals,key=lambda p:(p.base_score,p.candidate['sample_id'])),log

    def attempt(self, ctx, plan, proposal, review=None, *, source_aware=False,
                reference_differences_diagnostic=True):
        sink = observer()
        evidence=self.verify_complete_source(ctx,proposal) if source_aware else None
        donor = None
        if sink is not None:
            q = proposal.candidate
            donor = Donor(self.profile.writer_id, q['character'], q['sample_id'], q['source_sha256'],
                          tuple(q['stroke_ids']), proposal.ids)
            emit(sink, 'component', 'admission', 'accepted', donor=donor, mapping=evidence,
                 index=proposal.component_id)
        before=self.emit(ctx,plan)
        proposed={**plan,proposal.component_id:proposal}
        after=self.emit(ctx,proposed)
        source=self.source(proposal)
        source_xy=[s.points for s in source]
        q=proposal.candidate
        reviewed=[]
        if review is not None:
            expected={k:q[k] for k in ('sample_id','source_sha256','component_id','stroke_ids')}
            if review.get('source')!=expected or review.get('target_context')!=component_key(ctx.graph,
                    next(n for n in ctx.graph.components if n.component_id==proposal.component_id)):
                raise ValueError('review identity/context does not match placement')
            if set(map(tuple,review['source_internal_pairs']))!=crossing_pairs(source_xy):
                raise ValueError('reviewed source crossing evidence changed')
            reviewed=review['source_internal_pairs']
        if source_aware:
            reviewed=sorted(crossing_pairs(source_xy))
        bx,ax=curves(before),curves(after)
        topology=classify_crossings(bx,ax,source_xy,proposal.indices,reviewed)
        if source_aware:
            # This is traceable source evidence, NOT a claim of human approval.
            topology['source_inherited_pairs']=topology.pop('reviewed_inherited_pairs')
        own=set(proposal.indices)
        new_boundary_contacts,lost_boundary_contacts=component_boundary_contacts(
            bx, ax, own, ctx.reference_contacts)
        ratios=[path_length(ax[i])/max(path_length(ctx.graph.strokes[i].median),1e-9) for i in own]
        errors=invariants(after,ctx.graph)
        degenerate=[i+1 for i,s in enumerate(ax) if path_length(s)<.003]
        reference_warnings=[]
        if lost_boundary_contacts:reference_warnings.append('reference-supported contact removed')
        if min(ratios)<.4 or max(ratios)>2.5:reference_warnings.append('length differs from reference')
        reference_is_diagnostic=source_aware and reference_differences_diagnostic
        accepted=(not errors and not degenerate and topology['internal_topology_preserved']
            and not topology['unexplained_new_pairs'] and not new_boundary_contacts
            and (reference_is_diagnostic or not reference_warnings))
        reasons=[]
        if errors:reasons.append('protocol or final bounds')
        if degenerate:reasons.append('degenerate output stroke')
        if not topology['internal_topology_preserved']:reasons.append('source topology changed')
        if topology['unexplained_new_pairs']:reasons.append('new unexplained crossing')
        if new_boundary_contacts:reasons.append('new cross-component brush contact')
        if not reference_is_diagnostic:reasons.extend(reference_warnings)
        diagnostic={'candidate':q,'transform':asdict(proposal.transform),'accepted':accepted,
            'protocol':errors,'degenerate':degenerate,'topology':topology,
            'new_cross_boundary_contacts':sorted(new_boundary_contacts),
            'lost_reference_supported_boundary_contacts':sorted(lost_boundary_contacts),
            'brush_width':BRUSH_WIDTH,'length_ratios':ratios,
            'review':review,'source_mapping_evidence':evidence,'source_aware':source_aware,
            'reference_differences_diagnostic_only':reference_warnings if reference_is_diagnostic else [],
            'fallback_reason':None if accepted else '; '.join(reasons)}
        if sink is not None:
            emit(sink, 'component', 'placement', 'accepted' if accepted else 'rejected',
                 donor=donor, transform=diagnostic['transform'], reason=diagnostic['fallback_reason'],
                 topology=topology, new_contacts=diagnostic['new_cross_boundary_contacts'],
                 lost_contacts=diagnostic['lost_reference_supported_boundary_contacts'],
                 brush_width=BRUSH_WIDTH, length_ratios=ratios, protocol=errors)
        return (proposed if accepted else plan),diagnostic


    def expand(self, ctx, initial_plan, *, existing_pool=False, root_contexts=(),
               reference_differences_diagnostic=True):
        """Fill reference slots only. Existing accepted sources/layout stay fixed.

        Explicit switches keep production and legacy probes unchanged. The old
        ranking and per-candidate fit are frozen; source-aware checks decide
        admission. Whole roots are a separate role-bridge pool experiment.
        """
        plan=dict(initial_plan);log=[]
        if existing_pool:
            for cid,pool in ctx.pools.items():
                if cid in plan:continue
                for p in sorted(pool,key=lambda p:p.base_score):
                    plan,d=self.attempt(ctx,plan,p,source_aware=True,
                        reference_differences_diagnostic=reference_differences_diagnostic);log.append(d)
                    if d['accepted']:break
        roots,root_log=self.root_proposals(ctx,root_contexts)
        for p in roots:
            if p.component_id not in plan:
                plan,d=self.attempt(ctx,plan,p,source_aware=True,
                    reference_differences_diagnostic=reference_differences_diagnostic);log.append(d)
        return self.emit(ctx,plan),plan,{'root_mapping':root_log,'placement':log}
