from __future__ import annotations

import hashlib

import numpy as np

from .component_style import component_for_stroke, parent_layout
from .geometry import signature_key
from .schemas import CharacterGraph

CONTEXT_FEATURES = 16


def _hash_block(value: str) -> list[float]:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return [byte / 127.5 - 1.0 for byte in digest[:4]]


def stroke_factor_keys(graph: CharacterGraph, stroke_index: int) -> tuple[str, str, str, str]:
    stroke = graph.strokes[stroke_index]
    component = component_for_stroke(graph, stroke)
    canonical = component.canonical if component is not None else "root"
    role_layout = (
        f"{component.role}@{parent_layout(graph, component)}"
        if component is not None
        else "root@single"
    )
    signature = signature_key(stroke.signature)
    component_path = component.path if component is not None else stroke.component_path
    return canonical, role_layout, signature, component_path


def stroke_context_tokens(graph: CharacterGraph) -> np.ndarray:
    """Encode component, role/layout and stroke signature without a learned vocabulary."""

    return np.asarray(
        [
            [value for key in stroke_factor_keys(graph, index) for value in _hash_block(key)]
            for index in range(len(graph.strokes))
        ],
        dtype=np.float32,
    )


def observed_structure_keys(graph: CharacterGraph) -> set[str]:
    keys: set[str] = set()
    for index in range(len(graph.strokes)):
        canonical, role_layout, signature, component_path = stroke_factor_keys(graph, index)
        keys.update(
            {
                f"component:{canonical}",
                f"role-layout:{role_layout}",
                f"stroke-signature:{signature}",
                f"component-path:{component_path}",
            }
        )
    return keys
