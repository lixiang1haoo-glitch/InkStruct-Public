"""Thin digits need numeric slots while glyph size and frozen identities stay fixed."""

import json
from dataclasses import replace

import pytest
from test_math_sample_constructions import measure
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.style import MathStyle
from inkstruct.renderers.pages import page_svg


def thin_one(left=.5):
    data=specimen('1','thin-one')
    for point in data['strokes'][0]['points']:point['x']=10+left*100
    return adapt_symbol(json.dumps(data).encode())


@pytest.mark.parametrize('em',[3,5,6,10])
@pytest.mark.parametrize('pen',[.1,.3,.5])
def test_thin_one_slot_is_centered_without_changing_ink(em,pen):
    r=AssetResolver(embedded=[thin_one()],builtin_numbers=True)
    box=measure(SourceSession('$111$'),r,MathStyle.handwriting(em_mm=em)) if pen==.3 else None
    if box is None:
        from inkstruct.math.handwritten import measure_math
        doc=parse_markdown(SourceSession('$111$'));node=next(n for root in doc.nodes for n in root.walk() if n.math)
        box=measure_math(node.math,r,owner=node.node_id,style=MathStyle.handwriting(em_mm=em),stroke_width=pen)
    expected=max(.315*em,.08*em+pen)
    assert box.ready,box.diagnostics
    for g in box.glyphs:
        assert g.advance_mm==pytest.approx(expected)
        assert g.em_mm==em and g.glyph.strokes==thin_one().strokes
        centre=g.origin_offset_mm+g.glyph.bounds[0]*em
        assert centre==pytest.approx(expected/2)
    assert [b.x_mm-a.x_mm for a,b in zip(box.glyphs,box.glyphs[1:])]==pytest.approx([expected,expected])


@pytest.mark.parametrize('formula',[r'1111',r'1.1111',r'10^{11}',r'1.1\times10^{-11}',r'\frac{1111}{11}',r'1:4:16'])
def test_numbers_scripts_and_fractions_keep_original_samples_and_scale(formula):
    symbols=[thin_one()]
    for c in ('×',':','−'):
        data=specimen(c,c);data['guides']['math_axis_em']=.25
        symbols.append(adapt_symbol(json.dumps(data).encode()))
    r=AssetResolver(embedded=symbols,builtin_numbers=True)
    box=measure(SourceSession('$'+formula+'$'),r,MathStyle.handwriting(fraction_source='geometric'))
    assert box.ready,box.diagnostics
    for g in box.glyphs:
        if g.occurrence.text=='1':
            assert g.advance_mm>=.315*g.em_mm-1e-9
            assert g.glyph.original_json==thin_one().original_json


def test_capture_offsets_cancel_and_legacy_math_does_not_change():
    boxes=[]
    for left in (.1,.8):
        r=AssetResolver(embedded=[thin_one(left)])
        session=SourceSession('$11$')
        compact=measure(session,r,MathStyle.handwriting())
        old=measure(session,r,MathStyle())
        g=old.glyphs[0]
        expected=max(g.glyph.layout_metrics.advance,g.glyph.layout_bounds[2])*6+.3
        assert g.advance_mm==pytest.approx(expected)
        boxes.append(tuple(g.x_mm+g.origin_offset_mm+g.glyph.bounds[0]*g.em_mm for g in compact.glyphs))
    assert boxes[0]==pytest.approx(boxes[1])


def test_table_body_and_non_digit_formula_geometry_and_corrections_remain_independent(tmp_path):
    from inkstruct.document.glyph_corrections import GlyphCorrection

    r=AssetResolver(embedded=[thin_one()],builtin_numbers=True)
    session=SourceSession('111\n\n|111|1.11|\n|---|---|\n|11|1111|\n\n$111$')
    doc=parse_markdown(session)
    legacy=layout_markdown(doc,r,flow=FlowStyle())
    flow=FlowStyle(math=MathStyle.handwriting())
    compact=layout_markdown(doc,r,flow=flow)
    assert legacy.fragments[:-3]==compact.fragments[:-3]
    choices=r.selection_records()
    f=compact.fragments[-3]
    corrected=replace(flow,glyph_corrections=(GlyphCorrection(
        character='1',asset_id=f.asset_id,occurrence_id=f.occurrence_id,dx_em=.1,scale_x=1.2),))
    result=layout_markdown(doc,r,flow=corrected)
    assert result.fragments[-3].advance_mm==f.advance_mm
    assert r.selection_records()==choices
    p=tmp_path/'digits.inkdoc'
    save_package(p,session,r,PageProfile(),StyleProfile(),flow=corrected)
    loaded=load_package(p)
    reopened=layout_markdown(parse_markdown(loaded.session),loaded.resolver,flow=loaded.flow)
    assert loaded.session.atom_ids==session.atom_ids and loaded.resolver.selection_records()==choices
    assert page_svg(reopened,0)==page_svg(result,0)
