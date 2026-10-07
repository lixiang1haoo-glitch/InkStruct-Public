from dataclasses import asdict

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.contextual_trajectory import choose_component
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.terminal_selection import (
    TerminalCandidates,
    direction_penalty,
    prepare_terminal_candidates,
    terminal_vector,
)


def test_terminal_direction_reads_short_hook_and_abstains_on_zero_length():
    hook = [(0., 0.), (1., 0.), (1., .1), (1., .09)]
    np.testing.assert_allclose(terminal_vector(hook, .005), (0., -1.))
    assert terminal_vector([(1., 1.), (1., 1.)], .01) is None
    opposite, _ = direction_penalty([[(0., 0.), (1., 0.)]], [[(1., 0.), (0., 0.)]])
    assert opposite == pytest.approx(2.)
    abstain, detail = direction_penalty([[(0., 0.), (0., 0.)]], [[(0., 0.), (0., 0.)]])
    assert abstain == 0. and detail[0]['penalty'] is None


def test_terminal_penalty_can_change_only_the_selected_complete_candidate():
    old, alternative = object(), object()
    records = [{'score': .02, 'terminal_penalties': {'baseline': 1., 'structure': 1.}},
               {'score': .024, 'terminal_penalties': {'baseline': 0., 'structure': 0.}}]
    prepared = TerminalCandidates(None, records, [(old, records[0]), (alternative, records[1])])
    assert prepared.select()[0] is old
    assert prepared.select(.005)[0] is alternative
    for value in (-.1, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='invalid'):
            prepared.select(value)
    with pytest.raises(ValueError, match='invalid'):
        prepared.select(.01, 'target_handwriting')


def test_zero_weight_is_frozen_D_and_all_trial_curves_are_whole_source_transforms(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    candidates = index.candidates(graph, component)
    ids = ordered_ids(graph, component)
    base = baseline.generate(graph)
    expected, old = choose_component(base, graph, ids, candidates, profile.source_trajectories)
    prepared = prepare_terminal_candidates(base, graph, ids, candidates, profile.source_trajectories)
    actual, new = prepared.select()
    assert asdict(expected) == asdict(actual)
    assert old['selected']['candidate'] == new['selected']['candidate']
    assert len(prepared.alternatives) > 0
    for glyph, record in prepared.alternatives:
        source = {s.standard_stroke_id: s for s in profile.source_trajectories['沱'].strokes}
        matrix = record['transform']
        for target_id, source_id in zip(ids, record['candidate']['stroke_ids'], strict=True):
            output = next(s for s in glyph.strokes if s.standard_stroke_id == target_id)
            expected_points = np.array(source[source_id].points) * matrix['sx'] + [matrix['tx'], matrix['ty']]
            np.testing.assert_allclose([(p.x, p.y) for p in output.points], expected_points, atol=1e-12)
            assert [p.pressure for p in output.points] == source[source_id].pressure


def test_empty_candidate_pool_returns_exact_original_object(tmp_path):
    graphs, _, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    base = baseline.generate(graph)
    prepared = prepare_terminal_candidates(base, graph, ['s1', 's2', 's3'], [], profile.source_trajectories)
    result, metadata = prepared.select(.04, 'structure')
    assert result is base and metadata['fallback_reason']
