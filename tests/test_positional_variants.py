import copy
from types import SimpleNamespace as NS

import pytest

from inkstruct.positional_variants import check_positional_variants, key_form
from inkstruct.v61_candidate_expansion import CandidateExpansionGenerator


def graph(family, count, last, role):
    ids = [f's{i+1}' for i in range(count)]
    strokes = [NS(stroke_id=k, median=[(0., .1*i), (.4, .1*i)]) for i,k in enumerate(ids)]
    strokes[-1].median = last
    node = NS(component_id='c', canonical=family, glyph_variant=family, role=role, stroke_ids=ids)
    return NS(strokes=strokes, components=[node]), node


def evidence(family, count, source, target, author=None):
    sg,sn = graph(family,count,source,'middle')
    tg,tn = graph(family,count,target,'left')
    raw = [NS(points=copy.deepcopy(s.median)) for s in sg.strokes]
    raw[-1].points = copy.deepcopy(author if author is not None else source)
    old = copy.deepcopy([s.points for s in raw])
    result = check_positional_variants(sg,sn,tg,tn,raw)
    assert [s.points for s in raw] == old
    return result


VERTICAL = [(0.,0.), (0.,1.)]
FALLING = [(0.,0.), (-.5,1.)]
HORIZONTAL = [(0.,0.), (1.,-.06)]
RISING = [(0.,0.), (1.,-.5)]


def test_sheep_vertical_source_rejected_and_falling_source_accepted():
    rejected = evidence('羊',6,VERTICAL,FALLING)
    assert not rejected['accepted']
    assert rejected['checks'][0]['source_reference']['form'] == 'vertical'
    assert rejected['checks'][0]['target_reference']['form'] == 'left_falling'
    assert evidence('羊',6,FALLING,FALLING)['accepted']
    assert evidence('羊',6,VERTICAL,VERTICAL)['accepted']
    assert not evidence('羊',6,FALLING,FALLING,VERTICAL)['accepted']


@pytest.mark.parametrize(('family','count'), [('土',3),('王',4),('子',3)])
def test_horizontal_rising_positional_variants(family,count):
    assert not evidence(family,count,HORIZONTAL,RISING)['accepted']
    assert evidence(family,count,RISING,RISING)['accepted']
    # A real author may already use the target variant in the source context.
    assert evidence(family,count,HORIZONTAL,RISING,RISING)['accepted']


def test_natural_slant_ambiguous_forms_and_unregistered_families_are_not_hard_rejected():
    assert evidence('土',3,HORIZONTAL,HORIZONTAL,[(0.,0.),(1.,-.22)])['accepted']
    assert evidence('木',4,HORIZONTAL,RISING)['checks'] == []
    unknown = evidence('土',3,HORIZONTAL,[(0.,0.),(1.,-.22)])
    assert unknown['accepted'] and unknown['checks'][0]['status'] == 'review'


def test_form_is_translation_scale_invariant_and_handles_entry_and_short_hook():
    points = [(.1,0.),(0.,.05),(0.,1.),(-.025,.99)]
    assert key_form(points)['form'] == 'vertical'
    assert key_form([(x*3+10,y*3-5) for x,y in points])['form'] == 'vertical'


def test_admission_blocks_even_if_candidate_would_pass_axis_and_collision_gates():
    engine = object.__new__(CandidateExpansionGenerator)
    engine.variant_checks = True
    engine.variant_evidence = lambda ctx,p: evidence('羊',6,VERTICAL,FALLING)
    plan = {'keep':'unchanged'}
    output, diagnostic = engine.attempt(None,plan,NS(candidate={'sample_id':'bad'}),source_aware=True)
    assert output is plan and not diagnostic['accepted']
    assert diagnostic['fallback_reason'].startswith('positional key-stroke mismatch')


def test_car_vertical_to_rising_is_not_just_a_scale_change():
    assert not evidence('车',4,VERTICAL,RISING)['accepted']


def test_repair_scope_cannot_reselect_unaffected_components():
    engine = object.__new__(CandidateExpansionGenerator)
    engine.variant_checks = True
    engine.variant_evidence = lambda ctx,p: {'accepted':p.component_id != 'bad'}
    plan={'bad':NS(component_id='bad',ids=('s1','s2')), 'good':NS(component_id='good',ids=('s3',))}
    calls=[]
    engine.extend = lambda ctx,p,policy,**kwargs: calls.append(kwargs['target_scope'])
    engine.repair(None,plan,None)
    assert calls == [{'s1','s2'}]
