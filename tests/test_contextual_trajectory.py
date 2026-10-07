import numpy as np
import pytest

from inkstruct.contextual_trajectory import (
    fit_shared_displacement,
    fit_shared_similarity,
    place_component,
)


def test_similarity_recovers_one_transform_for_all_strokes():
    source = [[(.1, .2), (.3, .5), (.4, .7)], [(.2, .8), (.8, .2)]]
    target = [[(x * .6 + .2, y * .6 + .1) for x, y in s] for s in source]
    transform = fit_shared_similarity(source, target)
    assert transform.sx == pytest.approx(.6)
    assert transform.sy == transform.sx
    assert transform.tx == pytest.approx(.2)
    assert transform.ty == pytest.approx(.1)
    for a, b in zip(source, target, strict=True):
        assert np.allclose(transform.apply(a), b)


def test_shared_field_is_spatial_not_stroke_specific_and_preserves_vertices():
    source = [[(.1, .2), (.5, .5), (.8, .7)], [(.2, .8), (.5, .5), (.8, .1)]]
    target = [[(x + .05 * y, y - .08 * x) for x, y in s] for s in source]
    field = fit_shared_displacement(source, target)
    assert field.derivative_bound <= .25 + 1e-12
    left, right = [field.apply(s) for s in source]
    assert left[1] == right[1]
    assert len(left) == len(source[0])
    # Independently check the claimed global distortion bound on a spatial grid.
    grid = np.array([(x, y) for x in np.linspace(-.2, 1.2, 9) for y in np.linspace(-.2, 1.2, 9)])
    warped = np.array(field.apply(grid))
    original_distance = np.linalg.norm(grid[:, None] - grid, axis=2)
    new_distance = np.linalg.norm(warped[:, None] - warped, axis=2)
    mask = original_distance > 0
    ratios = new_distance[mask] / original_distance[mask]
    assert ratios.min() >= 1 - field.derivative_bound - 1e-10
    assert ratios.max() <= 1 + field.derivative_bound + 1e-10


def test_zero_field_is_identity_and_invalid_parameters_rejected():
    source = [[(.1, .1), (.4, .8)], [(.2, .4), (.7, .3)]]
    field = fit_shared_displacement(source, source, strength=0)
    assert np.allclose(field.apply(source[0]), source[0])
    with pytest.raises(ValueError):
        fit_shared_displacement(source, source, derivative_cap=1)
    with pytest.raises(ValueError):
        fit_shared_similarity(source, source[:1])
    with pytest.raises(ValueError):
        place_component([[(0, 0), (0, 0)]], [[(0, 0), (1, 1)]])


def test_selector_needs_no_target_capture_and_preserves_source_point_count(tmp_path):
    from test_pipeline import make_structure

    from inkstruct.contextual_trajectory import choose_component
    from inkstruct.generate import DeterministicGenerator
    from inkstruct.schemas import SourceTrajectorySample, SourceTrajectoryStroke, StyleProfile
    from inkstruct.source_trajectory import arc_parameters
    from inkstruct.trajectory_experiment import invariants

    repository = make_structure(tmp_path)
    graph = repository.get('十')
    profile = StyleProfile('style_profile_v4', 'fixed', 'writer', 'fixed', 'none',
                           0, 0, {}, {}, {})
    base = DeterministicGenerator(profile, 'fixture').generate(graph)
    source = []
    for stroke in base.strokes:
        p = [(v.x, v.y) for v in stroke.points]
        source.append(SourceTrajectoryStroke(stroke.standard_stroke_id, stroke.order,
                       p, [.45] * len(p), list(range(len(p))), arc_parameters(p), .9))
    sample = SourceTrajectorySample('only-training-donor', '甲', 'hash', 'declared', source)
    candidate = {'character': '甲', 'sample_id': sample.sample_id, 'source_sha256': 'hash',
                 'stroke_ids': [s.standard_stroke_id for s in source], 'score': 0.}
    glyph, metadata = choose_component(base, graph, candidate['stroke_ids'], [candidate], {sample.sample_id: sample})
    assert not invariants(glyph, graph)
    assert metadata['fallback_reason'] is None
    assert [len(s.points) for s in glyph.strokes] == [len(s.points) for s in source]
    same, rejected = choose_component(base, graph, candidate['stroke_ids'], [], {})
    assert same is base and rejected['fallback_reason']
    with pytest.raises(ValueError, match='target character'):
        choose_component(base, graph, candidate['stroke_ids'], [{**candidate, 'character': '十'}], {sample.sample_id: sample})
