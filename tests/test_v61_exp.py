import copy
from dataclasses import asdict

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.v61_contacts import contact_pairs, segment_clearance
from inkstruct.v61_exp import V61ExpGenerator, curves


def test_segment_contacts_do_not_use_bbox_overlap_or_only_vertices():
    assert segment_clearance([(0, 0), (1, 1)], [(0, 1), (1, 0)]) == 0
    assert segment_clearance([(0, 0), (1, 0)], [(0.5, 0), (2, 0)]) == 0
    assert segment_clearance([(0, 0), (1, 1)], [(0, 0.2), (0.7, 0.9)]) == pytest.approx(
        0.2 / np.sqrt(2)
    )
    assert segment_clearance([(0, 0), (0, 0)], [(0.1, 0), (0.2, 0)]) == pytest.approx(0.1)
    assert contact_pairs([[(0, 0), (1, 0)], [(0.2, 0.02), (0.8, 0.02)]], 0.028) == {(0, 1)}
    assert not contact_pairs([[(0, 0), (1, 0)], [(0.2, 0.02), (0.8, 0.02)]], 0.01)


def test_staged_baseline_replay_and_frozen_candidate_transforms(tmp_path):
    graphs, repo, old, profile, _ = fixture(tmp_path)
    before = asdict(profile)
    default = asdict(old.generate(graphs["池"]))
    engine = V61ExpGenerator(profile, repo, repo)
    ctx = engine.prepare("池")
    selected, _ = engine.select(ctx)
    for cid, p in selected.items():
        assert p in ctx.pools[cid]
    laid, log = engine.layout(ctx, selected)
    output, meta = engine.finish(ctx, laid, layout_log=log)
    assert not any(meta["checks"].values())
    for cid, p in laid.items():
        oldp = selected[cid]
        assert p.candidate == oldp.candidate
        assert p.transform.sx == oldp.transform.sx == p.transform.sy
        assert (
            np.hypot(p.transform.tx - oldp.transform.tx, p.transform.ty - oldp.transform.ty)
            <= 0.028 + 1e-12
        )
        for i, s, xy in zip(p.indices, engine.source(p), engine.placed(p), strict=True):
            assert curves(output)[i] == xy
            assert [q.pressure for q in output.strokes[i].points] == s.pressure
            np.testing.assert_array_equal(
                np.diff([q.t_ms for q in output.strokes[i].points]), np.diff(s.t_ms)
            )
    assert asdict(profile) == before
    assert asdict(old.generate(graphs["池"])) == default


def test_no_source_does_not_fabricate_style_or_close_reference(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    profile.source_trajectories = {}
    engine = V61ExpGenerator(profile, repo, repo)
    ctx = engine.prepare("池")
    g, m = engine.generate("池")
    assert curves(g) == curves(ctx.baseline)
    assert m["source_strokes"] == 0 and "insufficient" in m["style_status"]
    assert all("reference_fallback" in s.style_source for s in g.strokes)


def test_target_sample_cannot_steer_selection_or_layout(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    a = V61ExpGenerator(profile, repo, repo).generate("池")[0]
    changed = copy.deepcopy(profile)
    for s in changed.source_trajectories["池"].strokes:
        s.points = [(x + 3, y - 2) for x, y in s.points]
    b = V61ExpGenerator(changed, repo, repo).generate("池")[0]
    assert asdict(a) == asdict(b)


def test_layout_removes_inter_component_brush_collision_without_straightening(tmp_path):
    from types import SimpleNamespace

    from inkstruct.trajectory_experiment import SharedTransform
    from inkstruct.v6_exp import FullReferenceGenerator
    from inkstruct.v61_exp import Context, Placement

    graphs, _, _, profile, _ = fixture(tmp_path)
    graph = copy.deepcopy(graphs["池"])
    graph.strokes = graph.strokes[:2]
    # Curved source keeps its bulge; only its shared translation can change.
    graph.strokes[0].median = [(0.29, 0.2), (0.30, 0.5), (0.29, 0.8)]
    graph.strokes[1].median = [(0.36, 0.2), (0.36, 0.8)]
    ref = FullReferenceGenerator(profile, "fixture").generate(graph)
    sid = graph.strokes[0].stroke_id
    source = SimpleNamespace(
        standard_stroke_id=sid,
        points=graph.strokes[0].median,
        pressure=[0.2, 0.8, 0.4],
        t_ms=[100, 105, 120],
    )
    sample = SimpleNamespace(character="沱", source_sha256="fixed", strokes=[source])
    profile.source_trajectories = {"donor": sample}
    engine = V61ExpGenerator.__new__(V61ExpGenerator)
    engine.profile = profile
    p = Placement(
        "part",
        (sid,),
        (0,),
        {"sample_id": "donor", "character": "沱", "source_sha256": "fixed", "stroke_ids": [sid]},
        SharedTransform(1, 1, 0.04, 0),
        0.0,
    )
    ctx = Context("池", graph, ref, ref, {}, {}, {"part": p}, set(), {(0, 1)}, set(), [(0, 1)])
    before = engine.emit(ctx, ctx.baseline_plan)
    assert contact_pairs(curves(before)) == {(0, 1)}
    plan, log = engine.layout(ctx, ctx.baseline_plan)
    after = engine.emit(ctx, plan)
    assert log[0]["applied"] and not contact_pairs(curves(after))
    delta = np.asarray(curves(after)[0]) - np.asarray(curves(before)[0])
    np.testing.assert_allclose(delta, np.tile(delta[0], (3, 1)), atol=1e-12)
    assert curves(after)[1] == curves(before)[1]
    assert [p.pressure for p in after.strokes[0].points] == source.pressure
