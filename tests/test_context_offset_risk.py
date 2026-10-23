from copy import deepcopy

import numpy as np
import pytest
from test_grouped_logistic_risk import records

from inkstruct.context_offset_risk import ContextRiskGate, fit_offset
from inkstruct.grouped_logistic_risk import GroupedLogisticRiskGate


def examples():
    return [{**r, 'context': 'C'+str(int(r['safe_benefit']))} for r in records()]


def test_context_offsets_learn_residuals_shrink_and_back_off_unknowns():
    rows = examples()
    before = deepcopy(rows)
    weak = fit_offset(rows, np.zeros(len(rows)), mode='component', regularization=.001)
    strong = fit_offset(rows, np.zeros(len(rows)), mode='component', regularization=1.)
    assert weak.offset([{'writer': 'a', 'context': 'C1'}])[0] > 2
    assert weak.offset([{'writer': 'a', 'context': 'C0'}])[0] < -2
    assert np.linalg.norm(strong.coefficients) < np.linalg.norm(weak.coefficients)
    assert weak.offset([{'writer': 'new', 'context': 'new'}])[0] == 0
    assert rows == before
    duplicate_group = [r for r in rows if r['writer'] == 'a' and r['character'] == rows[0]['character']]
    duplicated = fit_offset(rows+duplicate_group, np.zeros(len(rows)+len(duplicate_group)), mode='component', regularization=.001)
    np.testing.assert_allclose(duplicated.coefficients, weak.coefficients, atol=1e-8)


def test_query_character_removed_before_context_vocabulary_and_numeric_fit():
    rows = examples()
    query = rows[0]['character']
    a = ContextRiskGate(rows, mode='hierarchical', regularization=.01)
    result = a.predict('a', query, 'C1', [0.]*22+[1.]*24)
    poisoned = [{**r, 'features': [1e6]*46, 'context': 'poison', 'safe_benefit': True} if r['character'] == query else r for r in rows]
    b = ContextRiskGate(poisoned, mode='hierarchical', regularization=.01)
    assert b.predict('a', query, 'C1', [0.]*22+[1.]*24) == result
    assert not any('poison' in key for key in b.cache[query][1].vocabulary)
    assert result['accepted']
    assert len(b.cache[query][2]) == len(rows)-4


def test_base_mode_reproduces_frozen_numeric_gate_and_invalid_input_fails():
    rows = examples()
    old = GroupedLogisticRiskGate(rows, view='combined', regularization=.1)
    new = ContextRiskGate(rows)
    x = [0.]*22+[1.]*24
    a, b = old.predict('池', x), new.predict('a', '池', 'C1', x)
    assert a['score'] == b['score'] and a['accepted'] == b['accepted']
    with pytest.raises(ValueError):
        ContextRiskGate(rows+[rows[0]])
    for bad in (0, -1, float('nan')):
        with pytest.raises(ValueError):
            fit_offset(rows, np.zeros(len(rows)), mode='author', regularization=bad)
    with pytest.raises(ValueError):
        fit_offset(rows, [float('nan')]*len(rows), mode='author', regularization=.1)
