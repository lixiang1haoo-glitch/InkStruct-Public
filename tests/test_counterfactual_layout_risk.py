import pytest

from inkstruct.counterfactual_layout_risk import CounterfactualLayoutRiskGate


def test_nearest_trial_per_character_controls_risk_without_extra_votes():
    records = [{'writer': 'writer', 'character': chr(0x4e00+i), 'component_id': 'c0',
                'proposal_id': f'public_{move}', 'features': [move]*22,
                'safe_benefit': move == 0, 'geometry_ratio': .9 if move == 0 else 1.1}
               for i in range(5) for move in (0, 1)]
    gate = CounterfactualLayoutRiskGate(records)
    small = gate.predict('writer', '池', [0]*22, threshold=1.)
    large = gate.predict('writer', '池', [1]*22, threshold=1.)
    assert small['accepted'] and not large['accepted']
    assert small['safe_fraction'] == 1. and large['safe_fraction'] == 0.
    assert len(small['neighbors']) == len(large['neighbors']) == 5
    assert small['component_reference_count'] == 10 and small['reference_count'] == 5
    assert CounterfactualLayoutRiskGate(list(reversed(records))).predict('writer', '池', [0]*22, threshold=1.) == small
    assert not gate.predict('writer', chr(0x4e00), [0]*22)['available']
    with pytest.raises(ValueError, match='duplicate'):
        CounterfactualLayoutRiskGate(records+[records[0]])
