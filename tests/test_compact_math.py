"""Optical math is explicit and versioned; legacy glyphs and geometry stay intact."""

import json
import zipfile
from dataclasses import replace

import pytest
from test_latin_spacing import captured
from test_math_sample_constructions import STYLE, measure, resolver

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import FlowTemplate
from inkstruct.document.glyph_corrections import GlyphCorrection
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.style import MathStyle
from inkstruct.renderers.pages import page_svg


@pytest.mark.parametrize('char',list('AB01,.α'))
def test_formula_capture_offset_is_not_a_side_bearing(char):
    session=SourceSession('$'+char+'$')
    boxes=[]
    for left in (.1,.7):
        r=AssetResolver(embedded=[captured(char,left)])
        box=measure(session,r,MathStyle.handwriting())
        assert box.ready,box.diagnostics
        g=box.glyphs[0]
        assert g.em_mm==6 and g.glyph==r.resolve(g.occurrence)
        advance=max(.18*6+.3,.315*6) if char in '0123456789' else .18*6+.3
        assert g.advance_mm==pytest.approx(advance)
        extra=(advance-(.18*6+.3))/2
        assert g.origin_offset_mm+g.glyph.bounds[0]*6-.15==pytest.approx(.04*6+extra)
        boxes.append(box.width)
    assert boxes[0]==pytest.approx(boxes[1])


@pytest.mark.parametrize('formula',[
    r'\frac{123456}{789}',r'\sqrt{123}',r'\sqrt[3]{\frac{12}{34}}',
    r'\left(\frac{12}{34}\right)',r'\left[\sqrt{12}\right]',
    r'\left\{\frac{12}{34}\right\}',r'\begin{bmatrix}1&2\\3&4\end{bmatrix}',
])
def test_compact_structures_keep_sources_and_reduce_empty_geometry(formula):
    r=resolver();session=SourceSession('$'+formula+'$')
    old=measure(session,r,STYLE)
    choices=r.selection_records()
    new=measure(session,r,MathStyle.handwriting())
    assert new.ready and old.ready,(old.diagnostics,new.diagnostics)
    assert r.selection_records()==choices
    assert new.width<old.width
    assert new.ascent+new.descent<old.ascent+old.descent
    assert all(rule.asset_id and rule.sample_id and rule.transform for rule in new.rules)
    assert [(g.glyph,g.em_mm) for g in new.glyphs]==[(g.glyph,g.em_mm) for g in old.glyphs]


def test_explicit_spacing_and_scale_ratios_are_preserved():
    r=resolver();style=MathStyle.handwriting()
    compact=measure(SourceSession('$1234$'),r,style)
    spaced=measure(SourceSession(r'$12\quad34$'),r,style)
    assert spaced.width-compact.width==pytest.approx(6)
    assert style.fraction_scale==MathStyle().fraction_scale==.8
    assert style.script_scale==MathStyle().script_scale==.7


@pytest.mark.parametrize('named',[False,True])
def test_compact_math_version_and_frozen_roundtrip(tmp_path,named):
    r=resolver();session=SourceSession(r'$\sqrt{\frac{12}{34}}+\left(12\right)$')
    flow=FlowStyle(math=MathStyle.handwriting(),template=FlowTemplate() if named else None)
    before=layout_markdown(parse_markdown(session,field_blocks=named),r,flow=flow)
    choices=r.selection_records()
    raw={(g.asset_id,g.metrics_key):g.original_json for pool in r.pools.values() for g in pool}
    path=tmp_path/'compact.inkdoc'
    save_package(path,session,r,PageProfile(),StyleProfile(),flow=flow)
    loaded=load_package(path)
    assert loaded.flow==flow and loaded.session.atom_ids==session.atom_ids
    after=layout_markdown(parse_markdown(loaded.session,field_blocks=named),loaded.resolver,flow=loaded.flow)
    assert loaded.resolver.selection_records()==choices
    assert {(g.asset_id,g.metrics_key):g.original_json for pool in loaded.resolver.pools.values() for g in pool}==raw
    assert [page_svg(before,i,debug=True) for i in range(len(before.pages))]==[page_svg(after,i,debug=True) for i in range(len(after.pages))]
    with zipfile.ZipFile(path) as z:
        math=json.loads(z.read('styles.json'))['flow']['math']
        assert math['schema_version']=='inkstruct_math_style_v2' and math['spacing_policy']=='handwriting'
    legacy=tmp_path/'legacy.inkdoc'
    save_package(legacy,session,r,PageProfile(),StyleProfile(),flow=replace(flow,math=STYLE))
    with zipfile.ZipFile(legacy) as z:
        assert 'spacing_policy' not in json.loads(z.read('styles.json'))['flow']['math']
    assert load_package(legacy).flow.math==STYLE


def test_missing_sample_and_invalid_policy_still_block():
    box=measure(SourceSession(r'$\sqrt{1}$'),AssetResolver(builtin_numbers=True),MathStyle.handwriting())
    assert not box.ready and any(d.code=='math-construction-sample-invalid' for d in box.diagnostics)
    with pytest.raises(ValueError):MathStyle(spacing_policy='unknown')
    with pytest.raises(ValueError):MathStyle(schema_version='unknown')


def test_compact_formula_document_correction_preserves_frame_and_is_not_normalized_away():
    r=AssetResolver(embedded=[captured('A',.65)])
    session=SourceSession('$A$')
    document=parse_markdown(session)
    flow=FlowStyle(math=MathStyle.handwriting())
    before=layout_markdown(document,r,flow=flow)
    f=before.fragments[0]
    corrected=replace(flow,glyph_corrections=(GlyphCorrection(
        character='A',occurrence_id=f.occurrence_id,asset_id=f.asset_id,dx_em=.1,dy_em=.08,scale_x=1.2),))
    choices=r.selection_records()
    after=layout_markdown(document,r,flow=corrected)
    a=after.fragments[0]
    assert (f.x_mm,f.baseline_mm,f.advance_mm,f.logical_bounds)==(a.x_mm,a.baseline_mm,a.advance_mm,a.logical_bounds)
    assert r.selection_records()==choices
    old=[p for op in before.pages[0].paint_ops for p in op.points]
    new=[p for op in after.pages[0].paint_ops for p in op.points]
    origin=f.x_mm+f.glyph_origin_offset_mm
    for (x,y),(xx,yy) in zip(old,new,strict=True):
        assert xx==pytest.approx(origin+(x-origin)*1.2+.1*f.glyph_em_mm)
        assert yy==pytest.approx(y+.08*f.glyph_em_mm)
