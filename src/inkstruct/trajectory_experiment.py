"""Opt-in raw-trajectory experiments. Nothing here changes production generation.

Coordinates are normalized glyph units. Variable-length output is retained;
quadrature used by evaluation never replaces the delivered polylines.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from .geometry import bbox, cubic_bspline, path_length, resample
from .schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke


def cumulative(points):
    a = np.asarray(points, dtype=float)
    return np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(a, axis=0), axis=1))]


def at_distance(points, distance):
    a, s = np.asarray(points, dtype=float), cumulative(points)
    unique = np.r_[True, np.diff(s) > 1e-12]
    return np.array([np.interp(distance, s[unique], a[unique, axis]) for axis in (0, 1)])


def angle_degrees(left, right):
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    if denominator <= 1e-12:
        return None
    return float(np.degrees(np.arccos(np.clip(np.dot(left, right) / denominator, -1, 1))))


def point_distances(points, curve):
    points, curve = np.asarray(points, dtype=float), np.asarray(curve, dtype=float)
    start, vector = curve[:-1], np.diff(curve, axis=0)
    denominator = np.maximum(np.sum(vector * vector, axis=1), 1e-24)
    values = []
    for chunk in range(0, len(points), 256):
        p = points[chunk:chunk + 256]
        t = np.clip(np.sum((p[:, None] - start) * vector, axis=2) / denominator, 0, 1)
        distances = np.linalg.norm(p[:, None] - start - t[:, :, None] * vector, axis=2)
        values.extend(distances.min(axis=1))
    return np.asarray(values)


def quadrature(points, step=0.003):
    """Midpoint arc-length integration; preserve every original vertex for max error."""
    a = np.asarray(points, dtype=float)
    query, weights = [], []
    for start, end in pairwise(a):
        length = float(np.linalg.norm(end - start))
        if length <= 1e-12:
            continue
        count = max(1, math.ceil(length / step))
        query.extend(start + ((np.arange(count) + 0.5) / count)[:, None] * (end - start))
        weights.extend([length / count] * count)
    if not query:
        return a[:1], np.ones(1), a
    return np.asarray(query), np.asarray(weights), np.vstack([a, query])


def curve_error(predicted, reference, step=0.003):
    p, pw, pv = quadrature(predicted, step)
    r, rw, rv = quadrature(reference, step)
    mean = (np.average(point_distances(p, reference), weights=pw)
            + np.average(point_distances(r, predicted), weights=rw)) / 2
    maximum = max(float(point_distances(pv, reference).max()),
                  float(point_distances(rv, predicted).max()))
    return float(mean), maximum


def bend_angles(points, radius):
    s = cumulative(points)
    result = np.zeros(len(points))
    for i, position in enumerate(s):
        if position < radius or s[-1] - position < radius:
            continue
        center = np.asarray(points[i])
        before, after = at_distance(points, position - radius), at_distance(points, position + radius)
        result[i] = angle_degrees(center - before, after - center) or 0.0
    return result


def protected_indices(points):
    s = cumulative(points)
    length = s[-1]
    keep = {0, len(points) - 1}
    if length <= 1e-10:
        return keep
    # Preserve the endpoint neighborhoods verbatim, including any tiny terminal
    # hook. Add one point before the terminal window to preserve interpolation.
    tail = min(0.025, 0.25 * length)
    first_tail = max(0, int(np.searchsorted(s, length - tail)) - 1)
    keep.update(range(first_tail, len(points)))
    keep.update(np.flatnonzero(s <= min(0.01, 0.1 * length)).tolist())
    radius = min(0.012, length * 0.08)
    a, b = bend_angles(points, radius), bend_angles(points, radius * 1.5)
    keep.update(np.flatnonzero((a >= 45) & (b >= 45)).tolist())
    return keep


def simplify_protected(points, epsilon):
    """Segment-wise RDP with hard feature/endpoint locks; return source indices."""
    if not math.isfinite(epsilon) or epsilon < 0:
        raise ValueError("epsilon must be finite and nonnegative")
    if len(points) < 2 or not np.isfinite(points).all():
        raise ValueError("invalid source polyline")
    if epsilon == 0:
        return list(range(len(points)))
    keep = protected_indices(points)
    fixed = sorted(keep)
    stack = list(pairwise(fixed))
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        distances = point_distances(points[start + 1:end], [points[start], points[end]])
        index = int(np.argmax(distances)) + start + 1
        if float(distances.max()) > epsilon:
            keep.add(index)
            stack.extend(((start, index), (index, end)))
    return sorted(keep)


@dataclass(frozen=True)
class SharedTransform:
    sx: float
    sy: float
    tx: float
    ty: float

    def apply(self, points):
        return [(x * self.sx + self.tx, y * self.sy + self.ty) for x, y in points]


def shared_transform(strokes, target_bbox, mode="similarity", ratio_cap=1.15):
    source = bbox([p for stroke in strokes for p in stroke])
    width, height = source[2] - source[0], source[3] - source[1]
    target_width, target_height = target_bbox[2] - target_bbox[0], target_bbox[3] - target_bbox[1]
    if min(width, height, target_width, target_height) <= 1e-8:
        raise ValueError("degenerate component bounding box")
    sx, sy = target_width / width, target_height / height
    if mode == "similarity":
        sx = sy = min(sx, sy)
    elif mode == "bounded_xy":
        if not 1 <= ratio_cap <= 1.5:
            raise ValueError("invalid anisotropy bound")
        base = min(sx, sy)
        sx, sy = min(sx, base * ratio_cap), min(sy, base * ratio_cap)
    else:
        raise ValueError("unknown transform mode")
    source_center = ((source[0] + source[2]) / 2, (source[1] + source[3]) / 2)
    target_center = ((target_bbox[0] + target_bbox[2]) / 2, (target_bbox[1] + target_bbox[3]) / 2)
    return SharedTransform(sx, sy, target_center[0] - sx * source_center[0],
                           target_center[1] - sy * source_center[1])


def decode_component(source_strokes, transform, mode, epsilon=0.0):
    """All strokes share one transform. No averaging or per-stroke fitting."""
    decoded, retained = [], []
    for source in source_strokes:
        points = [tuple(p) for p in source.points]
        if mode == "B":
            indices = list(range(len(points)))
            curve = points
        elif mode == "C":
            indices = simplify_protected(points, epsilon / max(transform.sx, transform.sy))
            curve = [points[i] for i in indices]
        elif mode == "M":
            controls = resample(resample(points, 16), 8)
            count = max(24, min(128, math.ceil(path_length(transform.apply(controls)) * 120)))
            curve = resample(cubic_bspline(controls, max(64, count * 2), clip=False), count)
            indices = None
        else:
            raise ValueError("unknown experimental representation")
        if indices is not None:
            pressure = [source.pressure[i] for i in indices]
            times = [source.t_ms[i] for i in indices]
        else:
            pressure = np.interp(np.linspace(0, 1, len(curve)), source.arc_parameters,
                                 source.pressure).tolist()
            times = np.linspace(source.t_ms[0], source.t_ms[-1], len(curve)).tolist()
        decoded.append({"points": transform.apply(curve), "pressure": pressure, "time": times})
        retained.append(indices)
    fallback = None
    if mode == "C":
        raw = [transform.apply(s.points) for s in source_strokes]
        if crossing_pairs(raw) != crossing_pairs([s["points"] for s in decoded]):
            decoded, _, _ = decode_component(source_strokes, transform, "B")
            retained = [list(range(len(s.points))) for s in source_strokes]
            fallback = "simplification changed component crossing pairs; entire component uses B"
    return decoded, retained, fallback


def crossing_pairs(strokes):
    """Transverse inter-stroke crossings, including crossings at sampled vertices.

    At a shared interior vertex, four incident rays must alternate around the
    intersection. Global endpoints, tangencies and collinear overlaps are not
    counted as strict crossings. Report stroke pairs, not segment hit counts.
    """
    pairs = set()
    for i, left in enumerate(strokes):
        a = np.asarray(left[:-1])[:, None, :]
        v = np.diff(np.asarray(left), axis=0)[:, None, :]
        for j in range(i + 1, len(strokes)):
            b = np.asarray(strokes[j][:-1])[None, :, :]
            w = np.diff(np.asarray(strokes[j]), axis=0)[None, :, :]
            cross = v[..., 0] * w[..., 1] - v[..., 1] * w[..., 0]
            delta = b - a
            denominator = np.where(abs(cross) > 1e-12, cross, np.nan)
            t = (delta[..., 0] * w[..., 1] - delta[..., 1] * w[..., 0]) / denominator
            u = (delta[..., 0] * v[..., 1] - delta[..., 1] * v[..., 0]) / denominator
            if np.any((t > 1e-8) & (t < 1 - 1e-8) & (u > 1e-8) & (u < 1 - 1e-8)):
                pairs.add((i, j))
                continue
            candidates = np.argwhere((t >= -1e-8) & (t <= 1 + 1e-8)
                                     & (u >= -1e-8) & (u <= 1 + 1e-8))
            if not len(candidates):
                continue
            left_s, right_s = cumulative(left), cumulative(strokes[j])
            for si, sj in candidates:
                p = left_s[si] + t[si, sj] * (left_s[si + 1] - left_s[si])
                q = right_s[sj] + u[si, sj] * (right_s[sj + 1] - right_s[sj])
                delta = min(1e-5, p / 4, (left_s[-1] - p) / 4,
                            q / 4, (right_s[-1] - q) / 4)
                if delta <= 1e-10:
                    continue
                center = at_distance(left, p)
                rays = [at_distance(left, p - delta) - center,
                        at_distance(left, p + delta) - center,
                        at_distance(strokes[j], q - delta) - center,
                        at_distance(strokes[j], q + delta) - center]
                angles = np.array([math.atan2(r[1], r[0]) for r in rays])
                order = np.argsort(angles)
                labels = [int(k // 2) for k in order]
                gaps = np.diff(np.r_[angles[order], angles[order][0] + 2 * math.pi])
                if min(gaps) > 1e-6 and all(labels[k] != labels[(k + 1) % 4] for k in range(4)):
                    pairs.add((i, j))
                    break
    return pairs


def terminal_hook(points):
    """Operational terminal bend, not a semantic stroke/hook classifier."""
    s = cumulative(points)
    length = s[-1]
    if length < 0.03:
        return None
    radius = min(0.01, length * 0.06)
    turns = bend_angles(points, radius)
    stable = bend_angles(points, radius * 1.5)
    candidates = [i for i in range(1, len(points) - 1)
                  if s[i] >= 0.65 * length and radius * 1.5 <= length - s[i] <= 0.08
                  and turns[i] >= 55 and stable[i] >= 40]
    if not candidates:
        return None
    i = max(candidates, key=lambda k: turns[k])
    return {"index": i, "point": list(points[i]), "tail_length": float(length - s[i])}


def projected_tail_length(points, hook_point):
    a, s = np.asarray(points), cumulative(points)
    start, v = a[:-1], np.diff(a, axis=0)
    t = np.clip(np.sum((np.asarray(hook_point) - start) * v, axis=1)
                / np.maximum(np.sum(v * v, axis=1), 1e-24), 0, 1)
    distances = np.linalg.norm(start + t[:, None] * v - hook_point, axis=1)
    positions = s[:-1] + t * np.diff(s)
    distances[positions < s[-1] * 0.5] = np.inf
    k = int(np.argmin(distances))
    return float(s[-1] - positions[k])


def stroke_metrics(predicted, reference):
    mean, maximum = curve_error(predicted, reference)
    length, target_length = path_length(predicted), path_length(reference)
    window = min(0.02, 0.15 * target_length)
    pvec = np.asarray(predicted[-1]) - at_distance(predicted, max(0, length - window))
    rvec = np.asarray(reference[-1]) - at_distance(reference, max(0, target_length - window))
    hook = terminal_hook(reference)
    result = {"mean_distance": mean, "max_distance": maximum,
              "length_ratio": length / max(target_length, 1e-12),
              "absolute_length_error": abs(length - target_length) / max(target_length, 1e-12),
              "terminal_angle_deg": angle_degrees(pvec, rvec),
              "endpoint_error": float(np.linalg.norm(np.asarray(predicted[-1]) - reference[-1])),
              "hook": hook,
              "hook_length_error": None if hook is None else
                  abs(projected_tail_length(predicted, hook["point"]) - hook["tail_length"]),
              "points": len(predicted)}
    # Shape-only comparison removes whole-stroke translation/scale at evaluation
    # time only. It is supplementary, never used to position generated strokes.
    return result


def assemble(base: GeneratedGlyph, replacements: dict[int, dict], mode: str) -> GeneratedGlyph:
    strokes, cursor = [], 0
    for i, original in enumerate(base.strokes):
        replacement = replacements.get(i)
        if replacement:
            xy, pressure, times = (replacement[k] for k in ("points", "pressure", "time"))
        else:
            xy = [(p.x, p.y) for p in original.points]
            pressure, times = [p.pressure for p in original.points], [p.t_ms for p in original.points]
        start = times[0]
        points = [GeneratedPoint(float(x), float(y), cursor + round(t - start), float(p),
                                 "down" if j < len(xy) - 1 else
                                 ("end" if i == len(base.strokes) - 1 else "up"))
                  for j, ((x, y), p, t) in enumerate(zip(xy, pressure, times, strict=True))]
        cursor = points[-1].t_ms + 60
        strokes.append(GeneratedStroke(original.standard_stroke_id, original.order,
                       original.confidence, points,
                       f"experiment_{mode}" if replacement else original.style_source,
                       original.component_key))
    return GeneratedGlyph(base.schema_version, base.character, base.codepoint, base.locale,
                          base.writer_id, base.structure_version, base.profile_version,
                          f"raw_transform_experiment_{mode}", base.confidence, strokes,
                          {"policy": "experiment_shared_target_box_v1", "applied": False,
                           "inherited_A_canvas_fit": dict(base.canvas_fit)})


def invariants(glyph, graph):
    errors = []
    if len(glyph.strokes) != len(graph.strokes):
        errors.append("stroke count")
    if [(s.standard_stroke_id, s.order) for s in glyph.strokes] != [
        (s.stroke_id, s.order) for s in graph.strokes
    ]:
        errors.append("stroke ids/order")
    previous = -1
    for stroke in glyph.strokes:
        if len(stroke.points) < 2:
            errors.append("point count")
        for p in stroke.points:
            if not all(math.isfinite(v) for v in (p.x, p.y, p.pressure, p.t_ms)):
                errors.append("nonfinite")
            if not (0 <= p.x <= 1 and 0 <= p.y <= 1 and 0 <= p.pressure <= 1):
                errors.append("bounds")
            if p.t_ms < previous:
                errors.append("time order")
            previous = p.t_ms
    return sorted(set(errors))
