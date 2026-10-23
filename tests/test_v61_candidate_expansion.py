import copy

import pytest
from test_component_generation import make_graph
from test_source_generation_entry import fixture

from inkstruct.trajectory_experiment import SharedTransform
from inkstruct.v61_candidate_expansion import (
    CandidateExpansionGenerator,
    ExpansionPolicy,
    correspondence,
    fit_bounded_axes,
)
from inkstruct.v61_exp import Placement, V61ExpGenerator


def test_axis_fit_is_whole_component_bounded_positive_and_preserves_vertices():
    x = [[(0., 0.), (.2, .4), (.3, .7)], [(0., .8), (.7, .9)]]
    expected = SharedTransform(.6, .72, .15, .04)
    y = [expected.apply(s) for s in x]
    # Anchor arclength shifts under anisotropy, so fitted axes need not exactly
    # recover the construction, but point count and a single map must be retained.
    t = fit_bounded_axes(x, y)
    assert max(t.sx, t.sy) / min(t.sx, t.sy) <= 1.35
    assert [len(t.apply(s)) for s in x] == [3, 2]
    with pytest.raises(ValueError, match='ratio'):
        fit_bounded_axes(x, [SharedTransform(.2, 1., 0., 0.).apply(s) for s in x])
    with pytest.raises(ValueError):
        fit_bounded_axes(x, [[(-a, b) for a, b in s] for s in x])


def test_context_bridge_does_not_relax_identity_order_or_mapping():
    target = make_graph('池', '也')
    source = copy.deepcopy(target)
    tn = next(n for n in target.components if n.canonical == '也')
    sn = next(n for n in source.components if n.canonical == '也')
    sn.role = 'bottom'
    assert correspondence(source, sn, target, tn)['max_error'] < 1e-12
    sn.confidence = .79
    with pytest.raises(ValueError, match='confidence'):
        correspondence(source, sn, target, tn, anisotropic=True)
    sn.confidence = 1.
    sn.glyph_variant = '它'
    with pytest.raises(ValueError, match='identity'):
        correspondence(source, sn, target, tn, anisotropic=True)


def test_default_emit_still_rejects_axis_fit_and_opt_in_bound_is_enforced():
    p = Placement('x', (), (), {}, SharedTransform(.8, 1., 0., 0.), 0.)
    base = object.__new__(V61ExpGenerator)
    exp = object.__new__(CandidateExpansionGenerator)
    with pytest.raises(ValueError, match='isotropic'):
        base.validate_transform(p)
    with pytest.raises(ValueError, match='isotropic'):
        exp.validate_transform(p)
    p.candidate['bounded_axis_experiment'] = True
    exp.validate_transform(p)
    with pytest.raises(ValueError, match='isotropic'):
        base.validate_transform(p)
    p = Placement('x', (), (), p.candidate, SharedTransform(.5, 1., 0., 0.), 0.)
    with pytest.raises(ValueError, match='invalid'):
        exp.validate_transform(p)


def test_disabled_extension_is_exact_and_target_samples_never_selected(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    engine = CandidateExpansionGenerator(profile, repo, repo)
    ctx = engine.prepare('池')
    _, same, plan, log = engine.extend(ctx, ctx.baseline_plan)
    assert same == engine.emit(ctx, ctx.baseline_plan) and not log
    _, glyph, plan, _ = engine.extend(ctx, {}, ExpansionPolicy(context=True, hierarchy=True, whole_target=True))
    assert all(p.candidate['character'] != '池' for p in plan.values())
    assert len(glyph.strokes) == len(ctx.graph.strokes)
    sample = profile.source_trajectories['沱']
    sample.strokes[0].confidence = .29
    engine._inventories.clear()
    records = engine.inventory(False)
    assert any(errors for entries in records.values() for _, _, q, errors in entries
               if q['sample_id'] == '沱' and sample.strokes[0].standard_stroke_id in q['stroke_ids'])


def test_whole_target_arm_does_not_retry_ordinary_leaf_candidates(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    engine = CandidateExpansionGenerator(profile, repo, repo)
    ctx = engine.prepare('池')
    _, _, plan, log = engine.extend(ctx, {}, ExpansionPolicy(whole_target=True))
    # Source is 沱, whose root is not 池. Its matching leaf 也 must not leak
    # into an experiment labelled "only whole-target reuse".
    assert not plan and not log


def test_expansion_keeps_archive_and_structure_immutable_and_excludes_all_self_samples(tmp_path):
    graphs, repo, _, profile, _ = fixture(tmp_path)
    profile.source_trajectories.pop('沱')
    repeated = copy.deepcopy(profile.source_trajectories['池'])
    repeated.sample_id = 'repeat'
    profile.source_trajectories['repeat'] = repeated
    old_profile, old_graphs = copy.deepcopy(profile), copy.deepcopy(graphs)
    engine = CandidateExpansionGenerator(profile, repo, repo)
    ctx = engine.prepare('池')
    _, _, plan, _ = engine.extend(ctx, {}, ExpansionPolicy(context=True, hierarchy=True, nested=True, whole_target=True))
    assert not plan
    assert profile == old_profile and graphs == old_graphs
