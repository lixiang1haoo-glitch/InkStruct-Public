import copy
from types import SimpleNamespace

from test_component_generation import make_graph
from test_source_generation_entry import fixture

from inkstruct.recommend import greedy_marginal_order
from inkstruct.v61_collection import (
    audit_targets,
    freeze_validation,
    projected_candidates,
    select_budget,
)
from inkstruct.v61_exp import V61ExpGenerator


def test_shared_greedy_matches_full_recalculation():
    features={'甲':{'a','b'},'乙':{'b','c'},'丙':{'c'},'丁':{'d'}}
    covered=set()
    gain=lambda c: len(features[c]-covered)
    actual=[]
    for c in greedy_marginal_order(features,gain,ord):
        actual.append(c);covered.update(features[c])
    covered=set();remaining=set(features);expected=[]
    while remaining:
        c=min(remaining,key=lambda c:(-gain(c),ord(c)))
        if not gain(c):break
        expected.append(c);covered.update(features[c]);remaining.remove(c)
    assert actual==expected


def test_budget_counts_distinct_donor_characters_and_not_actual_acquisitions():
    slots={'x':{'safe_donor_characters':[],'stroke_count':3},
           'y':{'safe_donor_characters':['旧'],'stroke_count':2}}
    candidates={c:{'character':c,'stroke_count':5,'common_list':True,'opportunities':ops}
                for c,ops in [('甲',{'x':{}}),('乙',{'x':{},'y':{}}),('丙',{'x':{}})]}
    p=select_budget(candidates,slots,budget=2)
    assert len(p['recommendations'])==2
    assert p['projected_distinct_donors_if_all_admitted']=={'x':2,'y':2}
    assert p['actual_new_usable_sources']==0
    assert p['projected_first_source_slots']==['x']
    assert all(r['repeats']==2 for r in p['recommendations'])


def test_prospective_validation_uses_public_metadata_and_excludes_existing_groups():
    graphs={c:make_graph(c,'也') for c in '池沱河江沪'}
    repo=SimpleNamespace(get=graphs.__getitem__)
    held=freeze_validation(repo,{'池'},['沱'],list('池沱河江沪'),2)
    assert len(held)==2 and not set(held)&{'池','沱'}
    assert held==freeze_validation(repo,{'池'},['沱'],list('沪江河沱池'),2)


def test_current_admission_is_real_and_projection_never_promotes_uncollected_sources(tmp_path):
    graphs,repo,_,profile,_=fixture(tmp_path)
    graphs['沾']=make_graph('沾','也')
    repo.iter_graphs=lambda:iter(graphs.values())
    engine=V61ExpGenerator(profile,repo,repo)
    slots,glyphs=audit_targets(engine,['池'])
    assert glyphs['池']['actual_source_strokes']>0
    assert all(s['safe_donor_characters']==['沱'] for s in slots.values())
    projected=projected_candidates(engine,slots,{'池','沱'},{'池'}, {'沾'})
    assert set(projected)=={'沾'}
    assert '沾' not in {s.character for s in profile.source_trajectories.values()}
    assert not projected_candidates(engine,slots,{'池','沱'},{'池','沾'},{'沾'})
    assert all('assumption' in x for x in projected['沾']['opportunities'].values())
    # Same canonical at another position is not admitted merely for coverage.
    right={k:s for k,s in slots.items() if s['canonical']=='也'}
    other=copy.deepcopy(graphs['沾'])
    for n in other.components:
        if n.canonical=='也':n.role='top'
    engine.v6.index.graphs['沾']=other
    assert not projected_candidates(engine,right,{'池','沱'},{'池'}, {'沾'})
