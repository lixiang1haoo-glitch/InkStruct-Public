from dataclasses import asdict

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.component_aspect import (
    fit_bounded_aspect,
    prepare_aspect_candidates,
    solve_bounded_correspondences,
)
from inkstruct.contextual_trajectory import anchors, choose_component, fit_shared_similarity
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.trajectory_experiment import invariants


def test_bounded_fit_is_shared_positive_and_optimal_inside_the_cap():
    source = [[(0., 0.), (.2, .1), (.3, .4)], [(.1, .2), (.2, .6), (.5, .7)]]
    target = [(np.asarray(s)*[1.8, .7]+[.1, .05]).tolist() for s in source]
    cap = 1.25
    result = solve_bounded_correspondences(anchors(source), anchors(target), cap)
    assert result.sx > 0 and result.sy > 0
    assert result.sx/result.sy == pytest.approx(cap)
    x, y = anchors(source), anchors(target)
    actual_error = np.sum((x*[result.sx, result.sy]+[result.tx, result.ty]-y)**2)
    xc, yc = x-x.mean(0), y-y.mean(0)
    for ratio in np.linspace(1/cap, cap, 101):
        for sy in np.linspace(.3, 2., 101):
            assert actual_error <= np.sum((xc*[ratio*sy, sy]-yc)**2)+1e-12
    exact = fit_bounded_aspect(source, target, 2.)
    assert exact.sx/exact.sy <= 2.+1e-12
    assert asdict(fit_bounded_aspect(source, target, 1.)) == asdict(fit_shared_similarity(source, target))
    for bad in (0., .9, 2.1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            fit_bounded_aspect(source, target, bad)


def test_bounded_fit_recovers_feasible_diagonal_map_without_per_stroke_scaling():
    source = [[(0., 0.), (.2, .1), (.3, .4)], [(.1, .2), (.2, .6), (.5, .7)]]
    target = [(np.asarray(s)*[1.2, 1.]+[.1, .05]).tolist() for s in source]
    result = fit_bounded_aspect(source, target, 1.25)
    for a, b in zip(source, target, strict=True):
        np.testing.assert_allclose(result.apply(a), b, atol=1e-5)


def test_unit_cap_matches_frozen_D_and_every_candidate_preserves_full_source(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    candidates = index.candidates(graph, component)
    ids = ordered_ids(graph, component)
    base = baseline.generate(graph)
    expected, metadata = choose_component(base, graph, ids, candidates, index.sources)
    off = prepare_aspect_candidates(base, graph, ids, candidates, index.sources, cap=1.)
    for fixed in (False, True):
        output, report = off.select(fixed_donor=fixed)
        assert asdict(output) == asdict(expected)
        assert report['selected']['candidate'] == metadata['selected']['candidate']
    trial = prepare_aspect_candidates(base, graph, ids, candidates, index.sources, cap=1.5)
    output, fixed = trial.select(fixed_donor=True)
    assert fixed['selected']['candidate'] == metadata['selected']['candidate']
    for output, record in trial.alternatives:
        assert not invariants(output, graph)
        sample = index.sources[record['candidate']['sample_id']]
        source = {s.standard_stroke_id: s for s in sample.strokes}
        transform = record['transform']
        for target, sid in zip(ids, record['candidate']['stroke_ids'], strict=True):
            stroke = next(s for s in output.strokes if s.standard_stroke_id == target)
            original = source[sid]
            assert len(stroke.points) == len(original.points)
            np.testing.assert_allclose([(p.x, p.y) for p in stroke.points],
                np.asarray(original.points)*[transform['sx'], transform['sy']]+[transform['tx'], transform['ty']])
            assert [p.pressure for p in stroke.points] == original.pressure
            np.testing.assert_array_equal(np.diff([p.t_ms for p in stroke.points]), np.diff(original.t_ms))


def test_empty_and_illegal_pools_cannot_sneak_in_a_target_capture(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    base = baseline.generate(graph)
    trial = prepare_aspect_candidates(base, graph, ['s1', 's2', 's3'], [], profile.source_trajectories, cap=1.5)
    assert trial.select()[0] is base and trial.select(fixed_donor=True)[0] is base
    index = ExemplarIndex(profile, repo)
    component = next(c for c in graph.components if c.path == 'root.0')
    donor = index.candidates(graph, component)[0]
    with pytest.raises(ValueError, match='target character'):
        prepare_aspect_candidates(base, graph, ['s1', 's2', 's3'], [{**donor, 'character': '池'}], index.sources, cap=1.5)
