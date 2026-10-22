import copy
from types import SimpleNamespace as NS

import pytest

from inkstruct.positional_variants import check_positional_variants
from inkstruct.v62_exp import SemanticAuthorStrokeFallback, SemanticBatchStrokeFallback
from inkstruct.v62_semantics import check_content_variants, hook_compatibility, hook_form

HOOK = [(.2,.1),(.2,.75),(.23,.85),(.35,.9),(.65,.9),(.65,.7)]
SLANT = [(.2,.1),(.35,.45),(.5,.75),(.65,.9),(.65,.7)]
LIFT = [(.2,.1),(.2,.75),(.25,.85),(.4,.8),(.65,.55)]
V = [(.5,.2),(.5,.8)]
H = [(.1,.8),(.8,.8)]


@pytest.mark.parametrize('scale,tx,ty', [(1,0,0),(2,4,-2),(.3,-1,3)])
def test_hook_roles_are_scale_translation_invariant(scale,tx,ty):
    f=lambda p:[(x*scale+tx,y*scale+ty) for x,y in p]
    assert hook_form(f(HOOK))['form']=='vertical_bend_hook'
    assert hook_compatibility(f(HOOK),f(HOOK),f(HOOK))['accepted']
    assert not hook_compatibility(f(HOOK),f(SLANT),f(SLANT))['accepted']
    assert not hook_compatibility(f(HOOK),f(LIFT),f(LIFT))['accepted']


def stop_graph(last_two):
    curves=[V,[(.5,.4),(.8,.4)],*last_two]
    strokes=[NS(stroke_id=f's{i+1}',median=p) for i,p in enumerate(curves)]
    node=NS(component_id='stop',canonical='止',glyph_variant='止',role='bottom',stroke_ids=[s.stroke_id for s in strokes])
    return NS(strokes=strokes,components=[node]),node


@pytest.mark.parametrize('partial',[False,True])
def test_stop_variant_rejected_in_whole_and_nested_partial_components(partial):
    sg,sn=stop_graph(([ (.4,.4),(.1,.8) ],[(.1,.6),(.8,.9)]))
    tg,tn=stop_graph((V,H))
    if partial:
        sn=NS(component_id='part',canonical='上',glyph_variant='上',role='bottom',stroke_ids=['s1','s2','s4'])
        tn=copy.copy(sn)
    raw=[NS(points=s.median) for s in sg.strokes if s.stroke_id in sn.stroke_ids]
    before=copy.deepcopy(raw)
    assert check_positional_variants(sg,sn,tg,tn,raw)['accepted']
    assert not check_content_variants(sg,sn,tg,tn,raw)['accepted']
    assert [s.points for s in raw]==[s.points for s in before]


def test_correct_stop_and_natural_slant_remain_eligible():
    sg,sn=stop_graph(([(.5,.2),(.58,.8)],[(.1,.8),(.8,.68)]))
    tg,tn=stop_graph((V,H))
    assert check_content_variants(sg,sn,tg,tn,[NS(points=s.median) for s in sg.strokes])['accepted']


def fallback_fixture():
    graph=NS(character='靶',components=[],strokes=[NS(stroke_id='s1',median=HOOK)])
    source=NS(standard_stroke_id='s1',points=HOOK,pressure=[.4]*len(HOOK),
              t_ms=list(range(len(HOOK))),confidence=.9)
    sample=NS(sample_id='source',character='供',source_sha256='hash',stroke_order_status='declared',strokes=[source])
    profile=NS(trajectory_schema='source_trajectory_v1',build_identity={'structure_sha256':'db'},source_trajectories={'source':sample})
    repo=NS(content_sha256=lambda:'db',get=lambda _:graph)
    return graph,profile,repo


def test_serial_batch_exact_source_and_no_pool_mutation():
    graph,profile,repo=fallback_fixture()
    before=copy.deepcopy(profile)
    results=[]
    for cls in (SemanticAuthorStrokeFallback,SemanticBatchStrokeFallback):
        engine=cls(profile,repo)
        pool=copy.deepcopy(engine.pool)
        piece,ev=engine.select(graph,0,[HOOK],[HOOK])
        assert piece and ev['character']=='供'
        assert piece['pressure']==profile.source_trajectories['source'].strokes[0].pressure
        assert engine.pool==pool
        results.append((piece,ev))
    assert results[0]==results[1]
    assert profile==before


@pytest.mark.parametrize('cls',[SemanticAuthorStrokeFallback,SemanticBatchStrokeFallback])
def test_no_admitted_source_is_an_explicit_gap(cls):
    graph,profile,repo=fallback_fixture()
    profile.source_trajectories['source'].character='靶'
    piece,ev=cls(profile,repo).select(graph,0,[HOOK],[HOOK])
    assert piece is None and ev['reason']=='no admitted author stroke'
    assert ev['rejections']['same character']==1


def test_unregistered_family_remains_explicitly_out_of_scope():
    sg,sn=stop_graph((V,H));tg,tn=stop_graph((V,H))
    sn.canonical=sn.glyph_variant=tn.canonical=tn.glyph_variant='木'
    ev=check_content_variants(sg,sn,tg,tn,[NS(points=s.median) for s in sg.strokes])
    assert ev['accepted'] and not ev['checks'] and 'unverified' in ev['scope']
