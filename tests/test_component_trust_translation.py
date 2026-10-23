from dataclasses import asdict, replace

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.author_terminal_context import AuthorTerminalEvidence, prepare_author_terminal
from inkstruct.component_trust import correspondence_bound
from inkstruct.component_trust_translation import (
    smallest_circle_center,
    translate_prepared_candidates,
)
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.exemplar_variation import source_component
from inkstruct.topology_repair import glyph_curves
from inkstruct.trajectory_experiment import invariants


def test_minimax_circle_has_known_solutions_and_abstains_on_large_hulls():
    for points, expected, radius in [
        ([(1, 2)], [1, 2], 0),
        ([(0, 0), (2, 0), (.2, .1)], [1, 0], 1),
        ([(0, 0), (2, 0), (1, np.sqrt(3))], [1, 1/np.sqrt(3)], 2/np.sqrt(3)),
        ([(-1, -1), (-1, 1), (1, -1), (1, 1), (0, 0)], [0, 0], np.sqrt(2)),
    ]:
        center, actual, _ = smallest_circle_center(points)
        np.testing.assert_allclose(center, expected, atol=1e-12)
        assert actual == pytest.approx(radius)
        assert np.linalg.norm(np.asarray(points)-center, axis=1).max() <= actual+1e-12
    circle = [(np.cos(t), np.sin(t)) for t in np.linspace(0, 2*np.pi, 70, endpoint=False)]
    with pytest.raises(ValueError, match='capacity'):
        smallest_circle_center(circle)
    with pytest.raises(ValueError):
        smallest_circle_center([])


def test_one_translation_reduces_bound_without_changing_source_or_default(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    ids = ordered_ids(graph, component)
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    base = baseline.generate(graph)
    prepared = prepare_author_terminal(base, graph, component, index.candidates(graph, component), AuthorTerminalEvidence(index))
    glyph, record = prepared.alternatives[0]
    duplicate = replace(index.sources[record['candidate']['sample_id']], sample_id='translation-test')
    index.sources[duplicate.sample_id] = duplicate
    moved_record = {**record, 'candidate': {**record['candidate'], 'sample_id': duplicate.sample_id},
        'transform': {**record['transform'], 'tx': record['transform']['tx']+.03, 'ty': record['transform']['ty']-.01}}
    moved, _ = source_component(base, ids, moved_record, index.sources)
    prepared.alternatives.append((moved, moved_record))
    original_snapshot = asdict(moved)
    repaired = translate_prepared_candidates(base, graph, ids, prepared, index.sources)
    output, metadata = repaired.alternatives[1]
    assert metadata['common_translation']['applied']
    np.testing.assert_allclose(metadata['common_translation']['proposed_delta'], [-.03, .01], atol=1e-12)
    assert not invariants(output, graph)
    for i in range(3):
        assert correspondence_bound(glyph_curves(glyph)[i], glyph_curves(output)[i])['maximum'] < 1e-12
        assert [p.pressure for p in output.strokes[i].points] == [p.pressure for p in moved.strokes[i].points]
    assert asdict(moved) == original_snapshot
    assert repaired.select(0)[0] is prepared.original
