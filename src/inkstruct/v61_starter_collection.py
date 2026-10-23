"""Opt-in cold-start collection projection; never simulates author trajectories.

Public structure compatibility is only an opportunity. Mapping, actual key forms,
candidate truncation, placement and collisions must be checked after collection.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from types import SimpleNamespace

from .component_views import expand_views
from .exemplar_index import ordered_ids
from .glyph_frame_exp import reference_frame
from .positional_variants import check_positional_variants
from .recommend import greedy_marginal_order
from .reuse_rules import ReuseRules
from .v6_integrated_exp import framed_graph
from .v61_author_strokes import stroke_class
from .v61_candidate_expansion import correspondence, identity

VERSION = "v61_starter_public_projection_v1"
PARAMETERS = {"component_weight": 1., "stroke_bucket_weight": .2,
              "second_donor_gain": .15, "max_capture_strokes": 16,
              "budgets": [32, 64, 96], "repeats": 1, "validation_count": 16}


def freeze_split(characters, count=16):
    """Freeze before ranking; future repetitions of held-out characters stay out."""
    held = sorted(characters, key=lambda c: hashlib.sha256(
        (VERSION + ":validation:" + c).encode()).hexdigest())[:count]
    return [c for c in characters if c not in held], held


def public_view(repository, character, *, target=False):
    graph = repository.get(character)
    if target:
        graph = framed_graph(graph, reference_frame(graph))
    # Match legacy source-index expansion followed by the current expansion arm.
    graph = expand_views(graph, repository).graph
    rules = ReuseRules(True)
    graph, _ = rules.view(graph)
    allowed = tuple(sorted({n.canonical for n in graph.components if len(n.canonical) == 1}))
    graph = expand_views(graph, repository, allowed=allowed, max_depth=2).graph
    return rules.view(graph)[0]


def public_pair(source, sn, target, tn):
    """Conservative positional proof using reference ONLY, not author evidence."""
    proof = correspondence(source, sn, target, tn)
    sm = {s.stroke_id: s for s in source.strokes}
    public_strokes = [SimpleNamespace(points=sm[k].median) for k in ordered_ids(source, sn)]
    variants = check_positional_variants(source, sn, target, tn, public_strokes)
    if not variants['accepted']:
        raise ValueError('public positional key-stroke mismatch')
    return {"correspondence": proof, "public_variant_checks": variants,
            "author_geometry_checked": False}


def project(sources, targets, *, progress=None):
    """Return stroke-union opportunities; overlapping components count once.

    Single-stroke buckets are a weaker independent proxy, not admitted sources.
    Whole-character self reuse is excluded from these cross-character metrics.
    """
    index, buckets = defaultdict(list), defaultdict(set)
    weights, labels = {}, {}
    for char, graph in targets.items():
        for stroke in graph.strokes:
            for kind, weight in [('component', PARAMETERS['component_weight']),
                                 ('bucket', PARAMETERS['stroke_bucket_weight'])]:
                key = f'{kind}/{char}/{stroke.stroke_id}'
                weights[key] = weight
            buckets[stroke_class(stroke.median)].add(f'bucket/{char}/{stroke.stroke_id}')
        for node in graph.components:
            if len(node.stroke_ids) >= 2 and node.confidence >= .8:
                index[identity(node)].append((graph, node))
    candidates, rejected = {}, Counter()
    for number, (char, graph) in enumerate(sources.items(), 1):
        opportunities, evidence = set(), []
        for kind in {stroke_class(s.median) for s in graph.strokes}:
            opportunities.update(k for k in buckets[kind] if k.split('/')[1] != char)
        for sn in graph.components:
            if len(sn.stroke_ids) < 2 or sn.confidence < .8:
                continue
            for target, tn in index[identity(sn)]:
                if target.character == char:
                    continue
                try:
                    proof = public_pair(graph, sn, target, tn)
                except ValueError as exc:
                    rejected[str(exc)] += 1
                    continue
                keys = {f'component/{target.character}/{sid}' for sid in tn.stroke_ids}
                opportunities.update(keys)
                for key in keys:
                    labels.setdefault(key, set()).add(tn.canonical)
                evidence.append({'source_component': sn.component_id,
                                 'source_stroke_ids': ordered_ids(graph, sn),
                                 'target_character': target.character,
                                 'target_component': tn.component_id,
                                 'target_stroke_ids': ordered_ids(target, tn),
                                 'canonical': tn.canonical, **proof})
        candidates[char] = {'stroke_count': len(graph.strokes),
                            'opportunities': sorted(opportunities), 'evidence': evidence}
        if progress and number % 50 == 0:
            progress(number, len(sources))
    return candidates, weights, {k: sorted(v) for k, v in labels.items()}, dict(rejected)


def select(candidates, weights, budget):
    """Reuse the existing lazy cover planner; simple captures cost less effort."""
    counts = Counter()

    def gain(c):
        return sum(weights[k] * (1 if counts[k] == 0 else
                                PARAMETERS['second_donor_gain'] if counts[k] == 1 else 0)
                   for k in candidates[c]['opportunities']) / math.sqrt(candidates[c]['stroke_count'])

    rows = []
    for char in greedy_marginal_order(candidates, gain,
                                      lambda c: (candidates[c]['stroke_count'], ord(c))):
        if len(rows) >= budget:
            break
        item = candidates[char]
        fresh = [k for k in item['opportunities'] if counts[k] == 0]
        second = [k for k in item['opportunities'] if counts[k] == 1]
        rows.append({'character': char, 'sequence': len(rows) + 1,
                     'stroke_count': item['stroke_count'], 'score': gain(char),
                     'new_opportunities': fresh, 'second_donor_opportunities': second})
        counts.update(item['opportunities'])
    return rows


def coverage(candidates, selected, targets):
    union = set().union(*(set(candidates[c]['opportunities']) for c in selected)) if selected else set()
    component = {k.removeprefix('component/') for k in union if k.startswith('component/')}
    bucket = {k.removeprefix('bucket/') for k in union if k.startswith('bucket/')}
    total = sum(len(g.strokes) for g in targets.values())
    unrecorded = {c: g for c, g in targets.items() if c not in selected}
    unseen_ids = {f'{c}/{s.stroke_id}' for c, g in unrecorded.items() for s in g.strokes}
    return {'target_characters': len(targets), 'target_strokes': total,
            'component_opportunity_strokes': len(component),
            'stroke_bucket_opportunity_strokes': len(bucket),
            'either_opportunity_strokes': len(component | bucket),
            'unrecorded_target_characters': len(unrecorded),
            'unrecorded_target_strokes': len(unseen_ids),
            'unrecorded_component_opportunity_strokes': len(component & unseen_ids),
            'unrecorded_either_opportunity_strokes': len((component | bucket) & unseen_ids),
            'capture_stroke_cost': sum(candidates[c]['stroke_count'] for c in selected),
            'actual_usable_coverage': None}
