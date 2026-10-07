from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .canvas_boundary import BOUNDARY_POLICY, fit_glyph_to_canvas
from .component_style import (
    absolute_bbox,
    component_context_key,
    component_for_stroke,
    component_relation_key,
    component_stroke_key,
    component_stroke_slot,
    component_trajectory_key,
    parent_layout,
    relative_bbox,
    transform_between_bboxes,
)
from .factorized import stroke_context_tokens
from .geometry import bbox, clamp01, cubic_bspline, path_length, resample, signature_key
from .profile import load_profile
from .render import render_png, render_svg
from .samples import sha256_file
from .schemas import (
    CharacterGraph,
    ComponentLayoutPrototype,
    ComponentNode,
    ComponentRelationPrototype,
    ComponentStrokePrototype,
    ComponentTrajectoryPrototype,
    GeneratedGlyph,
    GeneratedPoint,
    GeneratedStroke,
    Point2D,
    StrokePrototype,
    StyleProfile,
)
from .structures import StructureRepository

DEFAULT_OUTPUT_ROOT = Path("outputs")


class DeterministicGenerator:
    def __init__(
        self,
        profile: StyleProfile,
        structure_version: str,
        component_conditioning: bool | str = True,
        component_strength: float = 1.0,
    ):
        self.profile = profile
        self.structure_version = structure_version
        self.component_mode = (
            component_conditioning
            if isinstance(component_conditioning, str)
            else ("adaptive" if component_conditioning else "off")
        )
        if self.component_mode not in {"off", "stroke", "layout", "full", "adaptive"}:
            raise ValueError(f"unknown component conditioning mode: {self.component_mode}")
        if not 0.0 <= component_strength <= 1.5:
            raise ValueError("component strength must be inside [0, 1.5]")
        self.component_strength = component_strength
        self.component_conditioning = self.component_mode != "off"
        self.by_signature: dict[str, list[StrokePrototype]] = {}
        for prototype in profile.prototypes.values():
            self.by_signature.setdefault(prototype.signature, []).append(prototype)
        self.layouts_by_canonical: dict[str, list[ComponentLayoutPrototype]] = {}
        for prototype in profile.component_layouts.values():
            self.layouts_by_canonical.setdefault(prototype.canonical, []).append(prototype)
        self.character_layouts = profile.character_layouts
        self.strokes_by_canonical: dict[str, list[ComponentStrokePrototype]] = {}
        for prototype in profile.component_strokes.values():
            self.strokes_by_canonical.setdefault(prototype.canonical, []).append(prototype)
        self.component_relations = profile.component_relations
        self.component_trajectories_by_canonical: dict[str, list[ComponentTrajectoryPrototype]] = {}
        for prototype in profile.component_trajectories.values():
            self.component_trajectories_by_canonical.setdefault(prototype.canonical, []).append(
                prototype
            )
        self.character_component_trajectories = profile.character_component_trajectories

    def _global_transform(self, points: list[Point2D]) -> list[Point2D]:
        style = self.profile.global_style
        scale_x = style.get("scale_x", 1.0)
        scale_y = style.get("scale_y", 1.0)
        offset_x = style.get("offset_x", 0.0)
        offset_y = style.get("offset_y", 0.0)
        slant = style.get("slant", 0.0)
        return [
            (
                0.5 + (x - 0.5) * scale_x + (y - 0.5) * slant + offset_x,
                0.5 + (y - 0.5) * scale_y + offset_y,
            )
            for x, y in points
        ]

    def _prototype(
        self, signature: str, component_path: str
    ) -> tuple[StrokePrototype | None, bool]:
        exact = self.profile.prototypes.get(f"{signature}@{component_path}")
        if exact is not None:
            return exact, True
        candidates = self.by_signature.get(signature, [])
        if not candidates:
            return None, False
        return max(candidates, key=lambda value: (value.sample_count, value.confidence)), False

    def _layout_prototype(
        self, graph: CharacterGraph, component: ComponentNode
    ) -> tuple[ComponentLayoutPrototype | None, float, bool]:
        if self.component_mode not in {"layout", "full", "adaptive"}:
            return None, 0.0, False
        key = component_context_key(graph, component)
        direct = self.character_layouts.get(f"{graph.character}::{key}")
        if direct is not None:
            if self.component_mode == "adaptive":
                damping = min(0.85, 0.50 + direct.sample_count * 0.10)
                return direct, damping * self.component_strength, True
            return direct, min(1.0, self.component_strength), True
        exact = self.profile.component_layouts.get(key)
        if exact is not None:
            if self.component_mode == "adaptive":
                if exact.source_character_count < 2:
                    return None, 0.0, False
                damping = min(0.35, 0.12 + exact.source_character_count * 0.06)
                return exact, damping * self.component_strength, True
            reliability = min(0.80, 0.40 + exact.source_character_count * 0.10)
            return exact, reliability, True
        candidates = self.layouts_by_canonical.get(component.canonical, [])
        if not candidates:
            return None, 0.0, False
        layout = parent_layout(graph, component)

        def rank(value: ComponentLayoutPrototype) -> tuple[float, int, float]:
            score = 0.0
            score += 3.0 if value.glyph_variant == component.glyph_variant else 0.0
            score += 2.0 if value.role == component.role else 0.0
            score += 1.0 if value.parent_layout == layout else 0.0
            return score, value.source_character_count, value.confidence

        selected = max(candidates, key=rank)
        score = rank(selected)[0]
        if self.component_mode == "adaptive":
            if selected.source_character_count < 3 or score < 5.0:
                return None, 0.0, False
            damping = min(0.25, 0.10 + selected.source_character_count * 0.04)
            return selected, damping * self.component_strength, False
        reliability = min(0.70, 0.35 + selected.source_character_count * 0.08)
        damping = reliability * (0.55 + 0.45 * score / 6.0)
        return selected, damping, False

    def _component_stroke_prototype(
        self,
        graph: CharacterGraph,
        component: ComponentNode,
        stroke_id: str,
        signature: str,
    ) -> tuple[ComponentStrokePrototype | None, float, bool]:
        if self.component_mode not in {"stroke", "full", "adaptive"}:
            return None, 0.0, False
        key = component_stroke_key(graph, component, stroke_id, signature)
        exact = self.profile.component_strokes.get(key)
        if exact is not None:
            if self.component_mode == "adaptive":
                if exact.source_character_count < 3:
                    return None, 0.0, False
                weight = min(0.55, 0.20 + exact.source_character_count * 0.10)
                return exact, min(0.75, weight * self.component_strength), True
            reliability = min(0.90, 0.50 + exact.source_character_count * 0.10)
            return exact, reliability, True
        candidates = self.strokes_by_canonical.get(component.canonical, [])
        if not candidates:
            return None, 0.0, False
        slot, count = component_stroke_slot(component, stroke_id)
        layout = parent_layout(graph, component)

        def rank(value: ComponentStrokePrototype) -> tuple[float, int, float]:
            score = 0.0
            score += 4.0 if value.signature == signature else 0.0
            score += 3.0 if value.component_stroke_index == slot else 0.0
            score += 1.0 if value.component_stroke_count == count else 0.0
            score += 2.0 if value.glyph_variant == component.glyph_variant else 0.0
            score += 2.0 if value.role == component.role else 0.0
            score += 1.0 if value.parent_layout == layout else 0.0
            return score, value.source_character_count, value.confidence

        compatible = [
            value
            for value in candidates
            if value.signature == signature or value.component_stroke_index == slot
        ]
        if not compatible:
            return None, 0.0, False
        selected = max(compatible, key=rank)
        score = rank(selected)[0]
        if self.component_mode == "adaptive":
            if selected.source_character_count < 2 or score < 9.0:
                return None, 0.0, False
            weight = min(0.42, 0.14 + selected.source_character_count * 0.07)
            return selected, min(0.60, weight * self.component_strength), False
        reliability = min(0.82, 0.42 + selected.source_character_count * 0.08)
        damping = reliability * (0.50 + 0.50 * score / 13.0)
        return selected, damping, False

    def _component_geometry_prototype(
        self,
        graph: CharacterGraph,
        component: ComponentNode,
        stroke_id: str,
        signature: str,
    ) -> tuple[ComponentStrokePrototype | None, float, bool]:
        if self.component_mode not in {"stroke", "full", "adaptive"}:
            return None, 0.0, False
        key = component_stroke_key(graph, component, stroke_id, signature)
        exact = self.profile.component_strokes.get(key)
        if exact is not None:
            if self.component_mode == "adaptive":
                weight = min(0.68, 0.28 + exact.source_character_count * 0.12)
                return exact, weight * self.component_strength, True
            return exact, min(1.0, self.component_strength), True
        candidates = self.strokes_by_canonical.get(component.canonical, [])
        if not candidates:
            return None, 0.0, False
        slot, count = component_stroke_slot(component, stroke_id)
        layout = parent_layout(graph, component)

        def rank(value: ComponentStrokePrototype) -> tuple[float, int, float]:
            score = 0.0
            score += 5.0 if value.signature == signature else 0.0
            score += 4.0 if value.component_stroke_index == slot else 0.0
            score += 1.0 if value.component_stroke_count == count else 0.0
            score += 2.0 if value.glyph_variant == component.glyph_variant else 0.0
            score += 2.0 if value.role == component.role else 0.0
            score += 1.0 if value.parent_layout == layout else 0.0
            return score, value.source_character_count, value.confidence

        compatible = [
            value
            for value in candidates
            if value.signature == signature or value.component_stroke_index == slot
        ]
        if not compatible:
            return None, 0.0, False
        selected = max(compatible, key=rank)
        score = rank(selected)[0]
        if self.component_mode == "adaptive":
            if score < 10.0:
                return None, 0.0, False
            weight = min(0.35, 0.12 + selected.source_character_count * 0.06)
            return selected, weight * self.component_strength, False
        return selected, min(0.75, self.component_strength * score / 15.0), False

    def _relation_prototype(
        self, graph: CharacterGraph, component: ComponentNode
    ) -> tuple[ComponentRelationPrototype | None, float]:
        if self.component_mode not in {"layout", "full", "adaptive"}:
            return None, 0.0
        key = component_relation_key(graph, component)
        prototype = self.component_relations.get(key) if key else None
        if prototype is None or component.role not in prototype.bbox_deltas:
            return None, 0.0
        if self.component_mode == "adaptive":
            if prototype.source_character_count < 5:
                return None, 0.0
            weight = min(0.24, 0.08 + prototype.source_character_count * 0.008)
            return prototype, weight * self.component_strength
        return prototype, min(0.55, self.component_strength * 0.45)

    def _component_trajectory_prototype(
        self, graph: CharacterGraph, component: ComponentNode
    ) -> tuple[ComponentTrajectoryPrototype | None, float, bool, bool]:
        """Select one coherent trajectory for every stroke in a component."""
        if self.component_mode not in {"stroke", "full", "adaptive"}:
            return None, 0.0, False, False
        key = component_trajectory_key(graph, component)
        direct = self.character_component_trajectories.get(f"{graph.character}::{key}")
        if direct is not None and direct.stroke_count == len(component.stroke_ids):
            weight = min(1.0, 0.92 + direct.sample_count * 0.03)
            return direct, weight * self.component_strength, True, True
        exact = self.profile.component_trajectories.get(key)
        if exact is not None and exact.stroke_count == len(component.stroke_ids):
            if self.component_mode == "adaptive":
                if exact.source_character_count < 2:
                    return None, 0.0, False, False
                reliability = max(0.55, min(1.0, exact.confidence / 0.70))
                weight = min(0.88, 0.48 + exact.source_character_count * 0.08)
                return exact, weight * reliability * self.component_strength, True, False
            return exact, min(1.0, self.component_strength), True, False
        candidates = [
            value
            for value in self.component_trajectories_by_canonical.get(component.canonical, [])
            if value.stroke_count == len(component.stroke_ids)
        ]
        if not candidates:
            return None, 0.0, False, False
        layout = parent_layout(graph, component)

        def rank(value: ComponentTrajectoryPrototype) -> tuple[float, int, float]:
            score = 0.0
            score += 3.0 if value.glyph_variant == component.glyph_variant else 0.0
            score += 2.0 if value.role == component.role else 0.0
            score += 1.0 if value.parent_layout == layout else 0.0
            return score, value.source_character_count, value.confidence

        selected = max(candidates, key=rank)
        score = rank(selected)[0]
        if self.component_mode == "adaptive":
            if selected.source_character_count < 3 or score < 5.0:
                return None, 0.0, False, False
            reliability = max(0.50, min(1.0, selected.confidence / 0.70))
            weight = min(0.72, 0.38 + selected.source_character_count * 0.06)
            return selected, weight * reliability * self.component_strength, False, False
        return selected, min(0.85, self.component_strength * score / 6.0), False, False

    def _component_controls(
        self,
        graph: CharacterGraph,
        component: ComponentNode | None,
        controls: list[Point2D],
        *,
        layout_damping_override: float | None = None,
        allow_relation: bool = True,
    ) -> tuple[
        list[Point2D],
        ComponentLayoutPrototype | None,
        bool,
        tuple[float, float, float, float] | None,
        ComponentRelationPrototype | None,
    ]:
        if component is None:
            return controls, None, False, None, None
        prototype, damping, exact = self._layout_prototype(graph, component)
        if prototype is not None and layout_damping_override is not None:
            damping = layout_damping_override * self.component_strength
        relation, relation_damping = (
            self._relation_prototype(graph, component) if allow_relation else (None, 0.0)
        )
        if (prototype is None or damping <= 0) and (relation is None or relation_damping <= 0):
            return controls, None, False, component.bbox, None
        glyph_bbox = bbox([point for stroke in graph.strokes for point in stroke.median])
        standard_relative = relative_bbox(component.bbox, glyph_bbox)
        layout_delta = prototype.bbox_delta if prototype is not None else (0.0,) * 4
        desired_relative = tuple(
            max(-0.10, min(1.10, value + delta * damping))
            for value, delta in zip(standard_relative, layout_delta)
        )
        if desired_relative[2] - desired_relative[0] < 0.02:
            return controls, None, False, component.bbox, None
        if desired_relative[3] - desired_relative[1] < 0.02:
            return controls, None, False, component.bbox, None
        target_bbox = absolute_bbox(desired_relative, glyph_bbox)
        if relation is not None and relation_damping > 0:
            by_id = {value.component_id: value for value in graph.components}
            parent = by_id.get(component.parent_id) if component.parent_id else None
            if parent is not None:
                relation_standard = relative_bbox(component.bbox, parent.bbox)
                relation_desired = tuple(
                    max(-0.10, min(1.10, value + delta * relation_damping))
                    for value, delta in zip(relation_standard, relation.bbox_deltas[component.role])
                )
                relation_bbox = absolute_bbox(relation_desired, parent.bbox)
                target_bbox = tuple(
                    target + relation_target - standard
                    for target, relation_target, standard in zip(
                        target_bbox, relation_bbox, component.bbox
                    )
                )
        return (
            transform_between_bboxes(controls, component.bbox, target_bbox),
            prototype,
            exact,
            target_bbox,
            relation,
        )

    def _whole_component_controls(
        self, graph: CharacterGraph
    ) -> dict[
        str,
        tuple[
            list[Point2D],
            ComponentTrajectoryPrototype,
            bool,
            bool,
            ComponentLayoutPrototype | None,
            bool,
            ComponentRelationPrototype | None,
        ],
    ]:
        """Place all strokes of each component in one shared target frame."""
        by_stroke_id = {stroke.stroke_id: stroke for stroke in graph.strokes}
        result = {}
        for component in graph.components:
            if component.path == "root" or component.children_ids:
                continue
            if len(component.stroke_ids) < 2:
                continue
            if any(stroke_id not in by_stroke_id for stroke_id in component.stroke_ids):
                continue
            prototype, damping, exact, direct = self._component_trajectory_prototype(
                graph, component
            )
            if prototype is None or damping <= 0:
                continue
            first_stroke = by_stroke_id[component.stroke_ids[0]]
            (
                _,
                layout_prototype,
                layout_exact,
                target_bbox,
                relation_prototype,
            ) = self._component_controls(
                graph,
                component,
                resample(first_stroke.median, 8),
                layout_damping_override=1.0 if direct else None,
                allow_relation=not direct,
            )
            if target_bbox is None:
                target_bbox = component.bbox
            width = max(target_bbox[2] - target_bbox[0], 1e-6)
            height = max(target_bbox[3] - target_bbox[1], 1e-6)
            for index, stroke_id in enumerate(component.stroke_ids):
                standard = by_stroke_id[stroke_id]
                standard_controls = transform_between_bboxes(
                    resample(standard.median, 8), component.bbox, target_bbox
                )
                local_controls = prototype.stroke_controls[index]
                learned_controls = [
                    (target_bbox[0] + x * width, target_bbox[1] + y * height)
                    for x, y in local_controls
                ]
                controls = [
                    (
                        standard_point[0] * (1.0 - damping) + learned_point[0] * damping,
                        standard_point[1] * (1.0 - damping) + learned_point[1] * damping,
                    )
                    for standard_point, learned_point in zip(standard_controls, learned_controls)
                ]
                result[stroke_id] = (
                    controls,
                    prototype,
                    direct,
                    exact,
                    layout_prototype,
                    layout_exact,
                    relation_prototype,
                )
        return result

    def _stroke_geometry_controls(
        self,
        graph: CharacterGraph,
        component: ComponentNode | None,
        standard,
        controls: list[Point2D],
        component_bbox: tuple[float, float, float, float] | None,
    ) -> tuple[list[Point2D], ComponentStrokePrototype | None, bool]:
        if component is None or component_bbox is None:
            return controls, None, False
        signature = signature_key(standard.signature)
        prototype, damping, exact = self._component_geometry_prototype(
            graph, component, standard.stroke_id, signature
        )
        if prototype is None or damping <= 0:
            return controls, None, False
        standard_relative = relative_bbox(standard.bbox, component.bbox)
        desired_relative = tuple(
            max(-0.15, min(1.15, value + delta * damping))
            for value, delta in zip(standard_relative, prototype.stroke_bbox_delta)
        )
        if desired_relative[2] - desired_relative[0] < 0.005:
            return controls, None, False
        if desired_relative[3] - desired_relative[1] < 0.005:
            return controls, None, False
        target_bbox = absolute_bbox(desired_relative, component_bbox)
        transformed = transform_between_bboxes(controls, bbox(controls), target_bbox)
        component_width = max(component_bbox[2] - component_bbox[0], 1e-6)
        component_height = max(component_bbox[3] - component_bbox[1], 1e-6)
        if transformed:
            transformed[0] = (
                transformed[0][0] + prototype.start_delta[0] * damping * component_width,
                transformed[0][1] + prototype.start_delta[1] * damping * component_height,
            )
            transformed[-1] = (
                transformed[-1][0] + prototype.end_delta[0] * damping * component_width,
                transformed[-1][1] + prototype.end_delta[1] * damping * component_height,
            )
        return transformed, prototype, exact

    def generate(self, graph: CharacterGraph) -> GeneratedGlyph:
        return fit_glyph_to_canvas(self._generate_raw(graph))

    def _generate_raw(self, graph: CharacterGraph) -> GeneratedGlyph:
        """Internal unbounded geometry, also used in the neural memory blend."""
        generated: list[GeneratedStroke] = []
        time_cursor = 0
        stroke_confidences: list[float] = []
        whole_components = self._whole_component_controls(graph)
        for standard in graph.strokes:
            signature = signature_key(standard.signature)
            component = component_for_stroke(graph, standard)
            whole_component = whole_components.get(standard.stroke_id)
            if whole_component is not None:
                (
                    raw_controls,
                    trajectory_prototype,
                    trajectory_direct,
                    trajectory_exact,
                    layout_prototype,
                    layout_exact,
                    relation_prototype,
                ) = whole_component
                component_bbox = component.bbox if component is not None else None
                geometry_prototype = None
                geometry_exact = False
            else:
                trajectory_prototype = None
                trajectory_direct = False
                trajectory_exact = False
                raw_controls = resample(standard.median, 8)
                (
                    raw_controls,
                    layout_prototype,
                    layout_exact,
                    component_bbox,
                    relation_prototype,
                ) = self._component_controls(graph, component, raw_controls)
                raw_controls, geometry_prototype, geometry_exact = self._stroke_geometry_controls(
                    graph, component, standard, raw_controls, component_bbox
                )
            base_controls = np.asarray(raw_controls, dtype=np.float64)
            component_prototype = None
            component_damping = 0.0
            component_exact = False
            if component is not None:
                component_prototype, component_damping, component_exact = (
                    self._component_stroke_prototype(
                        graph, component, standard.stroke_id, signature
                    )
                )
            legacy_prototype, legacy_exact = self._prototype(signature, standard.component_path)
            if component_prototype is not None:
                if self.component_mode == "adaptive" and legacy_prototype is not None:
                    weight = component_damping
                    legacy_damping = 1.0 if legacy_exact else 0.60
                    component_residual = np.asarray(component_prototype.residual, dtype=np.float64)
                    legacy_residual = np.asarray(legacy_prototype.residual, dtype=np.float64)
                    blended_residual = (
                        legacy_residual * legacy_damping * (1.0 - weight)
                        + component_residual * weight
                    )
                    blended_pressure = (
                        np.asarray(legacy_prototype.pressure) * (1.0 - weight)
                        + np.asarray(component_prototype.pressure) * weight
                    )
                    prototype = component_prototype
                    exact = component_exact
                    residual_damping = 1.0
                    pressure_override = [float(value) for value in blended_pressure]
                    duration_override = (
                        legacy_prototype.duration_ms * (1.0 - weight)
                        + component_prototype.duration_ms * weight
                    )
                    residual_override = blended_residual
                    style_source = "component_blend_exact" if exact else "component_blend_fallback"
                else:
                    prototype = component_prototype
                    exact = component_exact
                    residual_damping = component_damping
                    pressure_override = None
                    duration_override = None
                    residual_override = None
                    style_source = "component_exact" if exact else "component_fallback"
            else:
                prototype, exact = legacy_prototype, legacy_exact
                residual_damping = 1.0 if exact else 0.60
                pressure_override = None
                duration_override = None
                residual_override = None
                style_source = "legacy_exact" if exact else "legacy_fallback"
            if prototype is None:
                controls = self._global_transform([tuple(point) for point in base_controls])
                pressure_curve = [self.profile.global_style.get("pressure_mean", 0.5)] * 8
                if geometry_prototype is not None:
                    confidence = geometry_prototype.confidence * 0.65
                elif layout_prototype is not None:
                    confidence = layout_prototype.confidence * 0.65
                elif relation_prototype is not None:
                    confidence = relation_prototype.confidence * 0.55
                else:
                    confidence = 0.45
                duration = None
                style_source = (
                    "component_geometry_exact"
                    if geometry_prototype is not None and geometry_exact
                    else (
                        "component_geometry_fallback"
                        if geometry_prototype is not None
                        else ("component_layout" if layout_prototype else "global")
                    )
                )
            else:
                residual = (
                    residual_override
                    if residual_override is not None
                    else np.asarray(prototype.residual, dtype=np.float64)
                )
                transformed = np.asarray(
                    self._global_transform([tuple(point) for point in base_controls]),
                    dtype=np.float64,
                )
                minimum = transformed.min(axis=0)
                span = transformed.max(axis=0) - minimum
                local_scale = max(float(span[0]), float(span[1]), 1e-6)
                local = (transformed - minimum) / local_scale
                styled = minimum + (local + residual * residual_damping) * local_scale
                controls = [(float(point[0]), float(point[1])) for point in styled]
                pressure_curve = pressure_override or prototype.pressure
                confidence = prototype.confidence * (1.0 if exact else 0.78)
                if layout_prototype is not None:
                    confidence = (confidence + layout_prototype.confidence * 0.8) / 2
                    style_source += "+layout_exact" if layout_exact else "+layout_fallback"
                duration = duration_override or prototype.duration_ms
            if geometry_prototype is not None and "component_geometry" not in style_source:
                style_source += (
                    "+component_geometry_exact"
                    if geometry_exact
                    else "+component_geometry_fallback"
                )
            if relation_prototype is not None:
                style_source += "+layout_relation"
            if trajectory_prototype is not None and component is not None:
                component_index, _ = component_stroke_slot(component, standard.stroke_id)
                controls = self._global_transform([tuple(point) for point in raw_controls])
                pressure_curve = trajectory_prototype.stroke_pressures[component_index - 1]
                duration = trajectory_prototype.stroke_durations_ms[component_index - 1]
                confidence = trajectory_prototype.confidence * (
                    1.0 if trajectory_direct or trajectory_exact else 0.82
                )
                style_source = (
                    "component_trajectory_direct"
                    if trajectory_direct
                    else (
                        "component_trajectory_exact"
                        if trajectory_exact
                        else "component_trajectory_fallback"
                    )
                )
                if layout_prototype is not None:
                    style_source += "+layout_exact" if layout_exact else "+layout_fallback"
                if relation_prototype is not None:
                    style_source += "+layout_relation"
            estimated_length = path_length(controls)
            point_count = max(24, min(128, math.ceil(estimated_length * 120)))
            trajectory = resample(
                cubic_bspline(controls, max(64, point_count * 2), clip=False), point_count
            )
            if duration is None:
                duration = max(
                    80.0,
                    estimated_length
                    * self.profile.global_style.get("milliseconds_per_unit", 700.0),
                )
            pressures = np.interp(
                np.linspace(0, 1, point_count),
                np.linspace(0, 1, len(pressure_curve)),
                pressure_curve,
            )
            points: list[GeneratedPoint] = []
            for index, ((x, y), pressure) in enumerate(zip(trajectory, pressures)):
                state = "down"
                if index == point_count - 1:
                    state = "end" if standard.order == len(graph.strokes) else "up"
                points.append(
                    GeneratedPoint(
                        x=x,
                        y=y,
                        t_ms=round(time_cursor + duration * index / max(1, point_count - 1)),
                        pressure=round(clamp01(float(pressure)), 6),
                        pen_state=state,
                    )
                )
            time_cursor = points[-1].t_ms + 60
            stroke_confidences.append(confidence)
            generated.append(
                GeneratedStroke(
                    standard_stroke_id=standard.stroke_id,
                    order=standard.order,
                    confidence=round(confidence, 6),
                    points=points,
                    style_source=style_source,
                    component_key=(
                        component_context_key(graph, component) if component is not None else None
                    ),
                )
            )
        glyph = GeneratedGlyph(
            schema_version="personal_trajectory_v1",
            character=graph.character,
            codepoint=graph.codepoint,
            locale=graph.locale,
            writer_id=self.profile.writer_id,
            structure_version=self.structure_version,
            profile_version=self.profile.profile_version,
            generator=(
                "deterministic_component_trajectory_v4"
                if self.component_conditioning
                and (
                    self.profile.component_trajectories
                    or self.profile.character_component_trajectories
                )
                else (
                    "deterministic_component_geometry_v3"
                    if self.component_conditioning
                    and self.profile.schema_version in {"style_profile_v3", "style_profile_v4"}
                    else (
                        "deterministic_component_residual_v2"
                        if self.component_conditioning and self.profile.component_strokes
                        else "deterministic_structure_residual_v1"
                    )
                )
            ),
            confidence=round(float(np.mean(stroke_confidences)), 6),
            strokes=generated,
        )
        return glyph


def _model_token(points: list[Point2D], *, order: int, count: int) -> list[float]:
    sampled = np.asarray(resample(points, 16), dtype=np.float32).reshape(-1)
    values = np.asarray(points, dtype=np.float32)
    minimum = values.min(axis=0)
    maximum = values.max(axis=0)
    extras = [
        float(minimum[0]),
        float(minimum[1]),
        float(maximum[0]),
        float(maximum[1]),
        order / max(count, 1),
        len(points) / 64.0,
        float(maximum[0] - minimum[0]),
        float(maximum[1] - minimum[1]),
    ]
    return [*[float(value) for value in sampled], *extras]


class HybridGenerator(DeterministicGenerator):
    def __init__(
        self,
        profile: StyleProfile,
        structure_version: str,
        checkpoint: Path,
        confidence_threshold: float | None = None,
        component_conditioning: bool | str = True,
        component_strength: float = 1.0,
    ):
        super().__init__(profile, structure_version, component_conditioning, component_strength)
        try:
            import torch
        except ImportError as error:
            raise RuntimeError(
                "learned generation requires the 'train' dependency group"
            ) from error
        if not torch.cuda.is_available():
            raise RuntimeError("learned generation requires a CUDA-capable NVIDIA GPU")
        from .model import HierarchicalResidualModel, ModelConfig

        payload = torch.load(checkpoint, map_location="cuda", weights_only=False)
        self.model = HierarchicalResidualModel(ModelConfig(**payload["model_config"])).cuda()
        self.model.load_state_dict(payload["model_state"])
        self.model.eval()
        self.torch = torch
        self.checkpoint = Path(checkpoint)
        self.trained_steps = int(payload.get("steps", 0))
        self.training_status = str(payload.get("training_status", "legacy_or_smoke"))
        self.has_dynamic_supervision = (
            payload.get("training_config", {}).get("dynamic_supervision") == "observed"
        )
        calibrated_threshold = payload.get("calibrated_confidence_threshold")
        self.confidence_threshold = float(
            confidence_threshold
            if confidence_threshold is not None
            else calibrated_threshold
            if calibrated_threshold is not None
            else 0.55
        )
        self.factorized_fallback = (
            self.model.config.use_factorized_style and profile.factorized_style is None
        )

    def generate(self, graph: CharacterGraph) -> GeneratedGlyph:
        if not self.profile.style_tokens:
            glyph = super().generate(graph)
            glyph.generator = "deterministic_fallback_missing_style_tokens"
            return glyph
        if self.factorized_fallback:
            glyph = super().generate(graph)
            glyph.generator = "deterministic_fallback_missing_factorized_profile"
            return glyph
        torch = self.torch
        style_values = self.profile.style_tokens[:96]
        structure_values = [
            _model_token(stroke.median, order=stroke.order, count=len(graph.strokes))
            for stroke in graph.strokes
        ]
        style = torch.tensor([style_values], dtype=torch.float32, device="cuda")
        structure = torch.tensor([structure_values], dtype=torch.float32, device="cuda")
        context = torch.tensor(
            stroke_context_tokens(graph)[None, ...], dtype=torch.float32, device="cuda"
        )
        writer_latent = (
            torch.tensor(
                [self.profile.factorized_style.writer_latent],
                dtype=torch.float32,
                device="cuda",
            )
            if self.model.config.use_factorized_style
            and self.profile.factorized_style is not None
            else None
        )
        with torch.inference_mode():
            prediction = self.model(
                style,
                structure,
                context_tokens=context,
                writer_latent=writer_latent,
            )
        confidences = prediction["confidence"][0].float().cpu().numpy()
        uncertainties = (
            np.exp(
                0.5 * prediction["residual_log_variance"][0].float().cpu().numpy()
            )
            if "residual_log_variance" in prediction
            else np.zeros_like(confidences)
        )
        if self.model.config.use_factorized_style:
            confidences = confidences * np.exp(-0.5 * uncertainties)
        mean_confidence = float(np.mean(confidences))
        if mean_confidence < self.confidence_threshold or (
            self.training_status != "formal" and self.confidence_threshold > 0
        ):
            glyph = super().generate(graph)
            glyph.generator = (
                "deterministic_fallback_untrained_checkpoint"
                if self.training_status != "formal"
                else "deterministic_fallback_low_model_confidence"
            )
            glyph.confidence = round(min(glyph.confidence, mean_confidence), 6)
            return glyph
        residuals = prediction["residual"][0].float().cpu().numpy()
        pressures = prediction["pressure"][0].float().cpu().numpy()
        durations = prediction["duration"][0].float().cpu().numpy()
        densities = prediction["density"][0].float().cpu().numpy()
        deterministic_memory = (
            super()._generate_raw(graph)
            if self.model.config.use_factorized_style or not self.has_dynamic_supervision
            else None
        )
        generated: list[GeneratedStroke] = []
        time_cursor = 0
        for index, standard in enumerate(graph.strokes):
            base = np.asarray(resample(standard.median, 8), dtype=np.float64)
            transformed = np.asarray(self._global_transform([tuple(point) for point in base]))
            minimum = transformed.min(axis=0)
            span = transformed.max(axis=0) - minimum
            local_scale = max(float(span.max()), 1e-6)
            local = (transformed - minimum) / local_scale
            controls = minimum + (local + residuals[index]) * local_scale
            if deterministic_memory is not None:
                memory_stroke = deterministic_memory.strokes[index]
                memory_controls = np.asarray(
                    resample(
                        [(round(point.x, 6), round(point.y, 6)) for point in memory_stroke.points], 8
                    ),
                    dtype=np.float64,
                )
                neural_weight = float(np.clip(np.exp(-uncertainties[index]), 0.15, 0.85))
                if memory_stroke.style_source.startswith(
                    ("component_trajectory_direct", "component_trajectory_exact")
                ):
                    neural_weight = 0.0
                controls = neural_weight * controls + (1.0 - neural_weight) * memory_controls
            controls = [(float(point[0]), float(point[1])) for point in controls]
            point_count = max(
                24,
                min(
                    128,
                    max(
                        round(float(densities[index]) * 128),
                        math.ceil(path_length(controls) * 180),
                    ),
                ),
            )
            memory_stroke = (
                deterministic_memory.strokes[index] if deterministic_memory is not None else None
            )
            duration = (
                max(80.0, memory_stroke.points[-1].t_ms - memory_stroke.points[0].t_ms)
                if memory_stroke is not None and not self.has_dynamic_supervision
                else max(80.0, float(durations[index]) * 1000.0)
            )
            trajectory = resample(
                cubic_bspline(controls, max(64, point_count * 2), clip=False), point_count
            )
            pressure_source = (
                [point.pressure for point in memory_stroke.points]
                if memory_stroke is not None and not self.has_dynamic_supervision
                else pressures[index]
            )
            pressure_curve = np.interp(
                np.linspace(0, 1, point_count),
                np.linspace(0, 1, len(pressure_source)),
                pressure_source,
            )
            points = []
            for point_index, ((x, y), pressure) in enumerate(zip(trajectory, pressure_curve)):
                state = "down"
                if point_index == point_count - 1:
                    state = "end" if index == len(graph.strokes) - 1 else "up"
                points.append(
                    GeneratedPoint(
                        x=x,
                        y=y,
                        t_ms=round(time_cursor + duration * point_index / max(1, point_count - 1)),
                        pressure=round(clamp01(float(pressure)), 6),
                        pen_state=state,
                    )
                )
            time_cursor = points[-1].t_ms + 60
            generated.append(
                GeneratedStroke(
                    standard_stroke_id=standard.stroke_id,
                    order=standard.order,
                    confidence=round(float(confidences[index]), 6),
                    points=points,
                )
            )
        glyph = GeneratedGlyph(
            schema_version="personal_trajectory_v1",
            character=graph.character,
            codepoint=graph.codepoint,
            locale=graph.locale,
            writer_id=self.profile.writer_id,
            structure_version=self.structure_version,
            profile_version=self.profile.profile_version,
            generator=(
                "hierarchical_residual_v3_factorized"
                if self.model.config.use_factorized_style
                else (
                    "hierarchical_residual_v2_refined"
                    if self.model.config.use_refiner
                    else "hierarchical_residual_v1"
                )
            ),
            confidence=round(mean_confidence, 6),
            strokes=generated,
        )
        return fit_glyph_to_canvas(glyph)


def _write_glyph(glyph: GeneratedGlyph, run_dir: Path, png: bool, source_diagnostics=None, repair_diagnostics=None) -> None:
    name = glyph.codepoint
    trajectory_path = run_dir / "trajectories" / f"{name}.json"
    trajectory_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = trajectory_path.with_suffix(".json.building")
    payload = asdict(glyph)
    if source_diagnostics is not None:
        payload["source_components"] = source_diagnostics
    if repair_diagnostics is not None:
        payload["geometry_repairs"] = repair_diagnostics
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(trajectory_path)
    render_svg(glyph, run_dir / "previews" / f"{name}.svg")
    if png:
        render_png(glyph, run_dir / "previews" / f"{name}.png")


def _source_summary(diagnostics):
    audit = diagnostics["geometry_audit"]
    return {
        **({"observed_reconstruction": diagnostics["observed_reconstruction"]} if "observed_reconstruction" in diagnostics else {}),
        "accepted_component_count": diagnostics["accepted_component_count"],
        "accepted_stroke_ids": diagnostics["accepted_stroke_ids"],
        "fallback_reason": diagnostics["fallback_reason"],
        "minimum_A_stroke_confidence": audit["min_stroke_confidence"],
        "low_A_confidence_stroke_ids": audit["low_confidence_stroke_ids"],
        "geometry_warning_count": len(audit["geometry_warnings"]),
        "geometry_warnings": audit["geometry_warnings"],
        "structure_warnings": audit["structure_warnings"],
        "donors": [{"component": r["canonical"],
                    "source_character": r["selection"]["selected"]["candidate"]["character"],
                    "source_sample_id": r["selection"]["selected"]["candidate"]["sample_id"],
                    "representation": r["representation"],
                    "minimum_source_mapping_confidence": min(r["source_mapping_confidence"].values())}
                   for r in diagnostics["components"] if r.get("selection", {}).get("selected")],
    }


def generate_run(
    writer_id: str,
    characters: list[str],
    structures: StructureRepository,
    profile_path: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    png: bool = True,
    checkpoint: Path | None = None,
    confidence_threshold: float | None = None,
    component_conditioning: bool | str = True,
    component_strength: float = 1.0,
    trajectory_mode: str = "legacy",
    source_profile_path: Path | None = None,
    source_nested_views: bool = False,
    source_observed: bool = False,
    reviewed_geometry: bool = False,
    source_characters_path: Path | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[dict, Path]:
    if trajectory_mode not in {"legacy", "source-raw", "source-simplified"}:
        raise ValueError("unknown trajectory mode")
    if trajectory_mode == "legacy" and (source_profile_path or source_nested_views or source_characters_path or source_observed):
        raise ValueError("source options require an explicit source trajectory mode")
    if trajectory_mode != "legacy" and checkpoint is not None:
        raise ValueError("source trajectory mode does not support neural checkpoints")
    if trajectory_mode != "legacy" and source_profile_path is None:
        raise ValueError("source trajectory mode requires --source-profile")
    profile = load_profile(profile_path)
    if profile.writer_id != writer_id:
        raise ValueError("profile writer does not match requested writer")
    metadata = structures.metadata()
    structure_version = metadata.get("source_version", "unknown")
    generator = (
        HybridGenerator(
            profile,
            structure_version,
            checkpoint,
            confidence_threshold,
            component_conditioning,
            component_strength,
        )
        if checkpoint is not None
        else DeterministicGenerator(
            profile, structure_version, component_conditioning, component_strength
        )
    )
    source_generator = None
    source_identity = None
    if trajectory_mode != "legacy":
        from .exemplar_generation import (
            SIMPLIFICATION_EPSILON,
            SOURCE_POLICY,
            SourceComponentGenerator,
        )

        source_profile = load_profile(source_profile_path)
        allowed = ({c for c in Path(source_characters_path).read_text(encoding="utf-8")
                    if not c.isspace()} if source_characters_path is not None else None)
        source_class = SourceComponentGenerator
        if source_observed:
            from .observed_reconstruction import ObservedSourceGenerator
            source_class = ObservedSourceGenerator
        source_generator = source_class(generator, source_profile, structures,
            mode=trajectory_mode, nested_views=source_nested_views, allowed_characters=allowed)
        source_identity = {
            "policy": SOURCE_POLICY, "mode": trajectory_mode,
            "source_profile_sha256": sha256_file(Path(source_profile_path)),
            "source_characters_sha256": sha256_file(Path(source_characters_path)) if source_characters_path else None,
            "nested_views": source_nested_views,
            "epsilon": SIMPLIFICATION_EPSILON if trajectory_mode == "source-simplified" else None,
            "implementation_sha256": {name: sha256_file(Path(__file__).with_name(name + ".py"))
                for name in ("exemplar_generation", "exemplar_index", "component_views", "fast_placement",
                             "contextual_trajectory", "trajectory_experiment", "generate", "geometry_audit")},
        }
        if source_observed:
            source_identity["observed_reconstruction"] = True
            source_identity["implementation_sha256"]["observed_reconstruction"] = sha256_file(Path(__file__).with_name("observed_reconstruction.py"))
    repair_processor = None
    if reviewed_geometry:
        if checkpoint is not None or generator.component_mode != "adaptive" or generator.component_strength != 1.:
            raise ValueError("reviewed geometry requires deterministic adaptive generation at strength 1")
        from .reviewed_geometry import ReviewedGeometryProcessor
        root = Path(__file__).resolve().parents[2]
        repair_processor = ReviewedGeometryProcessor(generator, structures,
            root / "configs/geometry_repairs/reviewed_v1.json",
            root / "third_party/makemeahanzi/graphics.txt",
            root / "third_party/makemeahanzi/dictionary.txt")
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = Path(output_root).resolve() / writer_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    unique_characters = list(dict.fromkeys(characters))
    started_at = datetime.now(UTC).isoformat()
    previous_elapsed = 0.0
    run_identity = {
        "boundary_policy": BOUNDARY_POLICY,
        "writer_id": writer_id,
        "profile_sha256": sha256_file(Path(profile_path)),
        "structure_sha256": sha256_file(structures.path),
        "checkpoint_sha256": sha256_file(checkpoint) if checkpoint else None,
        "component_mode": generator.component_mode,
        "component_strength": generator.component_strength,
        "confidence_threshold": (
            generator.confidence_threshold if isinstance(generator, HybridGenerator) else None
        ),
        "png": png,
    }
    if source_identity is not None:
        run_identity["source_components"] = source_identity
    if repair_processor is not None:
        run_identity["geometry_repairs"] = repair_processor.identity
    if manifest_path.is_file():
        try:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if previous_manifest.get("run_identity") != run_identity:
                raise ValueError("run identity changed or predates canvas fix; use a new run-id")
            started_at = previous_manifest.get("started_at", started_at)
            previous_elapsed = float(previous_manifest.get("elapsed_seconds", 0.0))
        except (OSError, TypeError, AttributeError, ValueError) as error:
            raise ValueError(f"cannot safely resume {run_dir}: {error}") from error
    elif any((run_dir / "trajectories").glob("*.json")):
        raise ValueError("existing trajectories have no manifest; use a new run-id")
    started_clock = time.perf_counter()
    completed: list[str] = []
    failed: list[dict[str, str]] = []
    source_results: dict[str, dict] = {}
    repair_results: dict[str, dict] = {}

    def write_manifest(status: str) -> dict:
        manifest = {
            "run_identity": run_identity,
            "schema_version": "generation_manifest_v1",
            "run_id": run_id,
            "writer_id": writer_id,
            "status": status,
            "started_at": started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(previous_elapsed + time.perf_counter() - started_clock, 3),
            "requested_count": len(unique_characters),
            "completed_count": len(completed),
            "failed_count": len(failed),
            "completed_characters": "".join(completed),
            "failed": failed,
            "profile_path": str(Path(profile_path).resolve()),
            "profile_version": profile.profile_version,
            "structure_database": str(structures.path.resolve()),
            "generator": type(source_generator or generator).__name__,
            "component_mode": generator.component_mode,
            "component_strength": generator.component_strength,
            "checkpoint": str(Path(checkpoint).resolve()) if checkpoint else None,
            "confidence_threshold": (
                generator.confidence_threshold
                if isinstance(generator, HybridGenerator)
                else None
            ),
        }
        if source_identity is not None:
            manifest["source_components"] = {
                "source_profile_path": str(Path(source_profile_path).resolve()),
                "mode": trajectory_mode,
                "characters_with_source_components": sum(v["accepted_component_count"] > 0 for v in source_results.values()),
                "by_character": source_results,
                "confidence_semantics": "A scores inherited; source mapping evidence is reported separately, uncalibrated",
            }
        if repair_processor is not None:
            manifest["geometry_repairs"] = {"changed_characters": [c for c, r in repair_results.items() if r["applied"]],
                                            "by_character": repair_results}
        temporary_manifest = manifest_path.with_suffix(".json.building")
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary_manifest.replace(manifest_path)
        return manifest

    manifest = write_manifest("running")
    for character in unique_characters:
        if cancelled is not None and cancelled():
            manifest = write_manifest("cancelled")
            break
        trajectory_path = run_dir / "trajectories" / f"U+{ord(character):04X}.json"
        if trajectory_path.is_file():
            # Do not let an old/corrupt file copied into a new run bypass the fix.
            try:
                cached = json.loads(trajectory_path.read_text(encoding="utf-8"))
                if (
                    cached["character"] != character
                    or cached["writer_id"] != writer_id
                    or cached["profile_version"] != profile.profile_version
                    or cached.get("canvas_fit", {}).get("policy") != BOUNDARY_POLICY
                ):
                    raise ValueError("cached trajectory identity differs")
            except (OSError, KeyError, TypeError, AttributeError, ValueError) as error:
                raise ValueError(f"cannot safely reuse {trajectory_path}; use a new run-id") from error
            if source_identity is not None:
                if cached.get("source_components", {}).get("run_identity") != source_identity:
                    raise ValueError("cached source trajectory identity differs; use a new run-id")
                source_results[character] = _source_summary(cached["source_components"])
            if repair_processor is not None:
                if cached.get("geometry_repairs", {}).get("run_identity") != repair_processor.identity:
                    raise ValueError("cached reviewed geometry identity differs; use a new run-id")
                repair_results[character] = cached["geometry_repairs"]
            completed.append(character)
        else:
            try:
                graph = structures.get(character)
                source_diagnostics = None
                if source_generator is None:
                    glyph = generator.generate(graph)
                else:
                    glyph, source_diagnostics = source_generator.generate(graph)
                    source_diagnostics["run_identity"] = source_identity
                repair_diagnostics = None
                if repair_processor is not None:
                    glyph, repair_diagnostics = repair_processor.apply(glyph, graph)
                    repair_diagnostics["run_identity"] = repair_processor.identity
                    if source_diagnostics is not None and repair_diagnostics["geometry_audit"] is not None:
                        source_diagnostics["geometry_audit"] = repair_diagnostics["geometry_audit"]
                if len(glyph.strokes) != len(graph.strokes):
                    raise RuntimeError("generator violated stroke-count invariant")
                if [stroke.order for stroke in glyph.strokes] != list(
                    range(1, len(graph.strokes) + 1)
                ):
                    raise RuntimeError("generator violated stroke-order invariant")
                if repair_diagnostics is None:
                    _write_glyph(glyph, run_dir, png, source_diagnostics)
                else:
                    _write_glyph(glyph, run_dir, png, source_diagnostics, repair_diagnostics)
                    repair_results[character] = repair_diagnostics
                if source_diagnostics is not None:
                    source_results[character] = _source_summary(source_diagnostics)
                completed.append(character)
            except (KeyError, OSError, RuntimeError, ValueError) as error:
                failed.append({"character": character, "reason": str(error)})
        manifest = write_manifest("running")
        if progress_callback is not None:
            progress_callback(
                {
                    "requested_count": len(unique_characters),
                    "completed_count": len(completed),
                    "failed_count": len(failed),
                    "character": character,
                }
            )
    else:
        manifest = write_manifest("completed")
    return manifest, run_dir
