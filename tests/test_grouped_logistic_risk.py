from copy import deepcopy

import numpy as np
import pytest

from inkstruct.grouped_logistic_risk import (
    GroupedLogisticRiskGate,
    fit_grouped,
    group_weights,
    meta_fold,
    validation_cells,
)
from inkstruct.layout_risk import training_fold


def records(n=60):
    return [{'writer': w, 'character': chr(0x4e00+i), 'component_id': 'c', 'proposal_id': str(j),
             'features': [0.]*22+[float(i % 2)]*24, 'safe_benefit': bool(i % 2),
             'fold': training_fold(chr(0x4e00+i))}
            for i in range(n) for w in ('a', 'b') for j in range(2)]


def test_weighted_constant_control_and_group_replication():
    rows = records()
    model = fit_grouped(rows, view='layout')
    np.testing.assert_allclose(model.predict([r['features'] for r in rows]), .5, atol=1e-8)
    model = fit_grouped(rows)
    duplicate_group = [r for r in rows if r['writer'] == 'a' and r['character'] == rows[0]['character']]
    duplicated = fit_grouped(rows+duplicate_group*9)
    np.testing.assert_allclose(model.coefficients, duplicated.coefficients, atol=1e-7)
    assert group_weights(rows).sum() == pytest.approx(1.)
    assert model.gradient_max < 1e-6


def test_geometry_signal_is_learned_without_changing_inputs():
    rows = records()
    old = deepcopy(rows)
    model = fit_grouped(rows, view='geometry', regularization=.001)
    scores = model.predict([r['features'] for r in rows])
    assert scores.min() < .05 and scores.max() > .95
    assert rows == old
    for reg in (0, -1, float('nan')):
        with pytest.raises(ValueError):
            fit_grouped(rows, regularization=reg)
    with pytest.raises(ValueError):
        model.predict([[float('nan')]*46])
    with pytest.raises(ValueError):
        fit_grouped([{**rows[0], 'safe_benefit': 2}])


def test_validation_is_within_generation_fold_and_groups_all_authors_and_proposals():
    rows = records()
    seen = []
    for generation, heldout, train, valid in validation_cells(rows):
        assert {r['fold'] for r in train+valid} == {generation}
        assert not {r['character'] for r in train} & {r['character'] for r in valid}
        assert all(meta_fold(r['character']) == heldout for r in valid)
        seen += [(r['writer'], r['character'], r['proposal_id']) for r in valid]
    assert len(set(seen)) == len(seen) == len(rows)


def test_query_character_excluded_before_scaling_fitting_and_duplicates_rejected():
    rows = records()
    query = chr(0x4e00)
    gate = GroupedLogisticRiskGate(rows, view='combined', regularization=.01)
    result = gate.predict(query, [0.]*22+[1.]*24)
    poisoned = [{**r, 'features': [1e6]*46, 'safe_benefit': True} if r['character'] == query else r for r in rows]
    assert GroupedLogisticRiskGate(poisoned, view='combined', regularization=.01).predict(query, [0.]*22+[1.]*24) == result
    assert result['training_rows'] == len(rows)-4 and result['accepted']
    assert gate.predict(query, [0.]*46)['accepted'] is False
    with pytest.raises(ValueError):
        GroupedLogisticRiskGate(rows+[rows[0]], view='layout', regularization=.1)
    with pytest.raises(ValueError):
        gate.predict(query, [0.]*46, threshold=float('nan'))
