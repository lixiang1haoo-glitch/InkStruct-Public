"""Opt-in acquisition planning from actual v6.1 instance admission, not prototypes.

Only real trajectories establish current usable coverage. Future captures carry
public-structure compatibility evidence and remain conditional projections.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict

import numpy as np

from .component_views import expand_views
from .exemplar_index import component_key, reference_compatibility
from .geometry import path_length
from .recommend import greedy_marginal_order
from .structures import MAINLAND_SIMPLIFIED_PACKAGE, character_package
from .v6_exp import NESTED_COMPONENTS

SPLIT_SEED = 'v61-collection-user001-future-validation-v1:'


def public_view(repository, character):
    return expand_views(repository.get(character), repository, allowed=NESTED_COMPONENTS).graph


def indexed_leaves(graph):
    return [n for n in graph.components if n.path != 'root' and not n.children_ids
            and len(n.stroke_ids) >= 2 and n.confidence >= .8]


def freeze_validation(repository, sampled, development, common, count=8):
    keys = {component_key(g,n) for c in development for g in [public_view(repository,c)]
            for n in indexed_leaves(g)}
    possible = []
    for c in common:
        if c in sampled or c in development:
            continue
        try:
            g = public_view(repository,c)
        except KeyError:
            continue
        if 3 <= len(g.strokes) <= 16 and any(component_key(g,n) in keys for n in indexed_leaves(g)):
            possible.append(c)
    return sorted(possible,key=lambda c:hashlib.sha256((SPLIT_SEED+c).encode()).hexdigest())[:count]


def audit_targets(engine, characters):
    slots, glyphs = {}, {}
    for c in characters:
        ctx = engine.prepare(c)
        target = engine.v6.target_repository.get(c)
        # Retrieval view has the same IDs as the frozen proposal records.
        view = public_view(engine.v6.target_repository,c)
        nodes = {n.component_id:n for n in view.components}
        accepted = {i for p in ctx.baseline_plan.values() for i in p.indices}
        glyphs[c] = {'stroke_count':len(ctx.graph.strokes),'actual_source_strokes':len(accepted),
                     'reference_strokes':len(ctx.graph.strokes)-len(accepted),
                     'baseline':asdict(ctx.baseline), 'reference_version':target.source_version}
        for part in ctx.baseline_meta['components']:
            cid = part['component_id']; node = nodes[cid]
            pool = ctx.pools[cid]; trials = []
            for p in pool:
                proposal = engine.emit(ctx,{**ctx.baseline_plan,cid:p})
                checks = engine.validate(ctx,proposal)
                ratios = [path_length(x)/max(path_length(ctx.graph.strokes[i].median),1e-9)
                          for i,x in zip(p.indices,engine.placed(p),strict=True)]
                safe = engine.safe(checks) and min(ratios)>=.4 and max(ratios)<=2.5
                trials.append({'candidate':p.candidate,'transform':asdict(p.transform),
                               'checks':checks,'length_ratios':ratios,'safe_fixed_context':safe})
            safe_characters = sorted({t['candidate']['character'] for t in trials if t['safe_fixed_context']})
            canonical_entries = [p for key,entries in engine.v6.index.by_key.items()
                                 if key.split('|')[0]==node.canonical for p in entries]
            same_context = engine.v6.index.by_key.get(component_key(view,node),[])
            status = ('has_multiple_safe_donor_characters' if len(safe_characters)>=2 else
                      'only_one_safe_donor_character' if safe_characters else
                      'existing_pool_rejected_by_placement_review_first' if pool else
                      'reference_shape_filter_review_first' if same_context else
                      'missing_eligible_context')
            key = f'{c}/{cid}'
            slots[key] = {'slot_id':key,'character':c,'component_id':cid,'canonical':node.canonical,
                'context_key':component_key(view,node),'stroke_ids':part['target_stroke_ids'],
                'stroke_count':len(part['target_stroke_ids']), 'status':status,
                'actual_selected':cid in ctx.baseline_plan,'safe_donor_characters':safe_characters,
                'eligible_pool_size':len(pool),'same_context_index_entries':len(same_context),
                'other_context_donor_characters':sorted({p['character'] for p in canonical_entries}),
                'whole_character_captures':sum(s.character==node.canonical
                                              for s in engine.profile.source_trajectories.values()),
                'trials':trials,'nested': '::view::' in cid}
    return slots,glyphs


def projected_candidates(engine, slots, sampled, forbidden, common, max_strokes=16, *, only_gaps=True):
    """Public compatibility only. Never invent future source points or confidence."""
    keys = defaultdict(list)
    for slot in slots.values():
        if not only_gaps or slot['status'] in ('missing_eligible_context','only_one_safe_donor_character'):
            keys[slot['context_key']].append(slot)
    targets = {c:public_view(engine.v6.target_repository,c) for c in {s['character'] for s in slots.values()}}
    result = {}
    for graph in engine.v6.mapping_repository.iter_graphs():
        c = graph.character
        if c in sampled or c in forbidden or character_package(c)!=MAINLAND_SIMPLIFIED_PACKAGE:
            continue
        # A small human collection should not prefer rare characters solely for
        # packing several structural features into one task. Retain GB2312 level 1
        # plus the project's curated common list; do not tune this on holdout results.
        if c not in common and not 0xB0 <= c.encode('gb2312')[0] <= 0xD7:
            continue
        if not 3<=len(graph.strokes)<=max_strokes or graph.component_warnings:
            continue
        view = engine.v6.index.graph(c)
        opportunities = {}
        for n in indexed_leaves(view):
            for slot in keys.get(component_key(view,n),[]):
                target = targets[slot['character']]
                tn = next(x for x in target.components if x.component_id==slot['component_id'])
                shape, aspect = reference_compatibility(target,tn,view,n)
                if shape>.18 or aspect>.7:
                    continue
                opportunities[slot['slot_id']] = {'source_component_id':n.component_id,
                    'source_stroke_ids':n.stroke_ids,'shape_error':shape,'log_aspect_error':aspect,
                    'assumption':'complete author capture, reliable mapping, actual box and placement not yet checked'}
        if opportunities:
            result[c] = {'character':c,'stroke_count':len(graph.strokes),'common_list':c in common,
                         'opportunities':opportunities}
    return result


def select_budget(candidates, slots, budget=12):
    """Same lazy set-cover engine as legacy planner; diminishing distinct-donor gain."""
    counts = {key:len(s['safe_donor_characters']) for key,s in slots.items()}
    initial = dict(counts)
    def gain(c):
        mass = sum(slots[k]['stroke_count']*(4 if counts[k]==0 else 1 if counts[k]==1 else 0)
                   for k in candidates[c]['opportunities'])
        # Prefer familiar/simple acquisition tasks, without claiming a success probability.
        cost = np.sqrt(candidates[c]['stroke_count']) * (1 if candidates[c]['common_list'] else 1.5)
        return float(mass/cost)
    order = greedy_marginal_order(candidates,gain,
        lambda c:(not candidates[c]['common_list'],candidates[c]['stroke_count'],ord(c)))
    selected = []
    for c in order:
        if len(selected)>=budget:
            break
        marginal = [k for k in candidates[c]['opportunities'] if counts[k]<2]
        score = gain(c)
        for k in candidates[c]['opportunities']:
            counts[k] += 1
        selected.append({**candidates[c],'sequence':len(selected)+1,'repeats':2,
                         'marginal_score':score,'marginal_slots':marginal})
    return {'recommendations':selected,'initial_distinct_safe_donors':initial,
            'projected_distinct_donors_if_all_admitted':counts,
            'projected_first_source_slots':[k for k in counts if initial[k]==0 and counts[k]>0],
            'projected_second_source_slots':[k for k in counts if initial[k]<2 and counts[k]>=2],
            'objective':'stroke-weighted first source 4 / second distinct donor character 1; '
                        'divided by sqrt(strokes), uncommon cost x1.5; not probability or quality',
            'budget':budget,'global_optimality_claimed':False,'actual_new_usable_sources':0}


def coverage_summary(slots,glyphs):
    return {'glyphs':len(glyphs),'total_strokes':sum(g['stroke_count'] for g in glyphs.values()),
            'actual_source_strokes':sum(g['actual_source_strokes'] for g in glyphs.values()),
            'actual_reference_strokes':sum(g['reference_strokes'] for g in glyphs.values()),
            'component_slots':len(slots),'status_counts':dict(Counter(s['status'] for s in slots.values()))}
