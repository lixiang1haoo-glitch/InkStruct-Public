"""Search complete, nested and whole-target component candidates."""
from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import asdict, dataclass, replace

import numpy as np

from .component_views import expand_views
from ..contextual_trajectory import anchors, fit_shared_similarity
from .placement import cross_boundary, crossing_delta
from .trace import Donor, emit, observer
from .component_index import component_key, ordered_ids, reference_compatibility
from ..geometry import bbox
from .position_rules import check_positional_variants
from .reuse_rules import ReuseRules
from ..trajectory_experiment import SharedTransform
from .component_admission import ComponentAdmission
from .component_plan import Placement

VERSION = 'v61_candidate_expansion_v1'
MAX_AXIS_RATIO = 1.35


@dataclass(frozen=True)
class ExpansionPolicy:
    context: bool = False
    hierarchy: bool = False
    nested: bool = False
    whole_target: bool = False
    anisotropic: bool = False


def identity(node):
    return node.canonical, node.glyph_variant, len(node.stroke_ids)


def fit_bounded_axes(source, target):
    """One positive diagonal transform for all strokes; reject, never clamp."""
    if len(source) != len(target):
        raise ValueError('stroke count mismatch')
    x, y = anchors(source), anchors(target)
    xm, ym = x.mean(axis=0), y.mean(axis=0)
    xc, yc = x - xm, y - ym
    denominator = np.sum(xc * xc, axis=0)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or min(denominator) < 1e-12:
        raise ValueError('invalid axis fit')
    scale = np.sum(xc * yc, axis=0) / denominator
    if min(scale) <= 1e-8 or max(scale) / min(scale) > MAX_AXIS_RATIO:
        raise ValueError('axis ratio exceeds frozen 1.35 bound or direction reversed')
    offset = ym - scale * xm
    return SharedTransform(float(scale[0]), float(scale[1]), float(offset[0]), float(offset[1]))


def correspondence(source, sn, target, tn, *, anisotropic=False):
    """Keep identity/count and ordered-reference proof, separately test axis fit."""
    if identity(sn) != identity(tn) or min(sn.confidence, tn.confidence) < .8:
        raise ValueError('identity/count or component mapping confidence')
    sm, tm = ({s.stroke_id: s for s in graph.strokes} for graph in (source, target))
    x = [sm[k].median for k in ordered_ids(source, sn)]
    y = [tm[k].median for k in ordered_ids(target, tn)]
    fit = (fit_bounded_axes if anisotropic else fit_shared_similarity)(x, y)
    bounds = bbox([p for s in y for p in s])
    span = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1e-9)
    errors = np.linalg.norm(anchors([fit.apply(s) for s in x]) - anchors(y), axis=1) / span
    shape, aspect = reference_compatibility(target, tn, source, sn)
    evidence = {'mean_error': float(errors.mean()), 'max_error': float(errors.max()),
                    'shape': shape, 'log_aspect': aspect, 'transform': asdict(fit), 'anisotropic': anisotropic}
    # The axis arm replaces raw aspect/shape gates with bounded ordered fit;
    # it is explicitly NOT pooled with isotropic results.
    if errors.mean() > .08 or errors.max() > .22 or (not anisotropic and (shape > .18 or aspect > .7)):
        raise ValueError('ordered reference correspondence exceeds thresholds')
    return evidence


class ComponentSearch(ComponentAdmission):
    check_variants = staticmethod(check_positional_variants)
    def __init__(self, *args, variant_checks=True, split_rules=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.variant_checks = variant_checks
        self.expanded_graphs = {}
        self.view_log = {}
        self._inventories = {}
        self.reuse_rules = ReuseRules(split_rules)
        self.rule_log = []
        self._rule_graphs = {}

    def rule_graph(self, character, *, side):
        """Raw validated views for audit, including virtual IDs from old plans."""
        key = (side, character)
        if key not in self._rule_graphs:
            repo = self.v6.mapping_repository if side == 'source' else self.v6.target_repository
            graph = repo.get(character)
            for _ in range(3):
                allowed = tuple({n.canonical for n in graph.components if len(n.canonical) == 1})
                graph = expand_views(graph, repo, allowed=allowed, max_depth=2).graph
            self._rule_graphs[key] = graph
        return self._rule_graphs[key]

    def reuse_evidence(self, ctx, proposal):
        rules = getattr(self, 'reuse_rules', ReuseRules())
        if not rules.enabled:
            return {'accepted': True, 'enabled': False}
        for side, char, ids in [('source', proposal.candidate['character'], proposal.candidate['stroke_ids']),
                                ('target', ctx.character, proposal.ids)]:
            evidence = rules.check(self.rule_graph(char, side=side), ids, side=side)
            if not evidence['accepted']:
                return evidence
        return {'accepted': True, 'enabled': True}

    def filter_plan(self, ctx, plan):
        if not getattr(self, 'reuse_rules', ReuseRules()).enabled:
            return plan, []
        kept, log = {}, []
        for cid, p in plan.items():
            evidence = self.reuse_evidence(ctx, p)
            if evidence['accepted']:
                kept[cid] = p
            else:
                log.append({'removed_inherited_candidate': p.candidate, 'reuse_rule': evidence,
                            'fallback_reason': 'forbidden author reuse split'})
        if log:
            self.rule_log.extend(log)
        return kept, log

    def prepare(self, character):
        # Base prepare checks exact legacy reconstruction. Apply restrictions
        # afterwards so that this check remains meaningful and independent.
        self._preparing_rule_context = True
        try:
            ctx = super().prepare(character)
        finally:
            self._preparing_rule_context = False
        if self.reuse_rules.enabled:
            ctx.baseline_plan, _ = self.filter_plan(ctx, ctx.baseline_plan)
            pools = {}
            for cid, pool in ctx.pools.items():
                safe, _ = self.filter_plan(ctx, {str(i):p for i,p in enumerate(pool)})
                pools[cid] = list(safe.values())
            ctx.pools = pools
            ctx.graph, log = self.reuse_rules.view(ctx.graph)
            self.rule_log.extend(log)
            ctx.baseline = self.emit(ctx, ctx.baseline_plan)
            from ..trajectory_experiment import crossing_pairs
            from .contacts import contact_pairs
            from .component_plan import curves
            ctx.baseline_contacts = contact_pairs(curves(ctx.baseline))
            ctx.baseline_crossings = crossing_pairs(curves(ctx.baseline))
        return ctx

    def emit(self, ctx, plan):
        if not getattr(self, '_preparing_rule_context', False):
            for p in plan.values():
                evidence = self.reuse_evidence(ctx,p)
                if not evidence['accepted']:
                    self.rule_log.append({'stage':'emit', 'reuse_rule': evidence})
                    raise ValueError('forbidden author reuse split in inherited output plan')
        return super().emit(ctx,plan)

    def variant_evidence(self, ctx, proposal):
        graph = self.source_graph(proposal.candidate['character'])
        target = ctx.graph
        sn = next((n for n in graph.components if n.component_id == proposal.candidate['component_id']), None)
        tn = next((n for n in target.components if n.component_id == proposal.component_id), None)
        # Legacy plans may name validated virtual nodes absent from ctx.graph.
        # Reconstruct only the existing validated view; never guess ownership.
        for _ in range(3):
            if sn is None:
                graph, _ = self.expanded(graph, self.v6.mapping_repository)
                sn = next((n for n in graph.components if n.component_id == proposal.candidate['component_id']), None)
            if tn is None:
                target, _ = self.expanded(target, self.v6.target_repository)
                tn = next((n for n in target.components if n.component_id == proposal.component_id), None)
            if sn is not None and tn is not None:
                break
        if sn is None or tn is None:
            return {'accepted': False, 'checks': [], 'reason': 'positional variant view unresolved'}
        return self.check_variants(graph, sn, target, tn, self.source(proposal))

    def admit_component(self, ctx, proposal):
        rule = self.reuse_evidence(ctx, proposal)
        if not rule['accepted']:
            return rule, None
        evidence = self.variant_evidence(ctx, proposal) if self.variant_checks else None
        return rule, evidence

    def attempt(self, ctx, plan, proposal, *args, **kwargs):
        plan, removed = self.filter_plan(ctx, plan)
        rule, evidence = self.admit_component(ctx, proposal)
        sink = observer()
        if sink is not None and (not rule['accepted'] or evidence and not evidence['accepted']):
            q = proposal.candidate
            donor = Donor(self.profile.writer_id, q['character'], q['sample_id'], q['source_sha256'],
                          tuple(q['stroke_ids']), proposal.ids)
            emit(sink, 'component', 'admission', 'rejected', donor=donor,
                 reason='forbidden author reuse split' if not rule['accepted'] else evidence['reason'],
                 index=proposal.component_id)
        if not rule['accepted']:
            diagnostic = {'candidate': proposal.candidate, 'accepted': False,
                          'reuse_rule': rule, 'removed_inherited': removed,
                          'fallback_reason': 'forbidden author reuse split'}
            self.rule_log.append(diagnostic)
            return plan, diagnostic
        if evidence and not evidence['accepted']:
            return plan, {'candidate': proposal.candidate, 'accepted': False,
                          'variant_compatibility': evidence,
                          'fallback_reason': 'positional key-stroke mismatch: ' + evidence['reason']}
        result, diagnostic = super().attempt(ctx, plan, proposal, *args, **kwargs)
        if evidence:
            diagnostic['variant_compatibility'] = evidence
        return result, diagnostic

    def expanded(self, graph, repository):
        allowed = tuple(sorted({n.canonical for n in graph.components if len(n.canonical) == 1}))
        result = expand_views(graph, repository, allowed=allowed, max_depth=2)
        view, log = self.reuse_rules.view(result.graph)
        return view, result.diagnostics + log

    def source_graph(self, character):
        return self.expanded_graphs.get(character) or super().source_graph(character)

    def inventory(self, nested):
        if nested in self._inventories:
            return self._inventories[nested]
        inventory = defaultdict(list)
        for sample in self.profile.source_trajectories.values():
            graph = self.v6.index.graph(sample.character)
            graph, rule_log = self.reuse_rules.view(graph)
            self.rule_log.extend(rule_log)
            if nested:
                graph, diagnostics = self.expanded(graph, self.v6.mapping_repository)
                self.expanded_graphs[sample.character] = graph
                self.view_log[sample.character] = diagnostics
            mapping = {s.standard_stroke_id: s for s in sample.strokes}
            ordered = [s.standard_stroke_id for s in sample.strokes]
            for node in graph.components:
                ids = ordered_ids(graph, node)
                if len(ids) < 2:
                    continue
                errors = []
                if ordered != [s.stroke_id for s in graph.strokes] or len(set(ordered)) != len(ordered) or sample.stroke_order_status not in ('declared', 'corrected'):
                    errors.append('archive IDs/order incomplete')
                if node.confidence < .8:
                    errors.append('source component confidence')
                scores = [mapping[k].confidence for k in ids if k in mapping]
                if len(scores) != len(ids) or min(scores, default=0) < .30 or np.mean(scores) < .55:
                    errors.append('source stroke mapping confidence')
                candidate = {'character': sample.character, 'sample_id': sample.sample_id,
                    'source_sha256': sample.source_sha256, 'component_id': node.component_id,
                    'stroke_ids': ids, 'confidence': float(np.mean(scores)) if scores else 0.}
                inventory[identity(node)].append((graph, node, candidate, errors))
        self._inventories[nested] = inventory
        return inventory

    def validate_transform(self, placement):
        if not placement.candidate.get('bounded_axis_experiment'):
            return super().validate_transform(placement)
        t = placement.transform
        if not np.isfinite([t.sx, t.sy, t.tx, t.ty]).all() or min(t.sx, t.sy) <= 0 or max(t.sx, t.sy) / min(t.sx, t.sy) > MAX_AXIS_RATIO:
            raise ValueError('invalid bounded axis experiment transform')


    def extend(self, ctx, initial_plan, policy=None, *, target_scope=None):
        """Independent arms start from frozen baseline. Never overwrite source data."""
        policy = policy or ExpansionPolicy()
        initial_plan, rule_log = self.filter_plan(ctx, initial_plan)
        if policy.anisotropic and not all((policy.context, policy.hierarchy, policy.nested, policy.whole_target)):
            raise ValueError('axis fallback requires the complete isotropic expansion first')
        if not any(asdict(policy).values()):
            return ctx, self.emit(ctx, initial_plan), dict(initial_plan), rule_log
        prefix_log = rule_log
        if policy.anisotropic:
            ctx, _, initial_plan, recursive_log = self.extend(ctx, initial_plan, replace(policy, anisotropic=False),
                                                             target_scope=target_scope)
            prefix_log += recursive_log
        probe = copy.copy(ctx)
        probe.graph, view_log = self.reuse_rules.view(ctx.graph)
        probe.pools = {**ctx.pools}
        log = list(prefix_log) + view_log
        if policy.nested:
            probe.graph, diagnostics = self.expanded(ctx.graph, self.v6.target_repository)
            log.append({'target_view_validation': diagnostics})
        inventory = self.inventory(policy.nested)
        nodes = [n for n in probe.graph.components if len(n.stroke_ids) >= 2 and
                 ((n.path == 'root' and policy.whole_target) or
                  (n.path != 'root' and (policy.hierarchy or not n.children_ids)))]
        nodes.sort(key=lambda n: (-len(n.stroke_ids), n.path))
        plan = dict(initial_plan)
        repair_ids = set()
        if self.variant_checks:
            for cid, p in list(plan.items()):
                evidence = self.variant_evidence(probe, p)
                if not evidence['accepted']:
                    del plan[cid]
                    repair_ids.update(p.ids)
                    log.append({'removed_inherited_candidate': p.candidate,
                                'variant_compatibility': evidence,
                                'fallback_reason': 'inherited positional key-stroke mismatch'})
        # Axis arm starts with exactly the isotropic output; never replaces a
        # successful isotropic placement merely to fit the reference more tightly.
        sink = observer()
        for node in nodes:
            ids = tuple(ordered_ids(probe.graph, node))
            if target_scope is not None and not set(ids) <= set(target_scope):
                continue
            overlap = {cid for cid, p in plan.items() if set(p.ids) & set(ids)}
            covered = set().union(*(set(plan[cid].ids) for cid in overlap)) if overlap else set()
            if set(ids) <= covered or covered - set(ids):
                continue
            if overlap and not (policy.hierarchy or node.path == 'root'):
                continue
            start = {cid: p for cid, p in plan.items() if cid not in overlap}
            proposals = []
            entries = inventory.get(identity(node), [])
            if sink is not None:
                emit(sink, 'component expansion', 'retrieval', 'found' if entries else 'no candidates',
                     index=node.component_id, target=ids, count=len(entries), bounded_axes=policy.anisotropic)
            for sg, sn, entry, errors in entries:
                if entry['character'] == ctx.character:
                    continue
                if not policy.hierarchy and node.path != 'root' and (sn.path == 'root' or sn.children_ids):
                    continue
                bridge_root = (policy.hierarchy and sn.path == 'root') or node.path == 'root'
                if not policy.context and not bridge_root and component_key(sg, sn) != component_key(probe.graph, node):
                    continue
                old_target_ids = {n.component_id for n in ctx.graph.components} | {n['component_id'] for n in ctx.baseline_meta['components']}
                old_source_ids = {n.component_id for n in self.v6.index.graph(entry['character']).components}
                reasons = []
                if policy.context and component_key(sg, sn) != component_key(probe.graph, node):
                    reasons.append('context bridge')
                if policy.hierarchy and (sn.path == 'root' or sn.children_ids or node.children_ids):
                    reasons.append('complete root/parent component')
                if policy.nested and (node.component_id not in old_target_ids or sn.component_id not in old_source_ids):
                    reasons.append('validated nested view')
                if policy.whole_target and node.path == 'root':
                    reasons.append('whole target')
                if policy.anisotropic:
                    reasons.append('bounded axis fallback')
                if set(ids) & repair_ids:
                    reasons.append('replace incompatible inherited source')
                if not reasons:
                    continue  # Do not mix ordinary-pool retries/top-16 changes into ablations.
                record = {'target_component': node.component_id, 'candidate': entry,
                          'axis_experiment': policy.anisotropic, 'expansion_reasons': reasons}
                if errors:
                    log.append({**record, 'rejected': errors})
                    if sink is not None:
                        donor = Donor(self.profile.writer_id, entry['character'], entry['sample_id'],
                                      entry['source_sha256'], tuple(entry['stroke_ids']), ids)
                        emit(sink, 'component expansion', 'admission', 'rejected', donor=donor, reason=errors)
                    continue
                try:
                    source = self.profile.source_trajectories[entry['sample_id']]
                    mapping = {s.standard_stroke_id: s for s in source.strokes}
                    evidence = None
                    if self.variant_checks:
                        evidence = self.check_variants(sg, sn, probe.graph, node,
                            [mapping[k] for k in entry['stroke_ids']])
                        if not evidence['accepted']:
                            log.append({**record, 'rejected': 'positional key-stroke mismatch',
                                        'variant_compatibility': evidence})
                            if sink is not None:
                                donor = Donor(self.profile.writer_id, entry['character'], entry['sample_id'],
                                              entry['source_sha256'], tuple(entry['stroke_ids']), ids)
                                emit(sink, 'component expansion', 'admission', 'rejected', donor=donor,
                                     reason=evidence['reason'], evidence=evidence)
                            continue
                    proof = correspondence(sg, sn, probe.graph, node, anisotropic=policy.anisotropic)
                    q = {**entry, 'expansion_correspondence': proof,
                         'bounded_axis_experiment': policy.anisotropic, 'expansion_reasons': reasons}
                    if evidence:
                        q['variant_compatibility'] = evidence
                    x = [mapping[k].points for k in q['stroke_ids']]
                    y = [s.median for s in probe.graph.strokes if s.stroke_id in ids]
                    indices = tuple(i for i, s in enumerate(probe.graph.strokes) if s.stroke_id in ids)
                    if policy.anisotropic:
                        # A matched-donor isotropic control prevents pool expansion
                        # or tail search from being misreported as an axis benefit.
                        try:
                            iso_proof = correspondence(sg, sn, probe.graph, node)
                            iso_q = {**q, 'bounded_axis_experiment': False,
                                     'expansion_correspondence': iso_proof}
                            iso_p = Placement(node.component_id, ids, indices, iso_q,
                                              fit_shared_similarity(x, y), 0.)
                            probe.pools[node.component_id] = [*probe.pools.get(node.component_id, []), iso_p]
                            _, control = self.attempt(probe, start, iso_p, source_aware=True)
                            if control['accepted']:
                                log.append({**record, 'rejected': 'same donor isotropic already feasible; not an axis benefit',
                                            'isotropic_control': control})
                                continue
                            q['isotropic_control'] = control
                        except ValueError as exc:
                            q['isotropic_control'] = {'accepted': False, 'rejected': str(exc)}
                    transform = (fit_bounded_axes if policy.anisotropic else fit_shared_similarity)(x, y)
                    score = float(np.linalg.norm(anchors([transform.apply(s) for s in x]) - anchors(y), axis=1).mean())
                    q['score'] = score
                    p = Placement(node.component_id, ids, indices, q, transform, score)
                    proposals.append(p)
                except ValueError as exc:
                    log.append({**record, 'rejected': str(exc)})
            proposals.sort(key=lambda p: (p.base_score, p.candidate['sample_id'], p.candidate['component_id']))
            probe.pools[node.component_id] = [*probe.pools.get(node.component_id, []), *proposals]
            for attempt_index, p in enumerate(proposals, 1):
                trial, diagnostic = self.attempt(probe, start, p, source_aware=True)
                diagnostic.update(target_component=node.component_id, replaced_components=sorted(overlap))
                if diagnostic['accepted'] and overlap:
                    # Replacement must be safe also against the previously accepted
                    # full glyph, not only against the temporarily restored reference.
                    before = self.emit(probe, plan)
                    after = self.emit(probe, trial)
                    from .contacts import contact_pairs
                    from .component_plan import curves
                    own = set(p.indices)
                    contacts = cross_boundary(contact_pairs(curves(after)) - contact_pairs(curves(before)), own)
                    crossings = cross_boundary(crossing_delta(curves(before), curves(after)), own)
                    diagnostic['replacement_new_boundary_contacts'] = sorted(contacts)
                    diagnostic['replacement_new_boundary_crossings'] = sorted(crossings)
                    if contacts or crossings:
                        diagnostic.update(accepted=False, fallback_reason='replacement introduces cross-boundary contact/crossing')
                log.append(diagnostic)
                if sink is not None:
                    q = p.candidate
                    donor = Donor(self.profile.writer_id, q['character'], q['sample_id'], q['source_sha256'],
                                  tuple(q['stroke_ids']), p.ids)
                    emit(sink, 'component expansion', 'decision',
                         'adopted' if diagnostic['accepted'] else 'rejected',
                         donor=donor, reason=diagnostic['fallback_reason'], attempt=attempt_index,
                         ranked=len(proposals), index=node.component_id,
                         replacement_crossings=diagnostic.get('replacement_new_boundary_crossings'),
                         replacement_contacts=diagnostic.get('replacement_new_boundary_contacts'))
                if diagnostic['accepted']:
                    plan = trial
                    break
        return probe, self.emit(probe, plan), plan, log
