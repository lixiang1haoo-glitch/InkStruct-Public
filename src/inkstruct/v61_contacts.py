"""Exact polyline clearance diagnostics for v6.1 exp; not font truth labels."""

from __future__ import annotations

from itertools import combinations

import numpy as np

from .trajectory_experiment import crossing_pairs, point_distances

BRUSH_WIDTH = 0.028  # Same normalized diagnostic brush as the frozen v6 report.


def segment_clearance(left, right):
    """Minimum segment distance, including interior intersections and degeneracy.

    For nonintersecting segments the minimum lies on an endpoint. Collinear
    overlaps are covered by endpoint projections; proper crossings need testing.
    No resampling, bounding-box overlap approximation or output mutation.
    """
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if len(a) < 2 or len(b) < 2 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("clearance requires finite polylines")
    if crossing_pairs([left, right]):
        return 0.0
    return min(float(point_distances(a, b).min()), float(point_distances(b, a).min()))


def contact_pairs(curves, width=BRUSH_WIDTH):
    if not np.isfinite(width) or width <= 0:
        raise ValueError("brush width must be positive and finite")
    boxes = [np.array([np.min(c, axis=0), np.max(c, axis=0)]) for c in curves]
    return {
        (i, j)
        for i, j in combinations(range(len(curves)), 2)
        if np.linalg.norm(
            np.maximum(0, np.maximum(boxes[i][0] - boxes[j][1], boxes[j][0] - boxes[i][1]))
        )
        <= width
        if segment_clearance(curves[i], curves[j]) <= width
    }


def contact_report(curves, reference, width=BRUSH_WIDTH):
    rows = []
    for i, j in combinations(range(len(curves)), 2):
        gap = segment_clearance(curves[i], curves[j])
        ref = segment_clearance(reference[i], reference[j])
        endpoints = [
            float(point_distances([p], curves[j])[0]) for p in (curves[i][0], curves[i][-1])
        ]
        endpoints += [
            float(point_distances([p], curves[i])[0]) for p in (curves[j][0], curves[j][-1])
        ]
        rows.append(
            {
                "orders": [i + 1, j + 1],
                "centerline_gap": gap,
                "brush_gap": gap - width,
                "reference_gap": ref,
                "endpoint_to_other_stroke": endpoints,
                "new_brush_contact_vs_reference": gap <= width and ref > width,
                "clear_reference_but_crowded": gap < width and ref >= 2 * width,
            }
        )
    return {
        "width": width,
        "pairs": rows,
        "brush_contacts": sum(r["brush_gap"] <= 0 for r in rows),
        "new_brush_contacts_vs_reference": sum(r["new_brush_contact_vs_reference"] for r in rows),
        "interpretation": "constant round-pen centerline-distance model; review signals, not intended-contact truth",
    }
