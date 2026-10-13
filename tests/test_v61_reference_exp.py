from dataclasses import asdict, replace

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.trajectory_experiment import SharedTransform
from inkstruct.v61_exp import Placement, V61ExpGenerator, curves
from inkstruct.v61_reference_exp import ReferenceAblationGenerator, fit_envelope


def test_envelope_uses_only_whole_component_bounds_not_stroke_correspondence():
    source = [[(0, 0), (0.7, 0.2), (1, 1)], [(0.1, 0.8), (0.6, 0.9)]]
    target = [[(0.2, 0.1), (0.8, 0.9)], [(0.3, 0.3), (0.5, 0.4)]]
    t = fit_envelope(source, target)
    assert t.sx == t.sy == pytest.approx(.6)
    assert (t.tx, t.ty) == pytest.approx((.2, .2))
    # Different reference interiors and extra collinear samples do not change placement.
    changed = [[(0.2, 0.1), (0.79, 0.89), (0.8, 0.9)], [(0.5, 0.4), (0.3, 0.3)]]
    assert fit_envelope(source, changed) == t
    assert fit_envelope([source[0], source[1][::-1]], target) == t
    with pytest.raises(ValueError):
        fit_envelope([[(0, 0), (0, 0)]], target)


def test_rank_ablation_retains_confidence_peer_and_gap_cost():
    p = Placement('c', ('id',), (0,), {'confidence':.7}, SharedTransform(1,1,0,0), .08)
    low = ReferenceAblationGenerator.__new__(ReferenceAblationGenerator)
    original = V61ExpGenerator.__new__(V61ExpGenerator)
    gap = original.ranking_score(p,.2,.3)-low.ranking_score(p,.2,.3)
    assert gap == pytest.approx(.75*(.08-.0003*.3))
    assert low.ranking_score(p,.2,.3)-low.ranking_score(p,.2,0) == pytest.approx(.3)


def test_fixed_donors_source_integrity_and_scale_refusal(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    before = asdict(profile)
    engine = ReferenceAblationGenerator(profile, repo, repo)
    ctx = engine.prepare('池')
    assert ctx.baseline_plan
    plan, log = engine.envelope_layout(ctx,ctx.baseline_plan)
    g, m = engine.finish(ctx, plan, layout_log=log)
    assert not any(m['checks'].values())
    for cid,p in plan.items():
        assert p.candidate == ctx.baseline_plan[cid].candidate
        assert p.transform.sx == p.transform.sy > 0
        for i,s,xy in zip(p.indices,engine.source(p),engine.placed(p),strict=True):
            assert curves(g)[i] == xy
            assert [q.pressure for q in g.strokes[i].points] == s.pressure
            np.testing.assert_array_equal(np.diff([q.t_ms for q in g.strokes[i].points]),np.diff(s.t_ms))
    # An extreme scale is rejected, rather than silently clamped or deforming strokes.
    extreme = {cid:replace(p,transform=SharedTransform(.00001,.00001,0,0))
               for cid,p in ctx.baseline_plan.items()}
    retained, reasons = engine.envelope_layout(ctx,extreme)
    assert retained == extreme
    assert all('scale outside' in r['reason'] for r in reasons)
    assert asdict(profile) == before
