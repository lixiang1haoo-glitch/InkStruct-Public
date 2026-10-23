from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from inkstruct.geometry import path_length
from inkstruct.schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke
from inkstruct.structure_delta import apply_structure_delta, transport_stroke


def objects():
    curves = [[(.1,.2),(.5,.2)],[(.2,.4),(.6,.4)]]
    strokes = [SimpleNamespace(stroke_id=f's{i+1}',order=i+1,median=p) for i,p in enumerate(curves)]
    graph = SimpleNamespace(character='十',strokes=strokes)
    glyph = GeneratedGlyph('v1','十','U+5341','zh-Hans','fixture','v1','profile','test',.8,
        [GeneratedStroke(f's{i+1}',i+1,.8,[GeneratedPoint(x,y,i*200+j*100,.5,'down' if j==0 else 'end') for j,(x,y) in enumerate(p)],'legacy_exact',None) for i,p in enumerate(curves)],{'scale':1.})
    return graph,glyph


def test_source_vertex_correspondence_recovers_clipped_tail_without_new_compression():
    old=[[.2,.8],[.2,1.],[.25,1.]]
    new=[[.2,.8],[.2,1.04],[.25,1.09]]
    predicted=[[.2,.5],[.2,.7],[.25,.7]]
    points,t,report=transport_stroke(predicted,old,new,np.eye(2))
    assert np.allclose(points[0],predicted[0])
    assert np.allclose(points[-1],[.25,.79])
    assert report['correspondence']=='source_vertex_index'
    assert len(points)>=len(predicted)
    assert np.all(np.diff(t)>0)


def test_constant_delta_preserves_shape_and_affine_frame():
    old=[[.1,.2],[.2,.25],[.5,.2]]
    new=(np.asarray(old)+[.02,.03]).tolist()
    out=[[.11,.3],[.3,.5],[.55,.27]]
    linear=np.array([[.8,.1],[0,.9]])
    points,_,_=transport_stroke(out,old,new,linear)
    assert np.allclose(np.asarray(points)[[0,-1]],np.asarray(out)[[0,-1]]+linear@np.array([.02,.03]))
    assert abs(path_length(points)-path_length(out))<1e-12


def test_nonfinite_and_reflected_frames_rejected():
    p=[[0.,0.],[1.,1.]]
    with pytest.raises(ValueError,match='frame'):
        transport_stroke(p,p,p,np.diag([-1.,1.]))
    with pytest.raises(ValueError,match='polyline'):
        transport_stroke(p,p,[[0,0],[1,float('nan')]],np.eye(2))


def test_noop_is_exact_and_captured_points_protected():
    graph,glyph=objects()
    result,report=apply_structure_delta(glyph,graph,graph,{})
    assert result is glyph and report['reason']=='reference unchanged'
    new=SimpleNamespace(character='十',strokes=[SimpleNamespace(stroke_id='s1',order=1,median=[(.1,.1),(.5,.1)]),graph.strokes[1]])
    glyph.strokes[0].style_source='source-original'
    result,report=apply_structure_delta(glyph,graph,new,{})
    assert result is glyph and report['events'][0]['reason']=='captured trajectory protected'


def test_only_changed_stroke_geometry_and_pressure_are_touched():
    graph,glyph=objects()
    new=SimpleNamespace(character='十',strokes=[SimpleNamespace(stroke_id='s1',order=1,median=[(.1,.1),(.5,.1)]),graph.strokes[1]])
    result,report=apply_structure_delta(glyph,graph,new,{},guard=True)
    assert report['applied']
    assert [(p.x,p.y,p.pressure) for p in result.strokes[1].points]==[(p.x,p.y,p.pressure) for p in glyph.strokes[1].points]
    assert glyph.strokes[0].points[0].y==.2


def test_guard_refuses_overflow_without_hiding_by_canvas_rescale():
    graph,glyph=objects()
    new=SimpleNamespace(character='十',strokes=[SimpleNamespace(stroke_id='s1',order=1,median=[(.1,-.2),(.5,-.2)]),graph.strokes[1]])
    result,report=apply_structure_delta(glyph,graph,new,{},guard=True)
    assert result is glyph and not report['applied'] and 'bounds' in report['invariant_errors']


def test_identity_mismatch_rejected():
    graph,glyph=objects()
    with pytest.raises(ValueError,match='identity'):
        apply_structure_delta(replace(glyph,strokes=list(reversed(glyph.strokes))),graph,graph,{})
