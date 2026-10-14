"""Batch acceleration and visible gap contracts, without private fixtures."""
import sys
from pathlib import Path

import numpy as np
import pytest
from test_v61_author_strokes import fixture

from inkstruct.v61_author_strokes import AuthorStrokeFallback
from inkstruct.v61_author_strokes_batch import BatchAuthorStrokeFallback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generate_v61_corrected_library import compact_sources, display_svg

from inkstruct.schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke


@pytest.mark.parametrize('character',['供','靶'])
@pytest.mark.parametrize('start_anchor',[None,(.48,.12)])
def test_cached_selection_matches_original(character,start_anchor):
    source,graph,profile,repo=fixture(character)
    old=AuthorStrokeFallback(profile,repo);new=BatchAuthorStrokeFallback(profile,repo)
    for scale in (.7,1.,1.2):
        target=[(.1+scale*x,.02+scale*y) for x,y in source.points]
        a,ap=old.select(graph,0,[target],[target],start_anchor=start_anchor)
        b,bp=new.select(graph,0,[target],[target],start_anchor=start_anchor)
        assert (a is None)==(b is None)
        assert ap['rejections']==bp['rejections']
        if a:
            assert ap['sample_id']==bp['sample_id']
            np.testing.assert_allclose(a['points'],b['points'],atol=1e-14,rtol=0)
            assert a['pressure']==b['pressure'] and a['time']==b['time']


def test_missing_bucket_and_visible_diagnostic_gap():
    source,graph,profile,repo=fixture()
    engine=BatchAuthorStrokeFallback(profile,repo)
    graph.strokes[0].median=[(.1,.1),(.9,.1)]
    selected,log=engine.select(graph,0,[graph.strokes[0].median],[graph.strokes[0].median])
    assert selected is None and log['eligible_geometry']==0
    rows,donors,gaps=compact_sources(graph,{},[log])
    assert not donors and rows[0]['kind']=='explicit_gap' and gaps[0]['order']==1
    s=GeneratedStroke('s1',1,1.,[GeneratedPoint(x,y,i,.5,'down' if i==0 else 'end') for i,(x,y) in enumerate(source.points)])
    glyph=GeneratedGlyph('v','靶','u','zh','writer','s','p','g',1.,[s])
    image=display_svg(glyph,{}).decode()
    assert 'class="reference"' in image and 'stroke-dasharray' in image
    assert image.count(' L')==len(source.points)-1


def test_preserved_source_internal_contact_is_not_boundary_alarm():
    from generate_v61_corrected_library import classify_inherited_contacts
    p={'kind':'author_complete_component','sample_id':'a','target_component':'whole','transform':{'sx':1}}
    sources={0:p,1:dict(p),2:{**p,'target_component':'other'}}
    checks={'new_external_crossings':[(1,2),(2,3)],'contacts':{'0.028':{'new_external':[(1,2),(2,3)]}}}
    result=classify_inherited_contacts(checks,sources)
    assert result['new_external_crossings']==[(2,3)]
    assert result['inherited_source_crossings']==[(1,2)]
    assert result['contacts']['0.028']['new_external']==[(2,3)]
