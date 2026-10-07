from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import bbox, clamp01, path_length, resample
from .schemas import AlignedGlyph, CharacterGraph, Point2D, RawSample, StrokeMapping


@dataclass(slots=True)
class _Cell:
    cost: float
    previous: tuple[int, int] | None
    mapping: StrokeMapping | None


@dataclass(slots=True)
class _OrderResolution:
    assignment: list[int]
    status: str
    confidence: float
    identity_improvement: float
    alternative_margin: float


def _shape_normalise(points: list[Point2D]) -> list[Point2D]:
    x0, y0, x1, y1 = bbox(points)
    width, height = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    scale = max(width, height)
    return [((x - x0) / scale, (y - y0) / scale) for x, y in points]


def _stroke_cost(standard: list[Point2D], user: list[Point2D]) -> float:
    standard_shape = np.asarray(resample(_shape_normalise(standard), 16))
    user_shape = np.asarray(resample(_shape_normalise(user), 16))
    direct_shape = float(np.mean(np.linalg.norm(standard_shape - user_shape, axis=1)))
    reverse_shape = float(np.mean(np.linalg.norm(standard_shape - user_shape[::-1], axis=1)))
    shape = min(direct_shape, reverse_shape + 0.10)
    sb = bbox(standard)
    ub = bbox(user)
    standard_center = ((sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2)
    user_center = ((ub[0] + ub[2]) / 2, (ub[1] + ub[3]) / 2)
    position = math.dist(standard_center, user_center)
    standard_length = max(path_length(standard), 1e-6)
    user_length = max(path_length(user), 1e-6)
    length = min(1.0, abs(math.log(user_length / standard_length)))
    direct_endpoint = 0.5 * (math.dist(standard[0], user[0]) + math.dist(standard[-1], user[-1]))
    reverse_endpoint = 0.5 * (
        math.dist(standard[0], user[-1]) + math.dist(standard[-1], user[0])
    )
    endpoint = min(direct_endpoint, reverse_endpoint + 0.08)
    standard_angle = math.atan2(
        standard[-1][1] - standard[0][1], standard[-1][0] - standard[0][0]
    )
    user_angle = math.atan2(user[-1][1] - user[0][1], user[-1][0] - user[0][0])
    angle_delta = abs((user_angle - standard_angle + math.pi) % (2 * math.pi) - math.pi)
    direction = min(angle_delta / math.pi, abs(math.pi - angle_delta) / math.pi + 0.12)
    return (
        0.45 * shape
        + 0.24 * position
        + 0.13 * endpoint
        + 0.10 * length
        + 0.08 * direction
    )


def _minimum_cost_assignment(costs: np.ndarray) -> tuple[list[int], float]:
    """Solve a square linear assignment with the O(n^3) Hungarian algorithm."""
    count = int(costs.shape[0])
    if costs.shape != (count, count):
        raise ValueError("assignment cost matrix must be square")
    potentials_row = [0.0] * (count + 1)
    potentials_column = [0.0] * (count + 1)
    column_owner = [0] * (count + 1)
    previous_column = [0] * (count + 1)
    for row in range(1, count + 1):
        column_owner[0] = row
        minimum = [float("inf")] * (count + 1)
        used = [False] * (count + 1)
        column = 0
        while True:
            used[column] = True
            owner = column_owner[column]
            delta = float("inf")
            next_column = 0
            for candidate in range(1, count + 1):
                if used[candidate]:
                    continue
                reduced = (
                    float(costs[owner - 1, candidate - 1])
                    - potentials_row[owner]
                    - potentials_column[candidate]
                )
                if reduced < minimum[candidate]:
                    minimum[candidate] = reduced
                    previous_column[candidate] = column
                if minimum[candidate] < delta:
                    delta = minimum[candidate]
                    next_column = candidate
            if not math.isfinite(delta):
                raise ValueError("stroke assignment has no finite solution")
            for candidate in range(count + 1):
                if used[candidate]:
                    potentials_row[column_owner[candidate]] += delta
                    potentials_column[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if column_owner[column] == 0:
                break
        while True:
            previous = previous_column[column]
            column_owner[column] = column_owner[previous]
            column = previous
            if column == 0:
                break
    assignment = [0] * count
    for column in range(1, count + 1):
        assignment[column_owner[column] - 1] = column - 1
    total = float(sum(costs[row, column] for row, column in enumerate(assignment)))
    return assignment, total


def _resolve_equal_count_order(
    standard_strokes: list[list[Point2D]], user_strokes: list[list[Point2D]]
) -> tuple[_OrderResolution, np.ndarray]:
    count = len(standard_strokes)
    geometric = np.asarray(
        [[_stroke_cost(standard, user) for user in user_strokes] for standard in standard_strokes],
        dtype=np.float64,
    )
    order_scale = max(1, count - 1)
    regularized = geometric.copy()
    for standard_index in range(count):
        for user_index in range(count):
            regularized[standard_index, user_index] += (
                0.025 * abs(standard_index - user_index) / order_scale
            )
    assignment, best = _minimum_cost_assignment(regularized)
    identity = list(range(count))
    if assignment == identity:
        return _OrderResolution(identity, "declared", 1.0, 0.0, 1.0), geometric
    identity_cost = float(sum(regularized[index, index] for index in range(count)))
    identity_improvement = max(0.0, (identity_cost - best) / max(1, count))
    alternatives: list[float] = []
    for standard_index, user_index in enumerate(assignment):
        forbidden = regularized.copy()
        forbidden[standard_index, user_index] = 1e6
        _, alternative = _minimum_cost_assignment(forbidden)
        alternatives.append(alternative)
    alternative_margin = max(0.0, (min(alternatives) - best) / max(1, count))
    evidence = min(1.0, identity_improvement / 0.10) * min(
        1.0, alternative_margin / 0.04
    )
    if identity_improvement >= 0.04 and alternative_margin >= 0.012:
        return (
            _OrderResolution(
                assignment,
                "corrected",
                max(0.35, evidence),
                identity_improvement,
                alternative_margin,
            ),
            geometric,
        )
    if identity_improvement >= 0.015:
        return (
            _OrderResolution(
                identity,
                "ambiguous",
                min(0.30, evidence),
                identity_improvement,
                alternative_margin,
            ),
            geometric,
        )
    return (
        _OrderResolution(
            identity, "declared", 1.0, identity_improvement, alternative_margin
        ),
        geometric,
    )


def standard_order_indices(aligned: AlignedGlyph, standard_count: int) -> list[int] | None:
    if aligned.stroke_order_status == "ambiguous":
        return None
    result: list[int | None] = [None] * standard_count
    for mapping in aligned.mappings:
        if mapping.mapping_type != "one_to_one":
            continue
        standard_index = mapping.standard_orders[0] - 1
        user_index = mapping.user_orders[0] - 1
        if not 0 <= standard_index < standard_count or result[standard_index] is not None:
            return None
        result[standard_index] = user_index
    if any(index is None for index in result) or len(set(result)) != standard_count:
        return None
    return [int(index) for index in result]


def _join(strokes: list[list[Point2D]]) -> list[Point2D]:
    result: list[Point2D] = []
    for stroke in strokes:
        result.extend(stroke)
    return result


def _normalise_glyph_extent(
    strokes: list[list[Point2D]], extent: float = 0.85
) -> list[list[Point2D]]:
    all_points = [point for stroke in strokes for point in stroke]
    x0, y0, x1, y1 = bbox(all_points)
    width, height = x1 - x0, y1 - y0
    scale = max(width, height)
    if scale <= 1e-8:
        raise ValueError("user glyph has negligible spatial extent")
    center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
    return [
        [
            (
                clamp01(0.5 + (x - center_x) * extent / scale),
                clamp01(0.5 + (y - center_y) * extent / scale),
            )
            for x, y in stroke
        ]
        for stroke in strokes
    ]


def align_sample(sample: RawSample, graph: CharacterGraph) -> AlignedGlyph:
    if sample.character != graph.character:
        raise ValueError("sample and structure characters differ")
    # x/y are both logical pixels, so preserve their common physical scale.
    # Dividing X and Y by different canvas dimensions would distort aspect ratio.
    user_strokes = [[(point.x, point.y) for point in stroke.points] for stroke in sample.strokes]
    user_strokes = _normalise_glyph_extent(user_strokes)
    standard_strokes = [stroke.median for stroke in graph.strokes]
    standard_count, user_count = len(standard_strokes), len(user_strokes)
    # Equal counts still require one-to-one topology, but the captured order is
    # not blindly trusted. A conservative global assignment corrects clear
    # permutations and marks weak/ambiguous alternatives so they cannot poison
    # component prototypes.
    if standard_count == user_count:
        order, cost_matrix = _resolve_equal_count_order(standard_strokes, user_strokes)
        mappings = []
        for standard_index, user_index in enumerate(order.assignment):
            mapping_cost = float(cost_matrix[standard_index, user_index])
            mapping_confidence = math.exp(-3.0 * mapping_cost)
            if order.status == "corrected":
                mapping_confidence *= 0.80 + 0.20 * order.confidence
            elif order.status == "ambiguous":
                mapping_confidence = min(mapping_confidence, 0.25)
            mappings.append(
                StrokeMapping(
                    standard_orders=[standard_index + 1],
                    user_orders=[user_index + 1],
                    mapping_type="one_to_one",
                    cost=mapping_cost,
                    confidence=mapping_confidence,
                )
            )
        confidence = float(np.mean([mapping.confidence for mapping in mappings]))
        warnings = []
        if order.status == "corrected":
            permutation = ",".join(str(index + 1) for index in order.assignment)
            warnings.append(
                "corrected captured stroke order: "
                f"standard_to_user=[{permutation}], confidence={order.confidence:.3f}"
            )
        elif order.status == "ambiguous":
            warnings.append(
                "ambiguous captured stroke order: sample excluded from style prototypes "
                f"(improvement={order.identity_improvement:.4f}, "
                f"margin={order.alternative_margin:.4f})"
            )
        low_confidence = [mapping for mapping in mappings if mapping.confidence < 0.35]
        if low_confidence:
            warnings.append(f"detected {len(low_confidence)} low-confidence mappings")
        return AlignedGlyph(
            schema_version="aligned_glyph_v2",
            sample_id=sample.sample_id,
            writer_id=sample.writer_id,
            character=sample.character,
            mappings=mappings,
            normalized_strokes=[resample(stroke, 16) for stroke in user_strokes],
            pressure_strokes=[
                [point.pressure for point in stroke.points] for stroke in sample.strokes
            ],
            time_strokes=[[point.t_ms for point in stroke.points] for stroke in sample.strokes],
            confidence=confidence,
            warnings=warnings,
            stroke_order_status=order.status,
            stroke_permutation=[index + 1 for index in order.assignment],
            order_confidence=order.confidence,
            order_identity_improvement=order.identity_improvement,
            order_alternative_margin=order.alternative_margin,
            source_normalized_strokes=user_strokes,
        )
    cells: list[list[_Cell]] = [
        [_Cell(float("inf"), None, None) for _ in range(user_count + 1)]
        for _ in range(standard_count + 1)
    ]
    cells[0][0] = _Cell(0.0, None, None)
    for si in range(standard_count + 1):
        for ui in range(user_count + 1):
            current = cells[si][ui]
            if not math.isfinite(current.cost):
                continue
            candidates: list[tuple[int, int, str, float]] = []
            if si < standard_count and ui < user_count:
                candidates.append(
                    (1, 1, "one_to_one", _stroke_cost(standard_strokes[si], user_strokes[ui]))
                )
            if si + 1 < standard_count and ui < user_count:
                combined = _join(standard_strokes[si : si + 2])
                candidates.append(
                    (2, 1, "one_to_many", _stroke_cost(combined, user_strokes[ui]) + 0.22)
                )
            if si < standard_count and ui + 1 < user_count:
                combined = _join(user_strokes[ui : ui + 2])
                candidates.append(
                    (1, 2, "many_to_one", _stroke_cost(standard_strokes[si], combined) + 0.22)
                )
            for standard_step, user_step, mapping_type, mapping_cost in candidates:
                next_si, next_ui = si + standard_step, ui + user_step
                total = current.cost + mapping_cost
                if total >= cells[next_si][next_ui].cost:
                    continue
                confidence = math.exp(-3.0 * mapping_cost)
                mapping = StrokeMapping(
                    standard_orders=list(range(si + 1, next_si + 1)),
                    user_orders=list(range(ui + 1, next_ui + 1)),
                    mapping_type=mapping_type,
                    cost=mapping_cost,
                    confidence=confidence,
                )
                cells[next_si][next_ui] = _Cell(total, (si, ui), mapping)
    final = cells[standard_count][user_count]
    warnings: list[str] = []
    mappings: list[StrokeMapping] = []
    if not math.isfinite(final.cost):
        warnings.append(
            f"stroke topology cannot be aligned: standard={standard_count}, user={user_count}"
        )
    else:
        position = (standard_count, user_count)
        while position != (0, 0):
            cell = cells[position[0]][position[1]]
            if cell.previous is None or cell.mapping is None:
                raise RuntimeError("broken alignment backtrace")
            mappings.append(cell.mapping)
            position = cell.previous
        mappings.reverse()
    complex_mappings = [mapping for mapping in mappings if mapping.mapping_type != "one_to_one"]
    low_confidence = [mapping for mapping in mappings if mapping.confidence < 0.35]
    if complex_mappings:
        warnings.append(f"detected {len(complex_mappings)} split/merged stroke mappings")
    if low_confidence:
        warnings.append(f"detected {len(low_confidence)} low-confidence mappings")
    confidence = float(np.mean([mapping.confidence for mapping in mappings])) if mappings else 0.0
    pressure_strokes = [[point.pressure for point in stroke.points] for stroke in sample.strokes]
    time_strokes = [[point.t_ms for point in stroke.points] for stroke in sample.strokes]
    return AlignedGlyph(
        schema_version="aligned_glyph_v2",
        sample_id=sample.sample_id,
        writer_id=sample.writer_id,
        character=sample.character,
        mappings=mappings,
        normalized_strokes=[resample(stroke, 16) for stroke in user_strokes],
        pressure_strokes=pressure_strokes,
        time_strokes=time_strokes,
        confidence=confidence,
        warnings=warnings,
        stroke_order_status="not_applicable",
        stroke_permutation=[],
        order_confidence=0.0,
        order_identity_improvement=0.0,
        order_alternative_margin=0.0,
        source_normalized_strokes=user_strokes,
    )
