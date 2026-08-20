from __future__ import annotations

import math

from .schemas import CharacterGraph, ComponentNode, Point2D, StandardStroke


def component_for_stroke(graph: CharacterGraph, stroke: StandardStroke) -> ComponentNode | None:
    by_path = {component.path: component for component in graph.components}
    component = by_path.get(stroke.component_path)
    if component is not None:
        return component
    return next(
        (component for component in graph.components if stroke.stroke_id in component.stroke_ids),
        None,
    )


def parent_layout(graph: CharacterGraph, component: ComponentNode) -> str:
    by_id = {value.component_id: value for value in graph.components}
    parent = by_id.get(component.parent_id) if component.parent_id else None
    return (parent.layout if parent and parent.layout else None) or "single"


def component_context_key(graph: CharacterGraph, component: ComponentNode) -> str:
    return "|".join(
        (
            component.canonical,
            component.glyph_variant,
            component.role,
            parent_layout(graph, component),
        )
    )


def component_stroke_slot(component: ComponentNode, stroke_id: str) -> tuple[int, int]:
    try:
        index = component.stroke_ids.index(stroke_id) + 1
    except ValueError:
        index = 1
    return index, max(1, len(component.stroke_ids))


def component_stroke_key(
    graph: CharacterGraph,
    component: ComponentNode,
    stroke_id: str,
    signature: str,
) -> str:
    index, count = component_stroke_slot(component, stroke_id)
    return f"{component_context_key(graph, component)}|{index}/{count}|{signature}"


def component_trajectory_key(graph: CharacterGraph, component: ComponentNode) -> str:
    """Key a whole-component trajectory without brittle per-stroke signatures."""
    return f"{component_context_key(graph, component)}|{len(component.stroke_ids)}"


def component_relation_key(graph: CharacterGraph, component: ComponentNode) -> str | None:
    by_id = {value.component_id: value for value in graph.components}
    parent = by_id.get(component.parent_id) if component.parent_id else None
    if parent is None or not parent.layout or len(parent.children_ids) < 2:
        return None
    children = [by_id[child_id] for child_id in parent.children_ids if child_id in by_id]
    roles = sorted(child.role for child in children)
    if len(roles) < 2 or len(set(roles)) != len(roles):
        return None
    return f"{parent.layout}|{','.join(roles)}"


def relative_bbox(
    child: tuple[float, float, float, float],
    parent: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    width = max(parent[2] - parent[0], 1e-6)
    height = max(parent[3] - parent[1], 1e-6)
    return (
        (child[0] - parent[0]) / width,
        (child[1] - parent[1]) / height,
        (child[2] - parent[0]) / width,
        (child[3] - parent[1]) / height,
    )


def absolute_bbox(
    relative: tuple[float, float, float, float],
    parent: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    width = max(parent[2] - parent[0], 1e-6)
    height = max(parent[3] - parent[1], 1e-6)
    return (
        parent[0] + relative[0] * width,
        parent[1] + relative[1] * height,
        parent[0] + relative[2] * width,
        parent[1] + relative[3] * height,
    )


def transform_between_bboxes(
    points: list[Point2D],
    source: tuple[float, float, float, float],
    target: tuple[float, float, float, float],
) -> list[Point2D]:
    source_width = max(source[2] - source[0], 1e-6)
    source_height = max(source[3] - source[1], 1e-6)
    target_width = max(target[2] - target[0], 1e-6)
    target_height = max(target[3] - target[1], 1e-6)
    return [
        (
            target[0] + (point[0] - source[0]) / source_width * target_width,
            target[1] + (point[1] - source[1]) / source_height * target_height,
        )
        for point in points
        if math.isfinite(point[0]) and math.isfinite(point[1])
    ]
