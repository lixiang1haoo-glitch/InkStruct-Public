import copy
from pathlib import Path

import pytest
from test_component_generation import make_graph

from inkstruct.structures import StructureRepository
from inkstruct.v61_starter_collection import (
    coverage,
    freeze_split,
    project,
    public_pair,
    public_view,
    select,
)


def test_validation_is_deterministic_disjoint_and_order_independent():
    chars = list('天地玄黄宇宙洪荒日月盈昃辰宿列张')
    training, held = freeze_split(chars, 4)
    assert held == freeze_split(list(reversed(chars)), 4)[1]
    assert not set(training) & set(held)
    assert set(training) | set(held) == set(chars)


def test_nested_overlapping_evidence_is_not_double_counted_and_self_is_excluded():
    source, target = make_graph('沱', '也'), make_graph('池', '也')
    original = copy.deepcopy(source)
    duplicate = copy.deepcopy(source.components[-1])
    duplicate.component_id += ':duplicate-view'
    source.components.append(duplicate)
    args = {'池': target, '沱': original}
    a, weights, _, _ = project({'沱': source}, args)
    b, _, _, _ = project({'沱': original}, args)
    assert a['沱']['opportunities'] == b['沱']['opportunities']
    assert all(k.split('/')[1] != '沱' for k in a['沱']['opportunities'])
    result = coverage(a, ['沱'], args)
    assert result['component_opportunity_strokes'] == len(target.strokes)
    assert result['actual_usable_coverage'] is None
    assert all(not e['author_geometry_checked'] for e in a['沱']['evidence'])
    assert len(a['沱']['opportunities']) <= len(weights)


def test_lazy_selection_prefers_new_coverage_before_second_donor_and_nested_budgets():
    weights = {str(i): 1. for i in range(6)}
    candidates = {
        '甲': {'stroke_count': 4, 'opportunities': ['0', '1', '2']},
        '乙': {'stroke_count': 4, 'opportunities': ['0', '1', '2']},
        '丙': {'stroke_count': 4, 'opportunities': ['3', '4', '5']},
    }
    rows = select(candidates, weights, 3)
    assert set(rows[1]['new_opportunities']) == {'0', '1', '2'} or set(
        rows[1]['new_opportunities']) == {'3', '4', '5'}
    assert len(rows[0]['new_opportunities']) == len(rows[1]['new_opportunities']) == 3
    assert rows[2]['new_opportunities'] == []
    assert rows[:2] == select(candidates, weights, 2)


DB = Path('artifacts/full_library_20261010/inputs/characters.sqlite3')


@pytest.mark.skipif(not DB.exists(), reason='optional frozen public structure database')
def test_real_public_views_respect_no_split_on_both_sides_and_keep_normal_shi():
    repo = StructureRepository(DB)
    before = repo.get('群')
    for target in (False, True):
        view = public_view(repo, '群', target=target)
        yin = [n for n in view.components if n.canonical == '尹']
        assert yin and all(not n.children_ids for n in yin)
        assert not any(n.canonical == '尸' for n in view.components)
    assert repo.get('群') == before
    assert any(n.canonical == '尸' for n in public_view(repo, '炉').components)


@pytest.mark.skipif(not DB.exists(), reason='optional frozen public structure database')
def test_real_sheep_positional_variants_are_not_counted_as_direct_reuse():
    repo = StructureRepository(DB)
    source, target = public_view(repo, '羊'), public_view(repo, '羝', target=True)
    sn = next(n for n in source.components if n.canonical == '羊')
    tn = next(n for n in target.components if n.canonical == '羊')
    with pytest.raises(ValueError):
        public_pair(source, sn, target, tn)
