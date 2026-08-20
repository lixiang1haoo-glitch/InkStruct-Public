from __future__ import annotations

import math

import numpy as np

from inkstruct.metrics import (
    aggregate_stroke_metrics,
    chamfer_distance,
    dtw_distance,
    stroke_distance_field,
)


def test_identical_strokes_have_zero_geometric_error() -> None:
    stroke = [(0.1, 0.2), (0.5, 0.4), (0.9, 0.8)]
    assert dtw_distance(stroke, stroke) == 0.0
    assert chamfer_distance(stroke, stroke) < 1e-12
    metrics = aggregate_stroke_metrics([stroke], [stroke])
    assert metrics["dtw"] == 0.0
    assert metrics["sdf_distance"] == 0.0
    assert math.isclose(metrics["render_iou"], 1.0)


def test_distance_field_is_finite_and_contains_ink() -> None:
    field = stroke_distance_field([[(0.2, 0.5), (0.8, 0.5)]], size=32)
    assert field.shape == (32, 32)
    assert np.isfinite(field).all()
    assert np.min(field) < 0
