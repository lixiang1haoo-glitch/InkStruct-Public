"""Recorded math axes survive font publication and immutable document freezing."""
import copy
import json

import pytest
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage, decode, from_embedded, to_user
from inkstruct.fonts.importer import build_font
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg


def samples(root, axis=0.4, *, missing=False):
    root.mkdir()
    glyphs=[]
    for char in '123+−=<>×∑√αβγ':
        value=specimen(char,str(ord(char)))
        if not missing:
            value['guides']['math_axis_em']=axis
        raw=json.dumps(value).encode()
        (root/f'{ord(char)}.json').write_bytes(raw)
        glyphs.append(adapt_symbol(raw))
    return glyphs


def test_axis_survives_developer_user_and_frozen_formula_without_source(tmp_path):
    folder=tmp_path/'symbols'
    raw=samples(folder)
    original={p:p.read_bytes() for p in folder.iterdir()}
    dev,user=tmp_path/'dev.inkfont',tmp_path/'user.inkfont'
    build_font(dev,writer='fixture',name='axis',symbols=folder)
    to_user(dev,user)
    a,b=FontPackage(dev),FontPackage(user)
    assert a.manifest['core_hash']==b.manifest['core_hash']
    font_glyphs=list(b.glyphs())
    assert all(g.math_axis_em==0.4 for g in font_glyphs)
    for g in font_glyphs:
        if g.character in '*∗':
            assert decode(g.original_json)['summary']['source_kind'] == 'composed'
            continue
        source=next(s for s in raw if s.character==('−' if g.character=='–' else g.character))
        assert g.strokes==source.strokes and g.metrics==source.metrics
        if g.character=='–':
            assert decode(g.original_json)['summary']['symbol_construction']['rule']=='en-dash-from-minus'
    source_text='$1+2=3$'
    doc=parse_markdown(source_text)
    node=next(n for root in doc.nodes for n in root.walk() if n.math)
    for glyphs in (raw,font_glyphs):
        box=measure_math(node.math,AssetResolver(embedded=glyphs),owner=node.node_id,
                         style=MathStyle(em_mm=10,axis_em=0.25))
        assert box.ready
        assert [g.baseline_mm for g in box.glyphs if g.occurrence.text in '+=']==pytest.approx([1.5,1.5])
    cases=['$1+2=3$','$α+β=γ$','$1<2$',r'$1\times2$',r'$\sum 1$',
           r'$\frac{1}{2}$',r'$\sqrt{1}$']
    for i,text in enumerate(cases):
        session=SourceSession(text)
        resolver=AssetResolver(embedded=font_glyphs)
        snap=layout_markdown(parse_markdown(session),resolver)
        assert snap.plotter_exportable, snap.diagnostics
        assert any(d.code=='math-calibration-unreviewed' for d in snap.diagnostics)
        svg=[page_svg(p) for p in plan_from_snapshot(snap).pages]
        path=tmp_path/f'case-{i}.inkdoc'
        save_package(path,session,resolver,PageProfile(),StyleProfile())
        restored=load_package(path)
        after=layout_markdown(parse_markdown(restored.session),restored.resolver)
        assert after==snap
        assert [page_svg(p) for p in plan_from_snapshot(after).pages]==svg
    frozen=tmp_path/'case-0.inkdoc'
    assert all(p.read_bytes()==v for p,v in original.items())
    for p in folder.iterdir():
        p.unlink()
    dev.unlink(); user.unlink()
    restored=load_package(frozen)
    assert layout_markdown(parse_markdown(restored.session),restored.resolver).plotter_exportable


@pytest.mark.parametrize('axis',[True,False,-0.1,2.1,'0.25',None,float('inf'),float('nan')])
def test_invalid_recorded_axis_rejected_at_publication(tmp_path,axis):
    folder=tmp_path/'symbols'
    samples(folder,axis)
    path=tmp_path/'invalid.inkfont'
    with pytest.raises(ValueError,match='数学轴|非有限数值'):
        build_font(path,writer='fixture',name='invalid',symbols=folder)
    assert not path.exists()
    raw=adapt_symbol((folder/'43.json').read_bytes())
    resolver=AssetResolver(embedded=[raw])
    result=layout_markdown(parse_markdown('$+$'),resolver)
    assert not result.exportable
    expected='math-axis-missing' if axis is None else 'math-axis-invalid'
    assert expected in [d.code for d in result.diagnostics]


def test_old_core_without_axis_remains_readable_but_does_not_guess_default(tmp_path):
    folder=tmp_path/'symbols'
    samples(folder,missing=True)
    font_path=tmp_path/'legacy.inkfont'
    build_font(font_path,writer='fixture',name='old',symbols=folder)
    font=FontPackage(font_path)
    assert all(g.math_axis_em is None for g in font.glyphs() if g.character not in '*∗')
    assert all(decode(g.original_json)['summary']['symbol_construction']['axis_basis'] == 'default-math-style'
               for g in font.glyphs('*∗'))
    snapshot=layout_markdown(parse_markdown('$1+2=3$'),AssetResolver(embedded=font.glyphs()))
    assert [d.code for d in snapshot.diagnostics if d.severity=='error']==['math-axis-missing']*2
    with pytest.raises(ValueError,match='Unresolved document errors'):
        plan_from_snapshot(snapshot)


def test_axis_is_hash_protected_and_illegal_axis_cannot_be_frozen(tmp_path):
    folder=tmp_path/'symbols'; samples(folder)
    path=tmp_path/'font.inkfont'
    build_font(path,writer='fixture',name='axis',symbols=folder)
    core=decode(next(FontPackage(path).glyphs('+')).original_json)
    changed=copy.deepcopy(core)
    changed['summary']['capture_guides']['math_axis_em']=0.3
    with pytest.raises(ValueError,match='来源身份不一致'):
        from_embedded(json.dumps(changed).encode())
    for axis in (True,-1,3,None,'0.4'):
        changed=copy.deepcopy(core)
        changed['summary']['capture_guides']['math_axis_em']=axis
        with pytest.raises(ValueError,match='数学轴'):
            from_embedded(json.dumps(changed).encode())
