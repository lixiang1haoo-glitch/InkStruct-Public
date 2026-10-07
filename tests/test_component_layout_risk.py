import pytest

from inkstruct.component_layout_risk import ComponentLayoutRiskGate
from inkstruct.layout_risk import LayoutRiskGate


def records():
    return [{'writer': 'writer', 'character': chr(0x4e00+i), 'component_id': 'c0',
             'features': [i*.01]*22, 'safe_benefit': i > 0,
             'geometry_ratio': 1.1 if i == 0 else .9} for i in range(5)]


def test_one_character_with_many_components_cannot_cast_more_votes():
    rows = records()
    control = ComponentLayoutRiskGate(rows).predict('writer', '池', [.02]*22, threshold=.8)
    more = rows+[{**rows[0], 'component_id': f'c{i}'} for i in range(1, 30)]
    result = ComponentLayoutRiskGate(more).predict('writer', '池', [.02]*22, threshold=.8)
    assert result['accepted'] == control['accepted'] is True
    assert result['safe_fraction'] == control['safe_fraction'] == .8
    assert result['reference_count'] == len(result['neighbors']) == 5
    assert result['neighbors'] == control['neighbors']
    assert result['component_reference_count'] == 34
    with pytest.raises(ValueError, match='duplicate'):
        ComponentLayoutRiskGate(rows+[rows[0]])


def test_all_query_components_excluded_before_scaling_and_single_control_matches():
    rows = records()
    original = LayoutRiskGate(rows).predict('writer', '池', [.02]*22, threshold=.8)
    result = ComponentLayoutRiskGate(rows).predict('writer', '池', [.02]*22, threshold=.8)
    for key in ('accepted', 'available', 'safe_fraction', 'mean_geometry_ratio', 'neighbors'):
        assert result[key] == original[key]
    poison = [{**rows[0], 'character': '池', 'component_id': f'c{i}', 'features': [1000]*22} for i in range(10)]
    assert ComponentLayoutRiskGate(rows+poison).predict('writer', '池', [.02]*22, threshold=.8) == result
    # Many observations from a single author-character cannot satisfy five groups.
    sparse = [rows[0]]+[{**rows[0], 'component_id': f'c{i}'} for i in range(1, 20)]
    assert not ComponentLayoutRiskGate(sparse).predict('writer', '池', [.02]*22)['available']
