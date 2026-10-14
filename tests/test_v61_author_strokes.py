from types import SimpleNamespace as NS

import pytest

from inkstruct.schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke
from inkstruct.trajectory_experiment import assemble
from inkstruct.v61_author_strokes import (
    AuthorStrokeFallback,
    pair_changes,
    require_author_only,
    retain_source_relationships,
    stroke_class,
    valid_source,
)


def fixture(character='供'):
    points = [(.5,.1),(.48,.3),(.35,.5),(.2,.7)]
    source = NS(standard_stroke_id='s1', points=points, pressure=[.1,.4,.8,.2],
                t_ms=[500,510,540,580], confidence=.9)
    graph = NS(character='靶',strokes=[NS(stroke_id='s1',median=points)])
    sample = NS(character=character,sample_id='sample',source_sha256='hash',
                stroke_order_status='declared',strokes=[source])
    repo = NS(content_sha256=lambda:'version',get=lambda c:graph)
    profile = NS(trajectory_schema='source_trajectory_v1',build_identity={'structure_sha256':'version'},
                 source_trajectories={'sample':sample})
    return source,graph,profile,repo


def test_pie_distinct_from_vertical_and_hook():
    assert stroke_class([(.5,0),(.5,.4),(.2,.8)]) == 'pie'
    assert stroke_class([(.5,0),(.5,.8)]) == 'shu'
    assert stroke_class([(.5,0),(.5,.8),(.2,.7)]) != 'pie'


def test_mapping_version_and_mapping_confidence_fail_closed():
    source,_graph,profile,repo=fixture()
    profile.build_identity['structure_sha256']='wrong'
    with pytest.raises(ValueError,match='version'):
        AuthorStrokeFallback(profile,repo)
    profile.build_identity['structure_sha256']='version'
    source.confidence=.4
    assert not AuthorStrokeFallback(profile,repo).pool


def test_same_character_all_repeats_are_excluded():
    source,graph,profile,repo=fixture('靶')
    engine=AuthorStrokeFallback(profile,repo)
    selected,log=engine.select(graph,0,[source.points],[source.points])
    assert selected is None and log['rejections']['same character']==1


def test_selection_and_assembly_preserve_full_source_and_pen_timing():
    source,graph,profile,repo=fixture()
    selected,log=AuthorStrokeFallback(profile,repo).select(graph,0,[source.points],[source.points])
    assert selected and log['transform']['sx']==log['transform']['sy']
    stroke=GeneratedStroke('s1',1,1.,[GeneratedPoint(0,0,0,.5,'down'),GeneratedPoint(1,1,10,.5,'end')])
    base=GeneratedGlyph('v','靶','u','zh','writer','s','p','g',1.,[stroke])
    result=assemble(base,{0:selected},'author_single_stroke')
    assert len(result.strokes[0].points)==len(source.points)
    assert [p.pressure for p in result.strokes[0].points]==source.pressure
    assert [p.t_ms for p in result.strokes[0].points]==[0,10,40,80]
    assert source.t_ms==[500,510,540,580]
    with pytest.raises(ValueError,match='incomplete'):
        require_author_only(result,{})
    assert require_author_only(result,{0:log}) is result


def test_new_contact_uses_segments_not_bounding_boxes():
    before=[[(0,0),(1,0)],[(.5,.5),(.5,1)]]
    after=[[(0,.6),(1,.6)],before[1]]
    assert pair_changes(before,after,before)['unsupported_crossings']==[(0,1)]
    assert pair_changes(after,after,before)['unsupported_crossings']==[]


def test_source_internal_contact_not_confused_with_replacement_or_boundary_damage():
    changes={'new_contacts':[(1,2),(1,5),(1,6)],'unsupported_contacts':[(1,2),(1,5),(1,6)],
             'new_crossings':[],'unsupported_crossings':[]}
    result=retain_source_relationships(changes,range(5))
    assert result['inherited_source_contacts']==[(1,2)]
    assert result['unsupported_contacts']==[(1,5),(1,6)]


def test_invalid_capture_time_or_pressure_cannot_be_admitted():
    source,*_=fixture()
    assert valid_source(source)
    source.t_ms=[50,20,80,90]
    assert not valid_source(source)
    source.t_ms=[0,20,80,90]
    source.pressure[0]=float('nan')
    assert not valid_source(source)
