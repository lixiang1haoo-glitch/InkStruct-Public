"""Conservative, non-destructive nested component views for exemplar retrieval."""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from ..contextual_trajectory import anchors, fit_shared_similarity
from ..geometry import bbox
from ..schemas import CharacterGraph, ComponentNode

VIEW_VERSION = 'nested_component_views_v1'


@dataclass
class ComponentViews:
    graph: CharacterGraph
    diagnostics: list[dict]


def expand_views(graph, repository, *, allowed=('敫', '多'), max_depth=2):
    """Use independent component records only after complete ordered-shape validation.

    Standard IDs, order, medians and original graphs remain untouched. Existing
    children are not replaced. This graph is for retrieval, not legacy generation.
    """
    view = copy.deepcopy(graph)
    diagnostics = []
    stroke_map = {s.stroke_id: s for s in graph.strokes}
    queue = [(n, 0, {graph.character}) for n in view.components if not n.children_ids]
    while queue:
        node, depth, visited = queue.pop(0)
        if node.path == 'root' or node.canonical not in allowed or depth >= max_depth:
            continue
        record = {'component_id': node.component_id, 'canonical': node.canonical,
                  'source_character': node.glyph_variant, 'expanded': False}
        diagnostics.append(record)
        if node.glyph_variant in visited or len(node.glyph_variant) != 1:
            record['reason'] = 'cycle or non-character component'
            continue
        try:
            independent = repository.get(node.glyph_variant)
        except (KeyError, ValueError):
            record['reason'] = 'independent component record unavailable'
            continue
        if len(independent.strokes) != len(node.stroke_ids) or independent.component_warnings:
            record['reason'] = 'stroke count mismatch or incomplete independent decomposition'
            continue
        ids = [s.stroke_id for s in graph.strokes if s.stroke_id in set(node.stroke_ids)]
        source = [s.median for s in independent.strokes]
        target = [stroke_map[s].median for s in ids]
        try:
            transform = fit_shared_similarity(source, target)
        except ValueError as exc:
            record['reason'] = f'invalid ordered geometry: {exc}'
            continue
        fitted = [transform.apply(s) for s in source]
        box = bbox([p for s in target for p in s])
        span = max(box[2] - box[0], box[3] - box[1], 1e-9)
        errors = np.linalg.norm(anchors(fitted) - anchors(target), axis=1) / span
        record['normalized_mean_error'] = float(errors.mean())
        record['normalized_max_error'] = float(errors.max())
        if errors.mean() > .08 or errors.max() > .22:
            record['reason'] = 'ordered shape correspondence not reliable'
            continue
        root = next(n for n in independent.components if n.path == 'root')
        if not root.children_ids:
            record['reason'] = 'independent record is already terminal'
            continue
        id_map = {s.stroke_id: target_id for s, target_id in zip(independent.strokes, ids, strict=True)}
        component_ids = {n.component_id: f'{node.component_id}::view::{n.component_id}'
                         for n in independent.components if n.path != 'root'}
        component_ids[root.component_id] = node.component_id
        new_nodes = []
        for child in independent.components:
            if child.path == 'root':
                continue
            mapped = [id_map[s] for s in child.stroke_ids]
            new_nodes.append(ComponentNode(component_ids[child.component_id],
                node.path + '.view' + child.path.removeprefix('root'), child.canonical,
                child.glyph_variant, child.role, component_ids[child.parent_id],
                [component_ids[k] for k in child.children_ids], mapped,
                bbox([p for k in mapped for p in stroke_map[k].median]), child.layout,
                min(node.confidence, child.confidence)))
        node.children_ids = [component_ids[k] for k in root.children_ids]
        node.layout = root.layout
        view.components.extend(new_nodes)
        queue.extend((n, depth + 1, visited | {node.glyph_variant}) for n in new_nodes if not n.children_ids)
        record.update({'expanded': True, 'reason': None, 'stroke_id_mapping': id_map,
                       'new_component_ids': [n.component_id for n in new_nodes],
                       'independent_source_version': independent.source_version})
    return ComponentViews(view, diagnostics)
