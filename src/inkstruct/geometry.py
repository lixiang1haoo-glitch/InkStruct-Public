from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from itertools import pairwise

import numpy as np

from .schemas import Point2D, StrokeSignature

EPSILON = 1e-9


def clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def bbox(points: Sequence[Point2D]) -> tuple[float, float, float, float]:
    if not points:
        raise ValueError("cannot calculate a bounding box for an empty stroke")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def path_length(points: Sequence[Point2D]) -> float:
    return sum(math.dist(left, right) for left, right in pairwise(points))


def resample(points: Sequence[Point2D], count: int = 16) -> list[Point2D]:
    if count < 2:
        raise ValueError("resample count must be at least two")
    if not points:
        raise ValueError("cannot resample an empty stroke")
    if len(points) == 1:
        return [tuple(map(float, points[0]))] * count
    values = np.asarray(points, dtype=np.float64)
    segment_lengths = np.linalg.norm(np.diff(values, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    if cumulative[-1] <= EPSILON:
        return [tuple(map(float, points[0]))] * count
    targets = np.linspace(0.0, cumulative[-1], count)
    x = np.interp(targets, cumulative, values[:, 0])
    y = np.interp(targets, cumulative, values[:, 1])
    return [(float(px), float(py)) for px, py in zip(x, y)]


def normalize_user_points(
    points: Iterable[tuple[float, float]], width: float, height: float
) -> list[Point2D]:
    if width <= 0 or height <= 0:
        raise ValueError("canvas dimensions must be positive")
    return [(clamp01(x / width), clamp01(y / height)) for x, y in points]


def direction_code(dx: float, dy: float) -> str:
    if abs(dx) + abs(dy) <= EPSILON:
        return "·"
    angle = math.atan2(dy, dx)
    index = round(angle / (math.pi / 4)) % 8
    return "→↘↓↙←↖↑↗"[index]


def stroke_signature(points: Sequence[Point2D]) -> StrokeSignature:
    sampled = resample(points, 12)
    codes: list[str] = []
    angles: list[float] = []
    for left, right in pairwise(sampled):
        dx, dy = right[0] - left[0], right[1] - left[1]
        code = direction_code(dx, dy)
        if code != "·" and (not codes or code != codes[-1]):
            codes.append(code)
        if abs(dx) + abs(dy) > EPSILON:
            angles.append(math.atan2(dy, dx))
    angle_changes: list[float] = []
    for left, right in pairwise(angles):
        change = (right - left + math.pi) % (2 * math.pi) - math.pi
        angle_changes.append(change)
    curvature = sum(abs(value) for value in angle_changes) / max(1, len(angle_changes))
    turns = sum(abs(value) >= math.pi / 5 for value in angle_changes)
    x0, y0, x1, y1 = bbox(sampled)
    width, height = x1 - x0, y1 - y0
    if width > height * 1.8:
        aspect = "wide"
    elif height > width * 1.8:
        aspect = "tall"
    else:
        aspect = "balanced"
    hook = bool(angle_changes and abs(angle_changes[-1]) > math.pi / 2)
    return StrokeSignature("".join(codes) or "·", turns, curvature, aspect, hook)


def signature_key(signature: StrokeSignature) -> str:
    hook = "h" if signature.hook else "n"
    return f"{signature.directions}|{signature.turns}|{signature.aspect}|{hook}"


def polyline_distance(left: Sequence[Point2D], right: Sequence[Point2D], count: int = 16) -> float:
    a = np.asarray(resample(left, count), dtype=np.float64)
    b = np.asarray(resample(right, count), dtype=np.float64)
    direct = float(np.mean(np.linalg.norm(a - b, axis=1)))
    reverse = float(np.mean(np.linalg.norm(a - b[::-1], axis=1)))
    return min(direct, reverse + 0.08)


def cubic_bspline(
    control_points: Sequence[Point2D], samples: int, *, clip: bool = True
) -> list[Point2D]:
    """Evaluate an open cubic uniform B-spline without scipy."""
    if samples < 2:
        raise ValueError("samples must be at least two")
    if len(control_points) < 4:
        return resample(control_points, samples)
    controls = np.asarray(control_points, dtype=np.float64)
    padded = np.vstack(([controls[0]] * 3, controls, [controls[-1]] * 3))
    segments = len(padded) - 3
    result: list[Point2D] = []
    for position in np.linspace(0.0, segments - 1e-9, samples):
        index = min(int(position), segments - 1)
        t = position - index
        basis = np.asarray(
            [
                (1 - t) ** 3 / 6,
                (3 * t**3 - 6 * t**2 + 4) / 6,
                (-3 * t**3 + 3 * t**2 + 3 * t + 1) / 6,
                t**3 / 6,
            ]
        )
        point = basis @ padded[index : index + 4]
        result.append(
            (clamp01(point[0]), clamp01(point[1])) if clip else (float(point[0]), float(point[1]))
        )
    return result
