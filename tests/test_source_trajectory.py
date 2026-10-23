import json
from dataclasses import asdict

import pytest
from test_alignment_order import _sample, _two_horizontal_graph
from test_pipeline import make_sample, make_structure

from inkstruct.alignment import align_sample
from inkstruct.generate import DeterministicGenerator
from inkstruct.profile import build_profile, load_profile
from inkstruct.samples import import_samples, iter_index
from inkstruct.schemas import AlignedGlyph
from inkstruct.source_trajectory import arc_parameters, source_trajectory


def test_corrected_source_keeps_pressure_time_and_physical_aspect():
    sample = _sample((700, 300))
    sample.canvas_width = 1200
    sample.canvas_height = 800
    for i, stroke in enumerate(sample.strokes):
        stroke.points[0].pressure = 0.2 + i * 0.4
    graph = _two_horizontal_graph()
    aligned = align_sample(sample, graph)
    source, reason = source_trajectory(sample, aligned, graph)
    assert reason is None
    assert [s.user_order for s in source.strokes] == [2, 1]
    assert [s.pressure[0] for s in source.strokes] == pytest.approx([0.6, 0.2])
    assert [s.t_ms[0] for s in source.strokes] == [20, 0]
    assert [s.standard_stroke_id for s in source.strokes] == [s.stroke_id for s in graph.strokes]
    assert source.strokes[0].arc_parameters == [0.0, 1.0]
    a, b = source.strokes[0].points
    c = source.strokes[1].points[0]
    assert (b[0] - a[0]) / abs(c[1] - a[1]) == pytest.approx(600 / 400)
    assert len(aligned.normalized_strokes[0]) == 16
    assert len(source.strokes[0].points) == 2


def test_ambiguous_and_legacy_channels_do_not_invent_source_points():
    graph = _two_horizontal_graph()
    sample = _sample((549, 451))
    aligned = align_sample(sample, graph)
    assert source_trajectory(sample, aligned, graph)[0] is None
    sample = _sample((300, 700))
    payload = asdict(align_sample(sample, graph))
    payload.pop("source_normalized_strokes")
    # Old construction still works with the new optional field.
    payload["mappings"] = align_sample(sample, graph).mappings
    legacy = AlignedGlyph(**payload)
    assert source_trajectory(sample, legacy, graph)[1] == "missing source trajectory channel"


def test_low_confidence_and_split_mappings_do_not_enter_source_channel():
    sample, graph = _sample((300, 700)), _two_horizontal_graph()
    aligned = align_sample(sample, graph)
    aligned.mappings[0].confidence = 0.29
    assert source_trajectory(sample, aligned, graph)[1] == "low-confidence source mapping"
    aligned.mappings[0].mapping_type = "many_to_one"
    assert source_trajectory(sample, aligned, graph)[0] is None


def test_stationary_points_keep_pressure_time_slots():
    assert arc_parameters([(0, 0), (0, 0), (1, 0)]) == [0.0, 0.0, 1.0]
    assert arc_parameters([(0, 0), (0, 0)]) == [0.0, 0.0]


def test_profile_extension_roundtrip_identity_and_legacy_output(tmp_path):
    repository = make_structure(tmp_path / "structure")
    make_sample(tmp_path / "raw" / "sample.json")
    imported = import_samples(tmp_path / "raw", "writer-1", tmp_path / "samples")
    from pathlib import Path

    index = Path(imported["index"])
    legacy, path = build_profile("writer-1", index, repository, tmp_path / "legacy")
    extended, extended_path = build_profile(
        "writer-1", index, repository, tmp_path / "extended", retain_source_trajectories=True
    )
    assert legacy.source_trajectories == {}
    assert extended.profile_version != legacy.profile_version
    assert extended.build_identity["structure_sha256"]
    assert extended.source_trajectories["fixture-sample"].source_sha256 == next(
        iter_index(index)
    ).source_sha256
    reloaded = load_profile(extended_path)
    assert json.dumps(asdict(reloaded), sort_keys=True) == json.dumps(asdict(extended), sort_keys=True)
    graph = repository.get("十")
    old = DeterministicGenerator(legacy, "fixture").generate(graph)
    new = DeterministicGenerator(reloaded, "fixture").generate(graph)
    assert [asdict(s) for s in old.strokes] == [asdict(s) for s in new.strokes]
    assert legacy.style_tokens == extended.style_tokens
    assert all(len(token) == 40 for token in extended.style_tokens)
    assert asdict(legacy)["component_trajectories"] == asdict(extended)["component_trajectories"]
    # JSON produced before the extension loads without a migration.
    payload = json.loads(path.read_text())
    for key in ("trajectory_schema", "source_trajectories", "build_identity"):
        payload.pop(key)
    path.write_text(json.dumps(payload))
    assert load_profile(path).source_trajectories == {}
    # A changed structure identity must not reuse a profile version.
    import sqlite3

    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE metadata SET value = 'different' WHERE key = 'source_version'")
    changed, _ = build_profile("writer-1", index, repository, tmp_path / "changed")
    assert changed.profile_version != legacy.profile_version


def test_unknown_extension_version_is_rejected(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"trajectory_schema": "source_trajectory_future"}))
    with pytest.raises(ValueError, match="unsupported trajectory schema"):
        load_profile(path)
