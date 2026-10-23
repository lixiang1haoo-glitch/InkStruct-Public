import importlib.util
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_pipeline import make_structure

from inkstruct.generate import DeterministicGenerator
from inkstruct.schemas import SourceTrajectoryStroke, StyleProfile
from inkstruct.source_trajectory import arc_parameters
from inkstruct.trajectory_experiment import (
    assemble,
    crossing_pairs,
    curve_error,
    decode_component,
    invariants,
    point_distances,
    protected_indices,
    shared_transform,
    simplify_protected,
    stroke_metrics,
)


def source(points, start=0):
    return SourceTrajectoryStroke("s1", 1, points, [0.4] * len(points),
                                  [start + i * 3 for i in range(len(points))],
                                  arc_parameters(points), 0.9)


def test_one_transform_preserves_whole_component_and_anisotropy_bound():
    strokes = [[(0.1, 0.2), (0.3, 0.7)], [(0.15, 0.3), (0.4, 0.5)]]
    transform = shared_transform(strokes, (0.3, 0.2, 0.9, 0.6))
    assert transform.sx == transform.sy
    original = np.asarray([p for s in strokes for p in s])
    transformed = np.asarray([p for s in strokes for p in transform.apply(s)])
    assert np.allclose(np.diff(transformed, axis=0), np.diff(original, axis=0) * transform.sx)
    xy = shared_transform(strokes, (0.3, 0.2, 0.9, 0.6), "bounded_xy", 1.15)
    assert max(xy.sx, xy.sy) / min(xy.sx, xy.sy) <= 1.15 + 1e-12


def test_bounded_simplification_preserves_corner_hook_and_source_slots():
    points = [(float(x), 0.2) for x in np.linspace(0.1, 0.8, 45)]
    points += [(0.8, float(y)) for y in np.linspace(0.2, 0.8, 30)]
    points += [(float(x), 0.8) for x in np.linspace(0.8, 0.77, 10)]
    indices = simplify_protected(points, 0.002)
    assert protected_indices(points) <= set(indices)
    assert len(indices) < len(points)
    simplified = [points[i] for i in indices]
    assert point_distances(points, simplified).max() <= 0.002 + 1e-12
    assert simplified[0] == points[0] and simplified[-1] == points[-1]
    s = source(points, 500)
    t = shared_transform([points], (0.1, 0.1, 0.9, 0.9))
    b, _, _ = decode_component([s], t, "B")
    c, retained, _ = decode_component([s], t, "C", 0.002)
    assert c[0]["time"] == [s.t_ms[i] for i in retained[0]]
    assert c[0]["pressure"] == [s.pressure[i] for i in retained[0]]
    assert stroke_metrics(c[0]["points"], b[0]["points"])["terminal_angle_deg"] < 1e-5


def test_evaluation_is_independent_of_collinear_sample_density():
    sparse = [(0.1, 0.2), (0.8, 0.2)]
    dense = [(float(x), 0.2) for x in np.linspace(0.1, 0.8, 133)]
    assert curve_error(sparse, dense)[1] < 1e-12
    shifted = [(x, y + 0.03) for x, y in dense]
    mean, maximum = curve_error(sparse, shifted)
    assert mean == pytest.approx(0.03)
    assert maximum == pytest.approx(0.03)


def test_crossing_is_not_bbox_overlap_or_endpoint_contact():
    assert crossing_pairs([[(0, 0), (1, 1)], [(0, 1), (1, 0)]]) == {(0, 1)}
    assert not crossing_pairs([[(0, 0), (1, 0)], [(1, 0), (1, 1)]])
    assert not crossing_pairs([[(0, 0), (1, 1)], [(0, 0.1), (0.8, 1)]])
    assert crossing_pairs([[(0, 0), (0.5, 0.5), (1, 1)],
                           [(0, 1), (0.5, 0.5), (1, 0)]]) == {(0, 1)}
    assert not crossing_pairs([[(0, 0), (1, 0)], [(0, 1), (0.5, 0), (1, 1)]])


def test_retiming_corrected_strokes_and_validation(tmp_path):
    graph = make_structure(tmp_path).get("十")
    profile = StyleProfile("style_profile_v4", "fixed", "writer", "fixed", "none",
                           0, 0, {}, {}, {})
    base = DeterministicGenerator(profile, "fixture").generate(graph)
    replacements = {
        0: {"points": [(0.2, 0.3), (0.8, 0.3)], "pressure": [0.4, 0.5], "time": [900, 930]},
        1: {"points": [(0.5, 0.1), (0.5, 0.8)], "pressure": [0.3, 0.6], "time": [100, 200]},
    }
    before = asdict(base)
    glyph = assemble(base, replacements, "B")
    assert invariants(glyph, graph) == []
    assert [p.t_ms for s in glyph.strokes for p in s.points] == [0, 30, 90, 190]
    assert asdict(base) == before
    glyph.strokes[0].points[0].pressure = float("nan")
    assert "nonfinite" in invariants(glyph, graph)


def test_invalid_transform_and_simplification_rejected():
    with pytest.raises(ValueError, match="degenerate"):
        shared_transform([[(0, 0), (0, 1)]], (0.1, 0.1, 0.9, 0.9))
    with pytest.raises(ValueError):
        simplify_protected([(0, 0), (1, 1)], -0.01)


def test_cross_generation_cannot_read_missing_target_capture(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "raw_experiment_runner", Path(__file__).parents[1] / "scripts/run_raw_trajectory_experiment.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    repository = make_structure(tmp_path)
    graph = repository.get("十")
    profile = StyleProfile("style_profile_v4", "fixed", "writer", "fixed", "none",
                           0, 0, {}, {}, {})
    donor = [source([(0.1, 0.4), (0.9, 0.4)]),
             source([(0.5, 0.1), (0.5, 0.9)], 100)]
    for stroke, standard in zip(donor, graph.strokes, strict=True):
        stroke.standard_stroke_id = standard.stroke_id
    experiment = runner.Experiment.__new__(runner.Experiment)
    experiment.repository = repository
    experiment.training = DeterministicGenerator(profile, "fixture")
    experiment.protocol = {"split": {"甲": "train", "十": "test"}, "anisotropy_ratio_cap": 1.15}
    experiment.sources = {"donor-only": SimpleNamespace(strokes=donor)}
    task = {"id": "heldout", "task": "cross", "character": "十",
            "target_sample_id": "deliberately-unavailable",
            "target_stroke_ids": [s.stroke_id for s in graph.strokes],
            "candidate": {"character": "甲", "sample_id": "donor-only",
                          "stroke_ids": [s.stroke_id for s in graph.strokes]}}
    _, _, variants, provenance = experiment.generate(task, 0.004)
    assert set(variants) == {"A", "B", "C", "M", "B_xy", "C_xy", "M_xy"}
    assert provenance["B"]["transform"]["sx"] == provenance["B"]["transform"]["sy"]
    assert all(not invariants(glyph, graph) for glyph in variants.values())
