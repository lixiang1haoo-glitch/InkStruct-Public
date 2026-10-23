from copy import deepcopy

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.contextual_trajectory import choose_component
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.layout_risk import LayoutRiskGate, move_features, training_fold


def examples():
    return [{'writer': 'writer', 'character': chr(0x4e00+i), 'features': [i*.01]*22,
             'safe_benefit': i < 6, 'geometry_ratio': .9 if i < 6 else 1.1} for i in range(8)]


def test_gate_excludes_query_before_scaling_and_preserves_grouped_votes():
    records = examples()
    result = LayoutRiskGate(records).predict('writer', '池', [.02]*22, threshold=.6)
    assert result['accepted'] and result['safe_fraction'] == .75
    assert not LayoutRiskGate(records).predict('writer', '池', [.02]*22, threshold=.8)['accepted']
    poison = {'writer': 'writer', 'character': '池', 'features': [1000]*22,
              'safe_benefit': False, 'geometry_ratio': 1000}
    assert LayoutRiskGate(records+[poison]).predict('writer', '池', [.02]*22, threshold=.6) == result
    with pytest.raises(ValueError, match='one grouped'):
        LayoutRiskGate(records+[records[0]])


def test_gate_abstains_outside_support_and_author_scope():
    gate = LayoutRiskGate(examples())
    assert not gate.predict('other', '池', [.02]*22)['available']
    assert gate.predict('other', '池', [.02]*22, scope='pooled', threshold=.6)['accepted']
    assert not gate.predict('writer', '池', [100]*22)['available']
    with pytest.raises(ValueError):
        gate.predict('writer', '池', [float('nan')]*22)
    assert {training_fold('池') for _ in range(10)} == {training_fold('池')}
    assert {training_fold(chr(i)) for i in range(0x4e00, 0x4e80)} == {0, 1, 2}


def test_neighbor_features_change_without_changing_component_or_public_features(tmp_path):
    graphs, repository, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repository, allowed_characters={'沱'})
    base = baseline.generate(graph)
    original, _ = choose_component(base, graph, ordered_ids(graph, component), index.candidates(graph, component), index.sources)
    prediction = {'tier': 'exact'}
    band = {'distance_before': 7., 'radius': 5., 'effective_strength': .2}
    before = move_features(graph, component, original, original, prediction, band)
    shifted = deepcopy(original)
    for stroke in shifted.strokes:
        if stroke.standard_stroke_id not in component.stroke_ids:
            for point in stroke.points:
                point.x += .01
    after = move_features(graph, component, shifted, shifted, prediction, band)
    assert len(before) == len(after) == 22 and np.isfinite(after).all()
    np.testing.assert_array_equal(before[:14], after[:14])
    assert not np.allclose(before[14:18], after[14:18])
    np.testing.assert_array_equal(before[18:], after[18:])
