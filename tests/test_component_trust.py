from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.author_terminal_context import AuthorTerminalEvidence, prepare_author_terminal
from inkstruct.component_trust import (
    correspondence_bound,
    parameterized_curve,
    prepare_component_trust,
)
from inkstruct.exemplar_index import ExemplarIndex
from inkstruct.trajectory_experiment import point_distances


def test_continuous_bound_is_density_independent_includes_endpoints_and_interior_corners():
    line = [(0., 0.), (1., 0.)]
    dense = [(float(x), 0.) for x in np.linspace(0, 1, 57)]
    assert correspondence_bound(line, dense)['maximum'] < 1e-12
    shifted = [(x, .03) for x, _ in dense]
    assert correspondence_bound(line, shifted)['maximum'] == pytest.approx(.03)
    # Equal endpoints do not hide a short interior excursion between grid points.
    short_hook = [(0., 0.), (.987, 0.), (.987, .008), (.987, 0.), (1., 0.)]
    bound = correspondence_bound(line, short_hook)
    assert bound['maximum'] >= .008
    assert bound['start_displacement'] == bound['end_displacement'] == 0
    assert 0 < bound['worst_arc_fraction'] < 1
    grid = np.linspace(0, 1, 10001)
    lp, lc = parameterized_curve(line)
    rp, rc = parameterized_curve(short_hook)
    left = np.column_stack([np.interp(grid, lp, lc[:, i]) for i in range(2)])
    right = np.column_stack([np.interp(grid, rp, rc[:, i]) for i in range(2)])
    maximum = np.linalg.norm(left-right, axis=1).max()
    assert maximum <= bound['maximum']+1e-12 and bound['maximum']-maximum < .0002
    assert max(point_distances(left, short_hook).max(), point_distances(right, line).max()) <= bound['maximum']+1e-12


def test_degenerate_curves_have_a_defined_bound_but_invalid_inputs_do_not():
    assert correspondence_bound([(0, 0)]*4, [(0, 1)]*2)['maximum'] == 1
    assert correspondence_bound([(0, 0)]*2, [(0, 0), (0, 2)])['maximum'] == 2
    for points in ([], [(0, 0)], [[0, 0, 1], [0, 1, 2]], [(float('nan'), 0), (1, 1)]):
        with pytest.raises(ValueError):
            correspondence_bound(points, [(0, 0), (1, 1)])


def test_guard_preserves_exact_off_zero_and_complete_candidate_selection(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    prepared = prepare_author_terminal(baseline.generate(graph), graph, component,
        index.candidates(graph, component), AuthorTerminalEvidence(index))
    old, record = prepared.alternatives[0]
    moved = deepcopy(old)
    for stroke in moved.strokes[:3]:
        for point in stroke.points:
            point.x += .03
    first = {**record, 'score': .02, 'author_terminal_penalties': {'author': 1., 'public_residual': 1.}}
    second = {**record, 'candidate': {**record['candidate'], 'sample_id': 'synthetic-choice'},
              'score': .025, 'author_terminal_penalties': {'author': 0., 'public_residual': 0.}}
    prepared.alternatives = [(old, first), (moved, second)]
    prepared.common_supported_strokes = {'author': [0], 'public_residual': [0]}
    protected = prepare_component_trust(prepared, ['s1', 's2', 's3'])
    assert protected.select(None)[0] is moved
    assert protected.select(None)[1] == prepared.select(.04, 'author')[1]
    assert protected.select(0)[0] is prepared.original
    assert protected.select(.02)[0] is old
    assert protected.select(.031)[0] is moved
    assert protected.select(.031)[1]['local_trust']['selected_bound']['maximum'] == pytest.approx(.03)
    # The guard only returns an existing complete glyph; it never edits points.
    snapshot = asdict(moved)
    protected.select(.025)
    assert asdict(moved) == snapshot
    for radius in (-1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            protected.select(radius)
    with pytest.raises(ValueError):
        protected.select(.01, mode='target')
    with pytest.raises(ValueError):
        prepare_component_trust(prepared, ['s1', 's1'])
