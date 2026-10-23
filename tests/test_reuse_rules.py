import copy
from types import SimpleNamespace as NS

import pytest
from test_pipeline import make_structure

from inkstruct.reuse_rules import ReuseRules
from inkstruct.schemas import ComponentNode
from inkstruct.v61_candidate_expansion import CandidateExpansionGenerator, ExpansionPolicy


def graph(parent='尹'):
    return NS(character='群',components=[
        NS(component_id='root',canonical='君',children_ids=['yin','mouth'],stroke_ids=list('1234567')),
        NS(component_id='yin',canonical=parent,children_ids=['line','body'],stroke_ids=list('1234')),
        NS(component_id='line',canonical='一',children_ids=[],stroke_ids=['2']),
        NS(component_id='body',canonical='尸',children_ids=['deep'],stroke_ids=list('134')),
        NS(component_id='deep',canonical='丿',children_ids=[],stroke_ids=['4']),
        NS(component_id='mouth',canonical='口',children_ids=[],stroke_ids=list('567'))])


def test_rule_only_for_exact_reviewed_split_and_keeps_original():
    g=graph();original=copy.deepcopy(g)
    rules=ReuseRules(True)
    view,log=rules.view(g)
    assert g==original and len(log)==1
    assert {n.component_id for n in view.components}=={'root','yin','mouth'}
    for ids in ('134','2','4'):
        assert not rules.check(g,ids,side='target')['accepted']
    for ids in ('1234','1234567','567'):
        assert rules.check(g,ids,side='source')['accepted']
    assert rules.check(graph('户'),'134',side='source')['accepted']
    other_split=graph();other_split.components[2].canonical='丶'
    assert rules.check(other_split,'134',side='source')['accepted']
    disabled=ReuseRules(False)
    assert disabled.view(g)==(g,[]) and disabled.check(g,'134',side='target')['accepted']


def fake_engine(source_graph=None,target_graph=None):
    engine=object.__new__(CandidateExpansionGenerator)
    engine.reuse_rules=ReuseRules(True);engine.rule_log=[]
    engine.rule_graph=lambda c,side: (source_graph or graph('户')) if side=='source' else (target_graph or graph())
    return engine


def proposal(ids='134',source_ids='134'):
    return NS(ids=tuple(ids),candidate={'character':'炉','stroke_ids':list(source_ids)})


def test_both_sides_checked_and_inherited_plan_cannot_bypass_emit():
    ctx=NS(character='群')
    p=proposal();engine=fake_engine()
    assert engine.reuse_evidence(ctx,p)['side']=='target'
    kept,log=engine.filter_plan(ctx,{'stale-node-id':p})
    assert not kept and log[0]['reuse_rule']['rule']['id']=='yin_no_split_yi_shi_v1'
    with pytest.raises(ValueError,match='forbidden'):
        engine.emit(ctx,{'stale-node-id':p})
    source_bad=fake_engine(source_graph=graph(),target_graph=graph('户'))
    assert source_bad.reuse_evidence(ctx,p)['side']=='source'
    allowed=proposal('1234','1234')
    assert engine.reuse_evidence(ctx,allowed)['accepted']


def test_even_disabled_expansion_arm_filters_inherited_forbidden_plan():
    engine=fake_engine();p=proposal();ctx=NS(character='群')
    engine.emit=lambda context,plan: ('emitted',list(plan))
    _,glyph,plan,log=engine.extend(ctx,{'old':p},ExpansionPolicy())
    assert plan=={} and glyph==('emitted',[]) and log


def test_attempt_rejects_before_geometry_or_mapping_can_admit():
    engine=fake_engine();ctx=NS(character='群')
    plan,log=engine.attempt(ctx,{},proposal(),source_aware=True)
    assert plan=={} and not log['accepted'] and log['reuse_rule']['side']=='target'


def test_dynamic_expansion_and_reexpansion_cannot_reintroduce_forbidden_children(tmp_path):
    host=make_structure(tmp_path).get('十')
    independent=copy.deepcopy(host)
    independent.character='尹'
    root=independent.components[0]
    root.canonical='尹';root.glyph_variant='尹';root.children_ids=['a','b']
    for i,name in enumerate(('一','尸')):
        s=independent.strokes[i]
        independent.components.append(ComponentNode(('a','b')[i],f'root.{i}',name,name,
            'top',root.component_id,[],[s.stroke_id],s.bbox,None,1.))
    host.character='甲';host.components[0].children_ids=['host']
    host.components.append(ComponentNode('host','root.0','尹','尹','left',host.components[0].component_id,
                                         [],[s.stroke_id for s in host.strokes],root.bbox,None,1.))
    before=copy.deepcopy(host)
    repo=NS(get=lambda c:independent)
    engine=object.__new__(CandidateExpansionGenerator);engine.reuse_rules=ReuseRules(True)
    for _ in range(3):
        host,log=engine.expanded(host,repo)
        assert len(host.components)==2 and host.components[1].children_ids==[]
        assert any(r.get('version')=='author_reuse_no_split_v1' for r in log)
    assert host.strokes==before.strokes and before.components[1].children_ids==[]
    engine.reuse_rules=ReuseRules(False)
    expanded,_=engine.expanded(host,repo)
    assert len(expanded.components)>len(host.components)
