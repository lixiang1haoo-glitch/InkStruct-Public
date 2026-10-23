from dataclasses import asdict
from unittest.mock import patch

import numpy as np
from test_source_generation_entry import fixture

from inkstruct.generate import DeterministicGenerator
from inkstruct.trajectory_experiment import SharedTransform, invariants
from inkstruct.v6_exp import FullReferenceGenerator, V6ExpGenerator


def test_no_donor_keeps_every_reference_vertex(tmp_path):
    graphs, repo, _baseline, profile, _ = fixture(tmp_path)
    profile.source_trajectories = {"池": profile.source_trajectories["池"]}
    graph = graphs["池"]
    before = asdict(graph)
    glyph, meta = V6ExpGenerator(profile, repo).generate(graph)
    assert meta["accepted_component_count"] == 0 and meta["no_donor"]
    for output, source in zip(glyph.strokes, graph.strokes, strict=True):
        assert [(p.x, p.y) for p in output.points] == source.median
    assert asdict(graph) == before
    assert not invariants(glyph, graph)


def test_complete_donor_single_similarity_no_spline_or_v4(tmp_path):
    graphs, repo, _baseline, profile, _ = fixture(tmp_path)
    before = asdict(profile)
    # Full-reference generation must work even if all v4/spline entry points fail.
    with (
        patch.object(DeterministicGenerator, "generate", side_effect=AssertionError("v4 called")),
        patch("inkstruct.generate.cubic_bspline", side_effect=AssertionError("spline called")),
    ):
        result, meta = V6ExpGenerator(profile, repo).generate(graphs["池"])
    assert meta["accepted_component_count"] > 0
    assert not invariants(result, graphs["池"])
    for comp in meta["components"]:
        selected = comp.get("selection", {}).get("selected")
        if not selected:
            continue
        t = SharedTransform(**selected["transform"])
        assert t.sx == t.sy and t.sx > 0
        candidate = selected["candidate"]
        assert candidate["character"] != "池"
        src = {
            s.standard_stroke_id: s
            for s in profile.source_trajectories[candidate["sample_id"]].strokes
        }
        outputs = {s.standard_stroke_id: s for s in result.strokes}
        for target_id, source_id in zip(
            comp["target_stroke_ids"], candidate["stroke_ids"], strict=True
        ):
            a, b = outputs[target_id], src[source_id]
            assert len(a.points) == len(b.points)
            np.testing.assert_allclose(
                [(p.x, p.y) for p in a.points], t.apply(b.points), atol=1e-12
            )
            assert [p.pressure for p in a.points] == b.pressure
    assert asdict(profile) == before


def test_v6_does_not_change_default_generator(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    before = asdict(baseline.generate(graphs["池"]))
    V6ExpGenerator(profile, repo).generate(graphs["池"])
    assert asdict(baseline.generate(graphs["池"])) == before


def test_reference_corners_and_time_survive_short_segments(tmp_path):
    graphs, _repo, _baseline, profile, _ = fixture(tmp_path)
    g = graphs["池"]
    g.strokes[0].median = [(0.1, 0.1), (0.3, 0.1), (0.3, 0.100001), (0.28, 0.100001)]
    output = FullReferenceGenerator(profile, "fixture").generate(g)
    assert [(p.x, p.y) for p in output.strokes[0].points] == g.strokes[0].median
    assert not invariants(output, g)


def test_old_prototypes_and_target_capture_cannot_affect_v6(tmp_path):
    import copy

    graphs, repo, _baseline, profile, _ = fixture(tmp_path)
    first = asdict(V6ExpGenerator(profile, repo).generate(graphs["池"])[0])
    changed = copy.deepcopy(profile)
    # Deliberately unusable v4 memories: they must never be consumed by v6.
    changed.prototypes = {"poison": object()}
    changed.component_trajectories = {"poison": object()}
    changed.global_style = {"scale_x": 999.0, "slant": 999.0}
    for stroke in changed.source_trajectories["池"].strokes:
        stroke.points = [(x + 10, y + 10) for x, y in stroke.points]
    second = asdict(V6ExpGenerator(changed, repo).generate(graphs["池"])[0])
    assert first == second


def test_empty_source_archive_is_valid_reference_fallback(tmp_path):
    graphs, repo, _baseline, profile, _ = fixture(tmp_path)
    profile.source_trajectories = {}
    glyph, report = V6ExpGenerator(profile, repo).generate(graphs["池"])
    assert report["no_donor"]
    assert not invariants(glyph, graphs["池"])
    for generated, reference in zip(glyph.strokes, graphs["池"].strokes, strict=True):
        assert [(p.x, p.y) for p in generated.points] == reference.median
