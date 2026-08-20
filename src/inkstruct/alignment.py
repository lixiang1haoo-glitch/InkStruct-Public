from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import bbox, clamp01, path_length, polyline_distance, resample
from .schemas import AlignedGlyph, CharacterGraph, Point2D, RawSample, StrokeMapping


@dataclass(slots=True)
class _Cell:
    cost: float
    previous: tuple[int, int] | None
    mapping: StrokeMapping | None


def _shape_normalise(points: list[Point2D]) -> list[Point2D]:
    x0, y0, x1, y1 = bbox(points)
    width, height = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    scale = max(width, height)
    return [((x - x0) / scale, (y - y0) / scale) for x, y in points]


def _stroke_cost(standard: list[Point2D], user: list[Point2D]) -> float:
    shape = polyline_distance(_shape_normalise(standard), _shape_normalise(user))
    sb = bbox(standard)
    ub = bbox(user)
    standard_center = ((sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2)
    user_center = ((ub[0] + ub[2]) / 2, (ub[1] + ub[3]) / 2)
    position = math.dist(standard_center, user_center)
    standard_length = max(path_length(standard), 1e-6)
    user_length = max(path_length(user), 1e-6)
    length = min(1.0, abs(math.log(user_length / standard_length)))
    return 0.65 * shape + 0.25 * position + 0.10 * length


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
    # For regular/semicursive samples with the expected stroke count, preserve
    # the declared pen order. A free dynamic programme can otherwise invent a
    # split+merge pair merely because its geometric cost is slightly smaller.
    if standard_count == user_count:
        mappings = []
        for index, (standard, user) in enumerate(zip(standard_strokes, user_strokes)):
            mapping_cost = _stroke_cost(standard, user)
            mappings.append(
                StrokeMapping(
                    standard_orders=[index + 1],
                    user_orders=[index + 1],
                    mapping_type="one_to_one",
                    cost=mapping_cost,
                    confidence=math.exp(-3.0 * mapping_cost),
                )
            )
        confidence = float(np.mean([mapping.confidence for mapping in mappings]))
        warnings = []
        low_confidence = [mapping for mapping in mappings if mapping.confidence < 0.35]
        if low_confidence:
            warnings.append(f"detected {len(low_confidence)} low-confidence mappings")
        return AlignedGlyph(
            schema_version="aligned_glyph_v1",
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
        schema_version="aligned_glyph_v1",
        sample_id=sample.sample_id,
        writer_id=sample.writer_id,
        character=sample.character,
        mappings=mappings,
        normalized_strokes=[resample(stroke, 16) for stroke in user_strokes],
        pressure_strokes=pressure_strokes,
        time_strokes=time_strokes,
        confidence=confidence,
        warnings=warnings,
    )
