from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import numpy as np

from .alignment import align_sample
from .component_style import (
    component_context_key,
    component_for_stroke,
    component_relation_key,
    component_stroke_key,
    component_stroke_slot,
    component_trajectory_key,
    parent_layout,
    relative_bbox,
)
from .factorized import observed_structure_keys
from .geometry import bbox, resample, signature_key
from .samples import iter_index, sha256_file
from .schemas import (
    ComponentLayoutPrototype,
    ComponentRelationPrototype,
    ComponentStrokePrototype,
    ComponentTrajectoryPrototype,
    FactorizedStyleProfile,
    Point2D,
    SourceTrajectorySample,
    SourceTrajectoryStroke,
    StrokePrototype,
    StyleProfile,
)
from .source_trajectory import MIN_MAPPING_CONFIDENCE, TRAJECTORY_SCHEMA, source_trajectory
from .structures import StructureRepository

DEFAULT_PROFILE_ROOT = Path("profiles")
PROFILE_BUILDER_VERSION = "component_trajectory_v4_source_v1"


def _mean(values: list[float], default: float) -> float:
    return float(np.mean(values)) if values else default


def _factorized_style_from_checkpoint(
    checkpoint: Path | None,
    style_tokens: list[list[float]],
    characters: set[str],
    structures: StructureRepository,
) -> FactorizedStyleProfile | None:
    if checkpoint is None or not style_tokens:
        return None
    try:
        import torch

        from .model import HierarchicalResidualModel, ModelConfig

        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        config = ModelConfig(**payload["model_config"])
        if not config.use_factorized_style:
            return None
        model = HierarchicalResidualModel(config)
        model.load_state_dict(payload["model_state"])
        model.eval()
        values = torch.tensor([style_tokens[:256]], dtype=torch.float32)
        with torch.inference_mode():
            _, mean, log_variance = model.encode_writer(values)
    except (ImportError, KeyError, RuntimeError, ValueError):
        return None
    observed = set()
    for character in characters:
        observed.update(observed_structure_keys(structures.get(character)))
    log_variance_values = log_variance[0].float().tolist()
    standard_deviation = np.exp(0.5 * np.asarray(log_variance_values, dtype=np.float64))
    return FactorizedStyleProfile(
        model_version=str(payload.get("model_version", "hierarchical_residual_v2")),
        checkpoint_sha256=sha256_file(Path(checkpoint)),
        writer_latent=[float(value) for value in mean[0].float().tolist()],
        writer_log_variance=[float(value) for value in log_variance_values],
        observed_structure_keys=sorted(observed),
        uncertainty_summary={
            "latent_std_mean": float(standard_deviation.mean()),
            "latent_std_max": float(standard_deviation.max()),
            "observed_key_count": float(len(observed)),
        },
    )


def _glyph_bbox(strokes: list[list[Point2D]]) -> tuple[float, float, float, float]:
    points = [point for stroke in strokes for point in stroke]
    return bbox(points)


def _local_stroke(points: np.ndarray) -> np.ndarray:
    minimum = points.min(axis=0)
    span = points.max(axis=0) - minimum
    scale = max(float(span[0]), float(span[1]), 1e-6)
    return (points - minimum) / scale


def _point_relative(point: Point2D, parent: tuple[float, float, float, float]) -> np.ndarray:
    width = max(parent[2] - parent[0], 1e-6)
    height = max(parent[3] - parent[1], 1e-6)
    return np.asarray(((point[0] - parent[0]) / width, (point[1] - parent[1]) / height))


def _build_component_trajectory_prototypes(
    values_by_key: dict[str, list[dict[str, object]]],
) -> dict[str, ComponentTrajectoryPrototype]:
    prototypes: dict[str, ComponentTrajectoryPrototype] = {}
    for key, values in values_by_key.items():
        first = values[0]
        stroke_count = int(first["stroke_count"])
        compatible = [value for value in values if int(value["stroke_count"]) == stroke_count]
        weights = np.asarray([float(value["confidence"]) for value in compatible], dtype=np.float64)
        weights /= max(float(weights.sum()), 1e-9)
        controls = np.average(
            np.stack([np.asarray(value["controls"]) for value in compatible]),
            axis=0,
            weights=weights,
        )
        controls = np.clip(controls, -0.15, 1.15)
        pressures = np.average(
            np.stack([np.asarray(value["pressures"]) for value in compatible]),
            axis=0,
            weights=weights,
        )
        durations = np.average(
            np.stack([np.asarray(value["durations"]) for value in compatible]),
            axis=0,
            weights=weights,
        )
        prototypes[key] = ComponentTrajectoryPrototype(
            key=key,
            canonical=str(first["canonical"]),
            glyph_variant=str(first["glyph_variant"]),
            role=str(first["role"]),
            parent_layout=str(first["parent_layout"]),
            stroke_count=stroke_count,
            stroke_controls=[
                [(float(point[0]), float(point[1])) for point in stroke] for stroke in controls
            ],
            stroke_pressures=[[float(value) for value in stroke] for stroke in pressures],
            stroke_durations_ms=[float(value) for value in durations],
            confidence=float(np.mean([float(value["confidence"]) for value in compatible])),
            sample_count=len(compatible),
            source_character_count=len({str(value["character"]) for value in compatible}),
        )
    return prototypes


def build_profile(
    writer_id: str,
    index_path: Path,
    structures: StructureRepository,
    profile_root: Path = DEFAULT_PROFILE_ROOT,
    style_checkpoint: Path | None = None,
    *,
    retain_source_trajectories: bool = False,
) -> tuple[StyleProfile, Path]:
    x_scales: list[float] = []
    y_scales: list[float] = []
    x_offsets: list[float] = []
    y_offsets: list[float] = []
    slants: list[float] = []
    pressures: list[float] = []
    milliseconds_per_unit: list[float] = []
    prototype_values: dict[str, list[tuple[np.ndarray, np.ndarray, float, float]]] = {}
    component_layout_values: dict[str, list[dict[str, object]]] = {}
    character_layout_values: dict[str, list[dict[str, object]]] = {}
    component_stroke_values: dict[str, list[dict[str, object]]] = {}
    component_relation_values: dict[str, list[dict[str, object]]] = {}
    component_trajectory_values: dict[str, list[dict[str, object]]] = {}
    character_component_trajectory_values: dict[str, list[dict[str, object]]] = {}
    style_tokens: list[list[float]] = []
    excluded: list[dict[str, str]] = []
    characters: set[str] = set()
    signature_hits: dict[str, int] = {}
    sample_count = 0
    corrected_order_samples: list[str] = []
    ambiguous_order_samples: list[str] = []
    source_trajectories: dict[str, SourceTrajectorySample] = {}
    source_exclusions: list[dict[str, str]] = []
    for sample in iter_index(index_path):
        if sample.writer_id != writer_id:
            excluded.append({"sample_id": sample.sample_id, "reason": "writer mismatch"})
            continue
        try:
            graph = structures.get(sample.character)
            aligned = align_sample(sample, graph)
        except (KeyError, ValueError) as error:
            excluded.append({"sample_id": sample.sample_id, "reason": str(error)})
            continue
        if aligned.stroke_order_status == "ambiguous":
            ambiguous_order_samples.append(sample.sample_id)
            excluded.append(
                {
                    "sample_id": sample.sample_id,
                    "reason": "ambiguous stroke order; excluded from style profile",
                }
            )
            continue
        if aligned.stroke_order_status == "corrected":
            corrected_order_samples.append(sample.sample_id)
        if retain_source_trajectories:
            trajectory, reason = source_trajectory(sample, aligned, graph)
            if trajectory is not None:
                if sample.sample_id in source_trajectories:
                    raise ValueError(f"duplicate source sample_id: {sample.sample_id}")
                source_trajectories[sample.sample_id] = trajectory
            else:
                source_exclusions.append({"sample_id": sample.sample_id, "reason": str(reason)})
        sample_count += 1
        characters.add(sample.character)
        user_glyph_bbox = _glyph_bbox(aligned.normalized_strokes)
        standard_glyph_bbox = _glyph_bbox([stroke.median for stroke in graph.strokes])
        user_width = user_glyph_bbox[2] - user_glyph_bbox[0]
        user_height = user_glyph_bbox[3] - user_glyph_bbox[1]
        standard_width = max(standard_glyph_bbox[2] - standard_glyph_bbox[0], 1e-6)
        standard_height = max(standard_glyph_bbox[3] - standard_glyph_bbox[1], 1e-6)
        x_scales.append(user_width / standard_width)
        y_scales.append(user_height / standard_height)
        x_offsets.append(
            (
                user_glyph_bbox[0]
                + user_glyph_bbox[2]
                - standard_glyph_bbox[0]
                - standard_glyph_bbox[2]
            )
            / 2
        )
        y_offsets.append(
            (
                user_glyph_bbox[1]
                + user_glyph_bbox[3]
                - standard_glyph_bbox[1]
                - standard_glyph_bbox[3]
            )
            / 2
        )
        all_user_points = np.asarray(
            [point for stroke in aligned.normalized_strokes for point in stroke], dtype=np.float64
        )
        if len(all_user_points) >= 2 and float(np.var(all_user_points[:, 1])) > 1e-8:
            covariance = float(np.cov(all_user_points[:, 0], all_user_points[:, 1])[0, 1])
            slants.append(covariance / float(np.var(all_user_points[:, 1])))
        for stroke in sample.strokes:
            pressures.extend(point.pressure for point in stroke.points)
            duration = stroke.points[-1].t_ms - stroke.points[0].t_ms
            if duration > 0:
                normalized = [
                    (point.x / sample.canvas_width, point.y / sample.canvas_height)
                    for point in stroke.points
                ]
                length = sum(math.dist(a, b) for a, b in pairwise(normalized))
                if length > 1e-6:
                    milliseconds_per_unit.append(duration / length)
        mappings_by_standard = {
            mapping.standard_orders[0] - 1: mapping
            for mapping in aligned.mappings
            if mapping.mapping_type == "one_to_one" and mapping.confidence >= 0.30
        }
        stroke_index_by_id = {stroke.stroke_id: index for index, stroke in enumerate(graph.strokes)}
        component_user_bboxes: dict[str, tuple[float, float, float, float]] = {}
        component_mapping_confidences: dict[str, float] = {}
        for component in graph.components:
            standard_indices = [
                stroke_index_by_id[stroke_id]
                for stroke_id in component.stroke_ids
                if stroke_id in stroke_index_by_id
            ]
            if not standard_indices or any(
                index not in mappings_by_standard for index in standard_indices
            ):
                continue
            user_indices = [
                mappings_by_standard[index].user_orders[0] - 1 for index in standard_indices
            ]
            component_user_bbox = _glyph_bbox(
                [aligned.normalized_strokes[index] for index in user_indices]
            )
            component_user_bboxes[component.component_id] = component_user_bbox
            component_mapping_confidences[component.component_id] = float(
                np.mean([mappings_by_standard[index].confidence for index in standard_indices])
                * component.confidence
            )
            if component.path == "root" and len(graph.components) > 1:
                continue
            standard_relative = np.asarray(
                relative_bbox(component.bbox, standard_glyph_bbox), dtype=np.float64
            )
            user_relative = np.asarray(
                relative_bbox(component_user_bbox, user_glyph_bbox), dtype=np.float64
            )
            delta = np.clip(user_relative - standard_relative, -0.20, 0.20)
            layout_confidence = component_mapping_confidences[component.component_id]
            context_key = component_context_key(graph, component)
            layout_value = {
                "delta": delta,
                "confidence": layout_confidence,
                "character": sample.character,
                "canonical": component.canonical,
                "glyph_variant": component.glyph_variant,
                "role": component.role,
                "parent_layout": parent_layout(graph, component),
            }
            component_layout_values.setdefault(context_key, []).append(layout_value)
            character_layout_values.setdefault(f"{sample.character}::{context_key}", []).append(
                layout_value
            )
            if not component.children_ids and len(standard_indices) >= 2:
                controls: list[np.ndarray] = []
                component_pressures: list[np.ndarray] = []
                component_durations: list[float] = []
                for user_index in user_indices:
                    user_controls = np.asarray(
                        resample(aligned.normalized_strokes[user_index], 8),
                        dtype=np.float64,
                    )
                    controls.append(
                        np.stack(
                            [
                                _point_relative(tuple(point), component_user_bbox)
                                for point in user_controls
                            ]
                        )
                    )
                    raw_pressures = aligned.pressure_strokes[user_index]
                    component_pressures.append(
                        np.interp(
                            np.linspace(0, 1, 8),
                            np.linspace(0, 1, len(raw_pressures)),
                            raw_pressures,
                        )
                    )
                    times = aligned.time_strokes[user_index]
                    component_durations.append(float(max(1, times[-1] - times[0])))
                trajectory_key = component_trajectory_key(graph, component)
                trajectory_value = {
                    "controls": np.stack(controls),
                    "pressures": np.stack(component_pressures),
                    "durations": np.asarray(component_durations),
                    "confidence": layout_confidence,
                    "character": sample.character,
                    "canonical": component.canonical,
                    "glyph_variant": component.glyph_variant,
                    "role": component.role,
                    "parent_layout": parent_layout(graph, component),
                    "stroke_count": len(standard_indices),
                }
                component_trajectory_values.setdefault(trajectory_key, []).append(trajectory_value)
                character_component_trajectory_values.setdefault(
                    f"{sample.character}::{trajectory_key}", []
                ).append(trajectory_value)
        component_by_id = {component.component_id: component for component in graph.components}
        for parent in graph.components:
            if not parent.layout or len(parent.children_ids) < 2:
                continue
            children = [
                component_by_id[child_id]
                for child_id in parent.children_ids
                if child_id in component_by_id
            ]
            if len(children) < 2 or any(
                child.component_id not in component_user_bboxes for child in children
            ):
                continue
            if parent.component_id not in component_user_bboxes:
                continue
            relation_key = component_relation_key(graph, children[0])
            if relation_key is None:
                continue
            parent_user_bbox = component_user_bboxes[parent.component_id]
            deltas: dict[str, np.ndarray] = {}
            for child in children:
                standard_relative = np.asarray(
                    relative_bbox(child.bbox, parent.bbox), dtype=np.float64
                )
                user_relative = np.asarray(
                    relative_bbox(component_user_bboxes[child.component_id], parent_user_bbox),
                    dtype=np.float64,
                )
                deltas[child.role] = np.clip(user_relative - standard_relative, -0.20, 0.20)
            relation_confidence = float(
                np.mean([component_mapping_confidences[child.component_id] for child in children])
            )
            component_relation_values.setdefault(relation_key, []).append(
                {
                    "deltas": deltas,
                    "roles": sorted(deltas),
                    "confidence": relation_confidence,
                    "character": sample.character,
                    "parent_layout": parent.layout,
                }
            )
        for mapping in aligned.mappings:
            if mapping.mapping_type != "one_to_one" or mapping.confidence < 0.30:
                continue
            standard_index = mapping.standard_orders[0] - 1
            user_index = mapping.user_orders[0] - 1
            standard = np.asarray(resample(graph.strokes[standard_index].median, 8))
            user = np.asarray(resample(aligned.normalized_strokes[user_index], 8))
            # Store only local shape deformation. Absolute position, glyph
            # scale and slant are modelled separately by global_style.
            residual = _local_stroke(user) - _local_stroke(standard)
            raw_pressures = aligned.pressure_strokes[user_index]
            pressure_curve = np.interp(
                np.linspace(0, 1, 8),
                np.linspace(0, 1, len(raw_pressures)),
                raw_pressures,
            )
            times = aligned.time_strokes[user_index]
            duration = float(max(1, times[-1] - times[0]))
            standard_stroke = graph.strokes[standard_index]
            user_stroke_bbox = bbox(aligned.normalized_strokes[user_index])
            user_token = np.asarray(resample(aligned.normalized_strokes[user_index], 16)).reshape(
                -1
            )
            style_tokens.append(
                [
                    *[float(value) for value in user_token],
                    *[float(value) for value in user_stroke_bbox],
                    (user_index + 1) / max(len(aligned.normalized_strokes), 1),
                    len(sample.strokes[user_index].points) / 64.0,
                    user_stroke_bbox[2] - user_stroke_bbox[0],
                    user_stroke_bbox[3] - user_stroke_bbox[1],
                ]
            )
            signature = signature_key(standard_stroke.signature)
            key = f"{signature}@{standard_stroke.component_path}"
            prototype_values.setdefault(key, []).append(
                (residual, pressure_curve, duration, mapping.confidence)
            )
            component = component_for_stroke(graph, standard_stroke)
            if component is not None:
                component_key = component_stroke_key(
                    graph, component, standard_stroke.stroke_id, signature
                )
                component_index, component_count = component_stroke_slot(
                    component, standard_stroke.stroke_id
                )
                component_user_bbox = component_user_bboxes.get(component.component_id)
                if component_user_bbox is not None:
                    standard_bbox_relative = np.asarray(
                        relative_bbox(standard_stroke.bbox, component.bbox), dtype=np.float64
                    )
                    user_bbox_relative = np.asarray(
                        relative_bbox(user_stroke_bbox, component_user_bbox), dtype=np.float64
                    )
                    stroke_bbox_delta = np.clip(
                        user_bbox_relative - standard_bbox_relative, -0.35, 0.35
                    )
                    start_delta = np.clip(
                        _point_relative(tuple(user[0]), component_user_bbox)
                        - _point_relative(tuple(standard[0]), component.bbox),
                        -0.25,
                        0.25,
                    )
                    end_delta = np.clip(
                        _point_relative(tuple(user[-1]), component_user_bbox)
                        - _point_relative(tuple(standard[-1]), component.bbox),
                        -0.25,
                        0.25,
                    )
                else:
                    stroke_bbox_delta = np.zeros(4, dtype=np.float64)
                    start_delta = np.zeros(2, dtype=np.float64)
                    end_delta = np.zeros(2, dtype=np.float64)
                component_stroke_values.setdefault(component_key, []).append(
                    {
                        "residual": residual,
                        "pressure": pressure_curve,
                        "duration": duration,
                        "confidence": mapping.confidence * component.confidence,
                        "character": sample.character,
                        "canonical": component.canonical,
                        "glyph_variant": component.glyph_variant,
                        "role": component.role,
                        "parent_layout": parent_layout(graph, component),
                        "component_stroke_index": component_index,
                        "component_stroke_count": component_count,
                        "signature": signature,
                        "stroke_bbox_delta": stroke_bbox_delta,
                        "start_delta": start_delta,
                        "end_delta": end_delta,
                    }
                )
            signature_hits[signature] = signature_hits.get(signature, 0) + 1
    if sample_count == 0:
        raise ValueError("no samples could be aligned to the structure database")
    prototypes: dict[str, StrokePrototype] = {}
    for key, values in prototype_values.items():
        weights = np.asarray([value[3] for value in values], dtype=np.float64)
        weights /= max(float(weights.sum()), 1e-9)
        residual = np.average(np.stack([value[0] for value in values]), axis=0, weights=weights)
        pressure = np.average(np.stack([value[1] for value in values]), axis=0, weights=weights)
        duration = float(np.average([value[2] for value in values], weights=weights))
        signature, component_path = key.split("@", 1)
        prototypes[key] = StrokePrototype(
            key=key,
            signature=signature,
            component_path=component_path,
            residual=[(float(point[0]), float(point[1])) for point in residual],
            pressure=[float(value) for value in pressure],
            duration_ms=duration,
            confidence=float(np.mean([value[3] for value in values])),
            sample_count=len(values),
        )
    component_layouts: dict[str, ComponentLayoutPrototype] = {}
    for key, values in component_layout_values.items():
        weights = np.asarray([float(value["confidence"]) for value in values])
        weights /= max(float(weights.sum()), 1e-9)
        delta = np.average(
            np.stack([np.asarray(value["delta"]) for value in values]), axis=0, weights=weights
        )
        first = values[0]
        component_layouts[key] = ComponentLayoutPrototype(
            key=key,
            canonical=str(first["canonical"]),
            glyph_variant=str(first["glyph_variant"]),
            role=str(first["role"]),
            parent_layout=str(first["parent_layout"]),
            bbox_delta=tuple(float(value) for value in delta),
            confidence=float(np.mean([float(value["confidence"]) for value in values])),
            sample_count=len(values),
            source_character_count=len({str(value["character"]) for value in values}),
        )
    character_layouts: dict[str, ComponentLayoutPrototype] = {}
    for key, values in character_layout_values.items():
        weights = np.asarray([float(value["confidence"]) for value in values])
        weights /= max(float(weights.sum()), 1e-9)
        delta = np.average(
            np.stack([np.asarray(value["delta"]) for value in values]), axis=0, weights=weights
        )
        first = values[0]
        character_layouts[key] = ComponentLayoutPrototype(
            key=key,
            canonical=str(first["canonical"]),
            glyph_variant=str(first["glyph_variant"]),
            role=str(first["role"]),
            parent_layout=str(first["parent_layout"]),
            bbox_delta=tuple(float(value) for value in delta),
            confidence=float(np.mean([float(value["confidence"]) for value in values])),
            sample_count=len(values),
            source_character_count=1,
        )
    component_relations: dict[str, ComponentRelationPrototype] = {}
    for key, values in component_relation_values.items():
        roles = list(values[0]["roles"])
        compatible = [value for value in values if list(value["roles"]) == roles]
        weights = np.asarray([float(value["confidence"]) for value in compatible])
        weights /= max(float(weights.sum()), 1e-9)
        bbox_deltas = {}
        for role in roles:
            delta = np.average(
                np.stack([np.asarray(value["deltas"][role]) for value in compatible]),
                axis=0,
                weights=weights,
            )
            bbox_deltas[role] = tuple(float(item) for item in delta)
        component_relations[key] = ComponentRelationPrototype(
            key=key,
            parent_layout=str(compatible[0]["parent_layout"]),
            roles=roles,
            bbox_deltas=bbox_deltas,
            confidence=float(np.mean([float(value["confidence"]) for value in compatible])),
            sample_count=len(compatible),
            source_character_count=len({str(value["character"]) for value in compatible}),
        )
    component_strokes: dict[str, ComponentStrokePrototype] = {}
    for key, values in component_stroke_values.items():
        weights = np.asarray([float(value["confidence"]) for value in values])
        weights /= max(float(weights.sum()), 1e-9)
        residual = np.average(
            np.stack([np.asarray(value["residual"]) for value in values]), axis=0, weights=weights
        )
        residual = np.clip(residual, -0.20, 0.20)
        pressure = np.average(
            np.stack([np.asarray(value["pressure"]) for value in values]), axis=0, weights=weights
        )
        duration = float(
            np.average([float(value["duration"]) for value in values], weights=weights)
        )
        stroke_bbox_delta = np.average(
            np.stack([np.asarray(value["stroke_bbox_delta"]) for value in values]),
            axis=0,
            weights=weights,
        )
        start_delta = np.average(
            np.stack([np.asarray(value["start_delta"]) for value in values]),
            axis=0,
            weights=weights,
        )
        end_delta = np.average(
            np.stack([np.asarray(value["end_delta"]) for value in values]),
            axis=0,
            weights=weights,
        )
        first = values[0]
        component_strokes[key] = ComponentStrokePrototype(
            key=key,
            canonical=str(first["canonical"]),
            glyph_variant=str(first["glyph_variant"]),
            role=str(first["role"]),
            parent_layout=str(first["parent_layout"]),
            component_stroke_index=int(first["component_stroke_index"]),
            component_stroke_count=int(first["component_stroke_count"]),
            signature=str(first["signature"]),
            residual=[(float(point[0]), float(point[1])) for point in residual],
            pressure=[float(value) for value in pressure],
            duration_ms=duration,
            confidence=float(np.mean([float(value["confidence"]) for value in values])),
            sample_count=len(values),
            source_character_count=len({str(value["character"]) for value in values}),
            stroke_bbox_delta=tuple(float(value) for value in stroke_bbox_delta),
            start_delta=tuple(float(value) for value in start_delta),
            end_delta=tuple(float(value) for value in end_delta),
        )
    component_trajectories = _build_component_trajectory_prototypes(component_trajectory_values)
    character_component_trajectories = _build_component_trajectory_prototypes(
        character_component_trajectory_values
    )
    index_sha256 = sha256_file(Path(index_path))
    factorized_style = _factorized_style_from_checkpoint(
        style_checkpoint, style_tokens, characters, structures
    )
    profile_schema = "style_profile_v5" if factorized_style is not None else "style_profile_v4"
    checkpoint_identity = (
        factorized_style.checkpoint_sha256 if factorized_style is not None else "deterministic"
    )
    build_identity = {
        "builder_version": PROFILE_BUILDER_VERSION,
        "writer_id": writer_id,
        "index_sha256": index_sha256,
        "structure_sha256": structures.content_sha256(),
        "profile_schema": profile_schema,
        "checkpoint_sha256": checkpoint_identity,
        "trajectory_schema": TRAJECTORY_SCHEMA if retain_source_trajectories else None,
        "parameters": {
            "normalization_extent": 0.85,
            "alignment_points": 16,
            "control_points": 8,
            "source_min_mapping_confidence": MIN_MAPPING_CONFIDENCE,
        },
    }
    profile_seed = json.dumps(build_identity, sort_keys=True, separators=(",", ":")).encode()
    profile_version = hashlib.sha256(profile_seed).hexdigest()[:16]
    profile = StyleProfile(
        schema_version=profile_schema,
        profile_version=profile_version,
        writer_id=writer_id,
        created_at=datetime.now(UTC).isoformat(),
        source_index_sha256=index_sha256,
        sample_count=sample_count,
        character_count=len(characters),
        global_style={
            "scale_x": _mean(x_scales, 1.0),
            "scale_y": _mean(y_scales, 1.0),
            "offset_x": _mean(x_offsets, 0.0),
            "offset_y": _mean(y_offsets, 0.0),
            "slant": max(-0.35, min(0.35, _mean(slants, 0.0))),
            "pressure_mean": _mean(pressures, 0.5),
            "milliseconds_per_unit": _mean(milliseconds_per_unit, 700.0),
        },
        prototypes=prototypes,
        component_layouts=component_layouts,
        character_layouts=character_layouts,
        component_strokes=component_strokes,
        component_relations=component_relations,
        component_trajectories=component_trajectories,
        character_component_trajectories=character_component_trajectories,
        coverage={
            "signature_hits": signature_hits,
            "prototype_count": len(prototypes),
            "aligned_character_count": len(characters),
            "corrected_stroke_order_sample_count": len(corrected_order_samples),
            "corrected_stroke_order_sample_ids": corrected_order_samples,
            "ambiguous_stroke_order_sample_count": len(ambiguous_order_samples),
            "residual_space": "component_bbox_plus_stroke_local_unit_extent",
            "component_layout_prototype_count": len(component_layouts),
            "character_layout_prototype_count": len(character_layouts),
            "component_stroke_prototype_count": len(component_strokes),
            "component_relation_prototype_count": len(component_relations),
            "component_trajectory_prototype_count": len(component_trajectories),
            "character_component_trajectory_prototype_count": len(character_component_trajectories),
            "component_identities": sorted(
                {prototype.canonical for prototype in component_layouts.values()}
            ),
            "component_layout_source_characters": sum(
                prototype.source_character_count for prototype in component_layouts.values()
            ),
        },
        excluded_samples=excluded,
        style_tokens=style_tokens[:256],
        factorized_style=factorized_style,
        trajectory_schema=TRAJECTORY_SCHEMA if retain_source_trajectories else None,
        source_trajectories=source_trajectories,
        build_identity=build_identity,
    )
    if retain_source_trajectories:
        profile.coverage["source_trajectory_sample_count"] = len(source_trajectories)
        profile.coverage["source_trajectory_exclusions"] = source_exclusions
    target_dir = Path(profile_root).resolve() / writer_id
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(profile), ensure_ascii=False, indent=2) + "\n"
    versioned = target_dir / f"{profile.profile_version}.json"
    if not versioned.exists():
        temporary = versioned.with_suffix(".json.building")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(versioned)
    current = target_dir / "profile.json"
    temporary_current = current.with_suffix(".json.building")
    temporary_current.write_text(payload, encoding="utf-8")
    temporary_current.replace(current)
    return profile, versioned


def load_profile(path: Path) -> StyleProfile:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("trajectory_schema") not in (None, TRAJECTORY_SCHEMA):
        raise ValueError(f"unsupported trajectory schema: {value['trajectory_schema']}")
    source_trajectories = {
        key: SourceTrajectorySample(**{
            **item,
            "strokes": [SourceTrajectoryStroke(**stroke) for stroke in item["strokes"]],
        })
        for key, item in value.get("source_trajectories", {}).items()
    }
    prototypes = {key: StrokePrototype(**item) for key, item in value["prototypes"].items()}
    component_layouts = {
        key: ComponentLayoutPrototype(**item)
        for key, item in value.get("component_layouts", {}).items()
    }
    character_layouts = {
        key: ComponentLayoutPrototype(**item)
        for key, item in value.get("character_layouts", {}).items()
    }
    component_strokes = {
        key: ComponentStrokePrototype(**item)
        for key, item in value.get("component_strokes", {}).items()
    }
    component_relations = {
        key: ComponentRelationPrototype(**item)
        for key, item in value.get("component_relations", {}).items()
    }
    component_trajectories = {
        key: ComponentTrajectoryPrototype(**item)
        for key, item in value.get("component_trajectories", {}).items()
    }
    character_component_trajectories = {
        key: ComponentTrajectoryPrototype(**item)
        for key, item in value.get("character_component_trajectories", {}).items()
    }
    factorized_style = (
        FactorizedStyleProfile(**value["factorized_style"])
        if value.get("factorized_style")
        else None
    )
    return StyleProfile(
        **{
            **value,
            "prototypes": prototypes,
            "component_layouts": component_layouts,
            "character_layouts": character_layouts,
            "component_strokes": component_strokes,
            "component_relations": component_relations,
            "component_trajectories": component_trajectories,
            "character_component_trajectories": character_component_trajectories,
            "factorized_style": factorized_style,
            "source_trajectories": source_trajectories,
        }
    )
