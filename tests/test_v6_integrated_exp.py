import copy
from dataclasses import asdict
from unittest.mock import patch

import numpy as np
import pytest
from test_source_generation_entry import fixture
from test_structure_corrections import fixture_repository

from inkstruct.generate import DeterministicGenerator
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.schemas import StyleProfile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.trajectory_experiment import invariants
from inkstruct.v6_integrated_exp import IntegratedV6Generator, framed_graph


def test_restored_overflow_is_fitted_before_output_validation(tmp_path):
    base, graphics, dictionary, config = fixture_repository(tmp_path)
    corrected = CorrectedStructureRepository(base, graphics, dictionary, config)
    profile = StyleProfile(
        "style_profile_v4",
        "test",
        "writer",
        "fixed",
        "none",
        0,
        0,
        {},
        {},
        {},
        trajectory_schema="source_trajectory_v1",
        build_identity={"structure_sha256": base.content_sha256()},
    )
    original = asdict(base.get("一"))
    raw = corrected.get("一")
    assert max(y for s in raw.strokes for x, y in s.median) > 1
    glyph, report = IntegratedV6Generator(profile, base, corrected).generate("一")
    expected = framed_graph(raw, reference_frame(raw))
    assert [(p.x, p.y) for p in glyph.strokes[0].points] == expected.strokes[0].median
    assert not invariants(glyph, raw)
    assert asdict(base.get("一")) == original
    assert (
        report["bridge"]["mapping_structure_sha256"] != report["bridge"]["target_structure_sha256"]
    )
    assert not report["bridge"]["source_realign"]


def test_round_curves_corners_pressure_and_time_are_preserved(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    original = asdict(profile)
    default = asdict(baseline.generate(graphs["池"]))
    engine = IntegratedV6Generator(profile, repo, repo)
    with patch.object(DeterministicGenerator, "generate", side_effect=AssertionError("legacy")):
        glyph, meta = engine.generate("池")
    assert meta["accepted_component_count"] > 0
    for part in meta["components"]:
        selected = part.get("selection", {}).get("selected")
        if not selected:
            continue
        candidate, transform = selected["candidate"], selected["transform"]
        mapping = {
            s.standard_stroke_id: s
            for s in profile.source_trajectories[candidate["sample_id"]].strokes
        }
        outputs = {s.standard_stroke_id: s for s in glyph.strokes}
        for target_id, source_id in zip(
            part["target_stroke_ids"], candidate["stroke_ids"], strict=True
        ):
            source, output = mapping[source_id], outputs[target_id]
            xy = np.asarray(source.points) * transform["sx"] + [transform["tx"], transform["ty"]]
            np.testing.assert_allclose([(p.x, p.y) for p in output.points], xy, atol=1e-12)
            assert [p.pressure for p in output.points] == source.pressure
            np.testing.assert_array_equal(
                np.diff([p.t_ms for p in output.points]), np.diff(source.t_ms)
            )
    assert not invariants(glyph, graphs["池"])
    assert asdict(profile) == original
    assert asdict(baseline.generate(graphs["池"])) == default
    replay, _ = engine.generate("池", locked_schedule=meta)
    assert [[asdict(p) for p in s.points] for s in replay.strokes] == [
        [asdict(p) for p in s.points] for s in glyph.strokes
    ]


def test_hash_and_mapping_mismatches_reject(tmp_path):
    graphs, repo, _, profile, _ = fixture(tmp_path)
    altered = copy.copy(repo)
    altered.content_sha256 = lambda: "unrelated"
    with pytest.raises(ValueError, match="verified correction"):
        IntegratedV6Generator(profile, repo, altered)
    bad = copy.deepcopy(profile)
    bad.build_identity["structure_sha256"] = "forged"
    with pytest.raises(ValueError, match="different structure"):
        IntegratedV6Generator(bad, repo, repo)
    target = copy.copy(repo)
    changed = copy.deepcopy(graphs["池"])
    changed.strokes[0].order = 99
    target.get = lambda _: changed
    with pytest.raises(ValueError, match="identity/order"):
        IntegratedV6Generator(profile, repo, target).generate("池")


def test_unsafe_locked_donor_reverts_to_complete_reference(tmp_path):
    graphs, repo, _, profile, _ = fixture(tmp_path)
    engine = IntegratedV6Generator(profile, repo, repo)
    _, schedule = engine.generate("池")
    for part in schedule["components"]:
        selected = part.get("selection", {}).get("selected")
        if selected:
            selected["transform"]["tx"] = 100
    glyph, report = engine.generate("池", locked_schedule=schedule)
    assert report["accepted_component_count"] == 0
    assert not invariants(glyph, graphs["池"])
    reference = framed_graph(graphs["池"], reference_frame(graphs["池"]))
    for a, b in zip(glyph.strokes, reference.strokes, strict=True):
        assert [(p.x, p.y) for p in a.points] == b.median


def test_target_capture_does_not_affect_generation(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    first = IntegratedV6Generator(profile, repo, repo).generate("池")[0]
    for stroke in profile.source_trajectories["池"].strokes:
        stroke.points = [(x + 5, y + 5) for x, y in stroke.points]
    second = IntegratedV6Generator(profile, repo, repo).generate("池")[0]
    assert asdict(first) == asdict(second)


def test_frozen_schedule_cannot_cross_target_identity(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    engine = IntegratedV6Generator(profile, repo, repo)
    _, schedule = engine.generate("池")
    with pytest.raises(ValueError, match="different target"):
        engine.generate("沱", locked_schedule=schedule)
