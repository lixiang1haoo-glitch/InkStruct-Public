from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

import numpy as np

from .geometry import path_length, resample
from .schemas import Point2D


def dtw_distance(left: Sequence[Point2D], right: Sequence[Point2D], count: int = 32) -> float:
    """Direction-preserving DTW distance between two arc-length sampled strokes."""
    a = np.asarray(resample(left, count), dtype=np.float64)
    b = np.asarray(resample(right, count), dtype=np.float64)
    costs = np.full((count + 1, count + 1), np.inf, dtype=np.float64)
    costs[0, 0] = 0.0
    for row in range(1, count + 1):
        for column in range(1, count + 1):
            local = float(np.linalg.norm(a[row - 1] - b[column - 1]))
            costs[row, column] = local + min(
                costs[row - 1, column],
                costs[row, column - 1],
                costs[row - 1, column - 1],
            )
    return float(costs[count, count] / (count * 2))


def chamfer_distance(left: Sequence[Point2D], right: Sequence[Point2D], count: int = 32) -> float:
    a = np.asarray(resample(left, count), dtype=np.float64)
    b = np.asarray(resample(right, count), dtype=np.float64)
    distances = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=-1)
    return float((distances.min(axis=1).mean() + distances.min(axis=0).mean()) / 2)


def endpoint_error(left: Sequence[Point2D], right: Sequence[Point2D]) -> float:
    return float((math.dist(left[0], right[0]) + math.dist(left[-1], right[-1])) / 2)


def tangent_error(left: Sequence[Point2D], right: Sequence[Point2D], count: int = 16) -> float:
    a = np.asarray(resample(left, count), dtype=np.float64)
    b = np.asarray(resample(right, count), dtype=np.float64)
    ta = np.diff(a, axis=0)
    tb = np.diff(b, axis=0)
    ta /= np.maximum(np.linalg.norm(ta, axis=1, keepdims=True), 1e-9)
    tb /= np.maximum(np.linalg.norm(tb, axis=1, keepdims=True), 1e-9)
    cosine = np.clip(np.sum(ta * tb, axis=1), -1.0, 1.0)
    return float(np.mean(np.arccos(cosine)) / math.pi)


def curvature_error(left: Sequence[Point2D], right: Sequence[Point2D], count: int = 16) -> float:
    def curvature(points: Sequence[Point2D]) -> np.ndarray:
        values = np.asarray(resample(points, count), dtype=np.float64)
        first = np.diff(values, axis=0)
        angles = np.arctan2(first[:, 1], first[:, 0])
        changes = np.diff(np.unwrap(angles))
        return changes / math.pi

    return float(np.mean(np.abs(curvature(left) - curvature(right))))


def _point_segment_distance(
    points: np.ndarray, start: np.ndarray, end: np.ndarray
) -> np.ndarray:
    vector = end - start
    denominator = max(float(np.dot(vector, vector)), 1e-12)
    projection = np.clip(((points - start) @ vector) / denominator, 0.0, 1.0)
    closest = start + projection[:, None] * vector
    return np.linalg.norm(points - closest, axis=1)


def stroke_distance_field(
    strokes: Sequence[Sequence[Point2D]], *, size: int = 64, radius: float = 0.012
) -> np.ndarray:
    """Unsigned centerline distance minus radius; negative values are ink."""
    if size < 8:
        raise ValueError("distance-field size must be at least eight")
    radius = max(radius, 0.6 / size)
    axis = (np.arange(size, dtype=np.float64) + 0.5) / size
    yy, xx = np.meshgrid(axis, axis, indexing="ij")
    pixels = np.stack((xx.reshape(-1), yy.reshape(-1)), axis=1)
    minimum = np.full(len(pixels), np.inf, dtype=np.float64)
    for stroke in strokes:
        sampled = resample(stroke, max(8, min(48, len(stroke))))
        for start, end in pairwise(np.asarray(sampled, dtype=np.float64)):
            minimum = np.minimum(minimum, _point_segment_distance(pixels, start, end))
    if not np.isfinite(minimum).any():
        return np.ones((size, size), dtype=np.float64)
    return (minimum - radius).reshape(size, size)


def render_metrics(
    generated: Sequence[Sequence[Point2D]],
    target: Sequence[Sequence[Point2D]],
    *,
    sizes: Sequence[int] = (64, 128),
) -> dict[str, float]:
    sdf_values: list[float] = []
    iou_values: list[float] = []
    for size in sizes:
        predicted = stroke_distance_field(generated, size=size)
        expected = stroke_distance_field(target, size=size)
        sdf_values.append(float(np.mean(np.abs(np.clip(predicted, -0.08, 0.08) - np.clip(expected, -0.08, 0.08)))))
        a, b = predicted <= 0, expected <= 0
        union = np.logical_or(a, b).sum()
        iou_values.append(float(np.logical_and(a, b).sum() / max(1, int(union))))
    return {
        "sdf_distance": float(np.mean(sdf_values)),
        "render_iou": float(np.mean(iou_values)),
        **{f"sdf_{size}": value for size, value in zip(sizes, sdf_values)},
        **{f"iou_{size}": value for size, value in zip(sizes, iou_values)},
    }


def style_descriptor(strokes: Sequence[Sequence[Point2D]]) -> np.ndarray:
    points = np.asarray([point for stroke in strokes for point in stroke], dtype=np.float64)
    if len(points) < 2:
        return np.zeros(20, dtype=np.float64)
    minimum, maximum = points.min(axis=0), points.max(axis=0)
    span = maximum - minimum
    centered = points - points.mean(axis=0)
    covariance = np.cov(centered.T) if len(points) > 2 else np.eye(2)
    lengths = np.asarray([path_length(stroke) for stroke in strokes], dtype=np.float64)
    directions: list[float] = []
    for stroke in strokes:
        sampled = np.asarray(resample(stroke, 12), dtype=np.float64)
        delta = np.diff(sampled, axis=0)
        directions.extend(np.arctan2(delta[:, 1], delta[:, 0]).tolist())
    histogram, _ = np.histogram(directions, bins=8, range=(-math.pi, math.pi), density=False)
    histogram = histogram / max(1, histogram.sum())
    descriptor = np.concatenate(
        (
            span,
            points.mean(axis=0),
            covariance.reshape(-1),
            [len(strokes) / 32.0, lengths.mean(), lengths.std(), lengths.max()],
            histogram,
        )
    )
    return descriptor.astype(np.float64)


def style_similarity(
    generated: Sequence[Sequence[Point2D]], target: Sequence[Sequence[Point2D]]
) -> float:
    left, right = style_descriptor(generated), style_descriptor(target)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator > 1e-12 else 0.0


def aggregate_stroke_metrics(
    generated: Sequence[Sequence[Point2D]], target: Sequence[Sequence[Point2D]]
) -> dict[str, float]:
    if len(generated) != len(target):
        raise ValueError("stroke metrics require equal stroke counts")
    rows = [
        {
            "dtw": dtw_distance(left, right),
            "chamfer": chamfer_distance(left, right),
            "endpoint": endpoint_error(left, right),
            "tangent": tangent_error(left, right),
            "curvature": curvature_error(left, right),
        }
        for left, right in zip(generated, target)
    ]
    result = {key: float(np.mean([row[key] for row in rows])) for key in rows[0]}
    result.update(render_metrics(generated, target))
    result["style_similarity"] = style_similarity(generated, target)
    return result
