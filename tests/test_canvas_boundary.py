import copy
import json
import math
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest
from test_pipeline import make_sample, make_structure

from inkstruct.canvas_boundary import fit_glyph_to_canvas
from inkstruct.capture_boundary import capture_edge_status
from inkstruct.evaluate import evaluate_run
from inkstruct.generate import DeterministicGenerator, HybridGenerator, generate_run
from inkstruct.geometry import cubic_bspline, path_length, resample
from inkstruct.profile import build_profile
from inkstruct.samples import import_samples
from inkstruct.schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke


def glyph_at(strokes):
    return GeneratedGlyph(
        "personal_trajectory_v1", "十", "U+5341", "zh-Hans", "writer-1", "fixture", "p", "g", 0.9,
        [GeneratedStroke(f"s{i + 1}", i + 1, 0.9, [
            GeneratedPoint(x, y, i * 100 + j * 10, 0.6, "down" if j == 0 else "up")
            for j, (x, y) in enumerate(stroke)
        ]) for i, stroke in enumerate(strokes)],
    )


def test_in_bounds_and_exact_boundary_contact_are_unchanged():
    glyph = glyph_at([[(0, 1), (0.31, 0.41)], [(1, 0), (0.41, 0.71)]])
    before = asdict(glyph)["strokes"]
    fit_glyph_to_canvas(glyph)
    assert asdict(glyph)["strokes"] == before
    assert not glyph.canvas_fit["applied"]


def test_floating_point_drift_does_not_shift_the_glyph():
    glyph = fit_glyph_to_canvas(glyph_at([[(-1e-12, 1 + 1e-12), (0.5, 0.5)]]))
    assert not glyph.canvas_fit["applied"]
    assert [(p.x, p.y) for p in glyph.strokes[0].points] == [(0, 1), (0.5, 0.5)]


@pytest.mark.parametrize("strokes", [
    [[(-0.1, 0.2), (0.4, 0.6)], [(0.1, 0.3), (0.7, 0.8)]],
    [[(0.1, 0.2), (1.2, 0.6)], [(0.1, 0.3), (0.7, 0.8)]],
    [[(0.1, -0.2), (0.4, 0.6)], [(0.1, 0.3), (0.7, 0.8)]],
    [[(0.1, 0.2), (0.4, 1.2)], [(0.1, 0.3), (0.7, 0.8)]],
    [[(-0.5, -0.4), (2.1, 1.6)], [(1.4, 0.3), (0.7, 2.8)]],
    [[(2, 2), (2, 2)]],
])
def test_fit_preserves_relative_shape_and_dynamics(strokes):
    glyph = glyph_at(strokes)
    original = copy.deepcopy(glyph)
    fit_glyph_to_canvas(glyph)
    scale = glyph.canvas_fit["scale"]
    offset = np.array(glyph.canvas_fit["translation"])
    for old_stroke, new_stroke in zip(original.strokes, glyph.strokes):
        assert old_stroke.standard_stroke_id == new_stroke.standard_stroke_id
        for old, new in zip(old_stroke.points, new_stroke.points):
            assert (old.t_ms, old.pressure, old.pen_state) == (new.t_ms, new.pressure, new.pen_state)
            assert 0 <= new.x <= 1 and 0 <= new.y <= 1
            np.testing.assert_allclose([new.x, new.y], np.array([old.x, old.y]) * scale + offset,
                                       atol=5.1e-7, rtol=0)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_coordinates_are_rejected(bad):
    with pytest.raises(ValueError, match="non-finite"):
        fit_glyph_to_canvas(glyph_at([[(0.2, 0.3), (bad, 0.4)]]))


def test_unclipped_curve_retains_hook_beyond_canvas():
    controls = [(0.2, 0.2), (0.3, 0.7), (0.4, 1.2), (0.7, 1.15), (0.7, 1.05)]
    raw = cubic_bspline(controls, 128, clip=False)
    clipped = cubic_bspline(controls, 128)
    assert max(y for _, y in raw) > 1
    assert sum(y == 1 for _, y in clipped) > 3
    glyph = fit_glyph_to_canvas(glyph_at([raw]))
    output = [(p.x, p.y) for p in glyph.strokes[0].points]
    assert path_length(output) == pytest.approx(path_length(raw) * glyph.canvas_fit["scale"], abs=1e-5)
    assert sum(y == 1 for _, y in output) == 0


def profile_fixture(tmp_path):
    repo = make_structure(tmp_path / "structures")
    make_sample(tmp_path / "raw" / "sample.json")
    report = import_samples(tmp_path / "raw", "writer-1", tmp_path / "samples")
    profile, path = build_profile("writer-1", report["index"], repo, tmp_path / "profiles")
    return repo, profile, path


def test_generator_retains_unclipped_geometry_before_fit(tmp_path):
    repo, profile, _ = profile_fixture(tmp_path)
    profile.prototypes = {}
    profile.global_style = {"scale_x": 1.8, "scale_y": 1.7, "offset_y": 0.4}
    generator = DeterministicGenerator(profile, "fixture", False)
    graph = repo.get("十")
    glyph = generator.generate(graph)
    assert glyph.canvas_fit["applied"]
    for standard, stroke in zip(graph.strokes, glyph.strokes):
        controls = generator._global_transform(resample(standard.median, 8))
        count = max(24, min(128, math.ceil(path_length(controls) * 120)))
        raw = resample(cubic_bspline(controls, max(64, count * 2), clip=False), count)
        expected = np.array(raw) * glyph.canvas_fit["scale"] + glyph.canvas_fit["translation"]
        np.testing.assert_allclose([(p.x, p.y) for p in stroke.points], expected, atol=5.1e-7, rtol=0)


def test_resume_refuses_old_or_different_generation_without_overwriting(tmp_path):
    repo, _, path = profile_fixture(tmp_path)
    args = ("writer-1", ["十"], repo, path)
    kwargs = {"output_root": tmp_path / "outputs", "run_id": "same", "png": False}
    _, run = generate_run(*args, **kwargs)
    manifest_path = run / "manifest.json"
    original = manifest_path.read_bytes()
    with pytest.raises(ValueError, match="identity"):
        generate_run(*args, **kwargs, component_strength=0.5)
    assert manifest_path.read_bytes() == original
    manifest, _ = generate_run(*args, **kwargs)
    assert manifest["completed_count"] == 1
    del manifest["run_identity"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    legacy = manifest_path.read_bytes()
    with pytest.raises(ValueError, match="predates"):
        generate_run(*args, **kwargs)
    assert manifest_path.read_bytes() == legacy
    manifest_path.unlink()
    with pytest.raises(ValueError, match="no manifest"):
        generate_run(*args, **kwargs)
    assert not manifest_path.exists()


def test_run_reports_fit_and_rejects_a_copied_legacy_glyph(tmp_path):
    repo, profile, path = profile_fixture(tmp_path)
    profile.global_style["offset_y"] = 0.7
    path.write_text(json.dumps(asdict(profile)), encoding="utf-8")
    kwargs = {"output_root": tmp_path / "outputs", "run_id": "overflow", "png": True}
    _, run = generate_run("writer-1", ["十"], repo, path, **kwargs)
    report = evaluate_run(run, repo)
    assert report["content_safety_passed"]
    assert report["canvas_fitted_count"] == 1
    assert report["canvas_review_characters"] == ["十"]
    assert (run / "previews" / "U+5341.png").is_file()
    assert (run / "previews" / "U+5341.svg").is_file()
    trajectory = run / "trajectories" / "U+5341.json"
    value = json.loads(trajectory.read_text(encoding="utf-8"))
    del value["canvas_fit"]
    trajectory.write_text(json.dumps(value), encoding="utf-8")
    before = trajectory.read_bytes()
    with pytest.raises(ValueError, match="cannot safely reuse"):
        generate_run("writer-1", ["十"], repo, path, **kwargs)
    assert trajectory.read_bytes() == before


@pytest.mark.parametrize("points,width,height,expected", [
    ([], 100, 200, "clear"),
    ([(50, 100)], 100, 200, "clear"),
    ([(4, 100)], 100, 200, "near"),
    ([(50, 1)], 100, 200, "edge"),
    ([(100, 100)], 100, 200, "edge"),
    ([(50, 199)], 100, 200, "edge"),
    ([(-2, 100)], 100, 200, "edge"),
    ([(1, 10), (math.nan, 10)], 100, 200, "invalid"),
    ([], 0, 200, "unavailable"),
])
def test_capture_edge_coordinates(points, width, height, expected):
    assert capture_edge_status(points, width, height) == expected


@pytest.mark.parametrize("observed_dynamics", [True, False])
def test_neural_output_and_confidence_fallback_use_boundary_fit(tmp_path, observed_dynamics):
    torch = pytest.importorskip("torch")
    repo, profile, _ = profile_fixture(tmp_path)
    profile.style_tokens = [[0.0] * 40]
    profile.global_style = {"offset_y": 0.6}
    generator = HybridGenerator.__new__(HybridGenerator)
    DeterministicGenerator.__init__(generator, profile, "fixture")

    class Prediction:
        config = SimpleNamespace(use_factorized_style=False, use_refiner=False)

        def __call__(self, style, structure, **kwargs):
            count = structure.shape[1]
            return {
                "confidence": torch.ones(1, count),
                "residual": torch.zeros(1, count, 8, 2),
                "pressure": torch.full((1, count, 8), 0.5),
                "duration": torch.full((1, count), 0.2),
                "density": torch.full((1, count), 0.5),
            }

    # Exercise production inference arithmetic on CPU; no CUDA/checkpoint needed.
    generator.torch = SimpleNamespace(
        tensor=lambda values, **kw: torch.tensor(values, dtype=kw["dtype"]),
        float32=torch.float32, inference_mode=torch.inference_mode,
    )
    generator.model = Prediction()
    generator.factorized_fallback = False
    generator.has_dynamic_supervision = observed_dynamics
    generator.training_status = "formal"
    generator.confidence_threshold = 0.5
    glyph = generator.generate(repo.get("十"))
    assert glyph.generator == "hierarchical_residual_v1"
    assert glyph.canvas_fit["applied"]
    assert all(0 <= p.y <= 1 for s in glyph.strokes for p in s.points)
    generator.confidence_threshold = 1.1
    fallback = generator.generate(repo.get("十"))
    assert fallback.generator == "deterministic_fallback_low_model_confidence"
    assert fallback.canvas_fit["applied"]
