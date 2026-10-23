from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.counterfactual_layout_risk import CounterfactualLayoutRiskGate
from inkstruct.trajectory_layout_risk import TrajectoryLayoutRiskGate, stroke_geometry_features


def test_geometry_features_are_inference_only_and_preserve_source_fields(tmp_path):
    graphs, _, baseline, _, _ = fixture(tmp_path)
    base = baseline.generate(graphs['池'])
    proposal = deepcopy(base)
    ids = [s.standard_stroke_id for s in proposal.strokes[:3]]
    for stroke in proposal.strokes[:3]:
        for p in stroke.points:
            p.x += .01
    snapshots = asdict(base), asdict(proposal)
    features, evidence = stroke_geometry_features(base, base, proposal, ids)
    assert len(features) == 24 and set(evidence) == set(ids)
    np.testing.assert_allclose(features[:12], 0., atol=1e-6)
    assert features[14] == pytest.approx(.2)  # Mean endpoint increment / 0.05.
    assert features[17] == pytest.approx(.2)  # Mean startpoint increment / 0.05.
    assert (asdict(base), asdict(proposal)) == snapshots
    for bad in ([], [ids[0], ids[0]], ['unknown']):
        with pytest.raises(ValueError):
            stroke_geometry_features(base, base, proposal, bad)
    broken = deepcopy(proposal)
    broken.strokes[0].standard_stroke_id = 'unknown'
    with pytest.raises(ValueError):
        stroke_geometry_features(base, base, broken, ids)


def records():
    return [{'writer': 'writer', 'character': chr(0x4e00+i), 'component_id': 'c0',
             'proposal_id': f'p{move}', 'features': [i*.01]*22+[move]*24,
             'safe_benefit': move == 0, 'geometry_ratio': .9 if move == 0 else 1.1}
            for i in range(5) for move in (0, 1)]


def test_zero_geometry_weight_exactly_matches_layout_control_and_blocks_are_separate():
    rows = records()
    legacy = CounterfactualLayoutRiskGate([{**e, 'features': e['features'][:22]} for e in rows])
    new = TrajectoryLayoutRiskGate(rows)
    a = legacy.predict('writer', '池', [.02]*22, threshold=1.)
    b = new.predict('writer', '池', [.02]*22+[1]*24, threshold=1., geometry_weight=0.)
    for key in ('accepted', 'safe_fraction', 'mean_geometry_ratio'):
        assert a[key] == b[key]
    assert [(e['writer'], e['character'], e['proposal_id'], e['distance']) for e in a['neighbors']] == [
        (e['writer'], e['character'], e['proposal_id'], e['distance']) for e in b['neighbors']]
    assert not new.predict('writer', '池', [.02]*22+[1]*24, threshold=1., geometry_weight=1.)['accepted']
    assert new.predict('writer', '池', [.02]*22+[0]*24, threshold=1., geometry_weight=1.)['accepted']
    for bad in (-.1, 1.1, float('nan')):
        with pytest.raises(ValueError):
            new.predict('writer', '池', [.02]*22+[0]*24, geometry_weight=bad)


def test_query_character_is_excluded_before_both_feature_scales():
    rows = records()
    query = [.02]*22+[0]*24
    original = TrajectoryLayoutRiskGate(rows).predict('writer', '池', query)
    poison = {**rows[0], 'character': '池', 'features': [1e6]*46}
    assert TrajectoryLayoutRiskGate(rows+[poison]).predict('writer', '池', query) == original
    assert len({(e['writer'], e['character']) for e in original['neighbors']}) == 5
