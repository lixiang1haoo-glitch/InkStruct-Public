"""Lossless normalized capture channel, independent of legacy control points."""

from __future__ import annotations

import math
from itertools import pairwise

from .alignment import standard_order_indices
from .schemas import (
    AlignedGlyph,
    CharacterGraph,
    RawSample,
    SourceTrajectorySample,
    SourceTrajectoryStroke,
)

TRAJECTORY_SCHEMA = "source_trajectory_v1"
MIN_MAPPING_CONFIDENCE = 0.30


def arc_parameters(points: list[tuple[float, float]]) -> list[float]:
    distances = [0.0]
    for start, end in pairwise(points):
        distances.append(distances[-1] + math.dist(start, end))
    total = distances[-1]
    return [value / total for value in distances] if total > 0 else distances


def source_trajectory(
    sample: RawSample, aligned: AlignedGlyph, graph: CharacterGraph
) -> tuple[SourceTrajectorySample | None, str | None]:
    """Keep geometry, pressure and time under the *same* standard-to-user map.

    Require a complete, unambiguous one-to-one glyph. Split/merged strokes and
    low confidence remain on the legacy path. Never reconstruct from 16 points.
    Times retain their captured values, so a corrected stroke permutation is not
    globally time-monotonic; a future decoder must assign new output timestamps.
    """
    indices = standard_order_indices(aligned, len(graph.strokes))
    if indices is None or len(sample.strokes) != len(graph.strokes):
        return None, "requires unambiguous one-to-one stroke mapping"
    if not aligned.source_normalized_strokes:
        return None, "missing source trajectory channel"
    confidences = {m.standard_orders[0]: m.confidence for m in aligned.mappings}
    if any(confidences[i + 1] < MIN_MAPPING_CONFIDENCE for i in range(len(indices))):
        return None, "low-confidence source mapping"
    strokes = []
    for standard, user_index in zip(graph.strokes, indices, strict=True):
        points = aligned.source_normalized_strokes[user_index]
        raw = sample.strokes[user_index].points
        if not len(points) == len(raw) == len(aligned.pressure_strokes[user_index]) == len(
            aligned.time_strokes[user_index]
        ):
            raise ValueError("source geometry, pressure and time have different lengths")
        strokes.append(SourceTrajectoryStroke(
            standard_stroke_id=standard.stroke_id,
            user_order=user_index + 1,
            points=list(points),
            pressure=list(aligned.pressure_strokes[user_index]),
            t_ms=list(aligned.time_strokes[user_index]),
            arc_parameters=arc_parameters(points),
            confidence=confidences[standard.order],
        ))
    return SourceTrajectorySample(
        sample_id=sample.sample_id,
        character=sample.character,
        source_sha256=sample.source_sha256,
        stroke_order_status=aligned.stroke_order_status,
        strokes=strokes,
    ), None
