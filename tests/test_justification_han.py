"""Seeded variation and legal-gap alignment preserve frozen resources and identity."""
import io
import json
import zipfile
from dataclasses import replace

import pytest
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.glyph_corrections import GlyphCorrection
from inkstruct.document.han_variation import HanVariation
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, package_bytes, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.editor.correction_context import surrounding_glyphs
from inkstruct.global_defaults import LayoutDefaults
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg

CHARS = "中文测试汉字后文行内公式电容器损耗角参数甲乙abcdefghijklmnopqrstuvwxyz−"


def resources():
    glyphs = []
    for c in dict.fromkeys(CHARS):
        raw = specimen(c, "fixture-"+str(ord(c)))
        xy = [(20,20),(65,25),(40,45),(55,65),(25,75)] if c != "−" else [(20,45),(65,45)]
        raw["strokes"][0]["points"] = [{"x":x,"y":y,"t_ms":i*10,"pressure":.5} for i,(x,y) in enumerate(xy)]
        raw["guides"]["math_axis_em"] = .25
        glyphs.append(adapt_symbol(json.dumps(raw,ensure_ascii=False).encode()))
    return AssetResolver(embedded=glyphs,builtin_numbers=True)


def render(source, flow=None, page=None, resolver=None):
    source = source if isinstance(source, SourceSession) else SourceSession(source)
    return layout_markdown(parse_markdown(source),resolver or resources(),flow=flow or FlowStyle(),
                           page=page or PageProfile(46,160,5))


def points(snapshot, f):
    return tuple(p for op in snapshot.pages[f.page_index].paint_ops if op.occurrence_id==f.occurrence_id
                 for p in op.points)


def normalized(snapshot, f):
    return tuple((round(x-f.x_mm,8),round(y-f.baseline_mm,8)) for x,y in points(snapshot,f))


def test_formula_wrap_distributes_spare_space_without_stretching_math_or_glyphs():
    session=SourceSession(r"中文测试 $\frac{1234}{56}$ 后文")
    resolver=resources()
    page=PageProfile(38,160,5)
    left=render(session,page=page,resolver=resolver)
    justified=render(session,FlowStyle(paragraph_align="justify"),page=page,resolver=resolver)
    assert justified.plotter_exportable,justified.diagnostics
    first=[f for f in justified.fragments if f.line_index==0 and f.asset_id]
    assert [f.text for f in first]==list("中文测试")
    assert first[-1].logical_bounds[2]==pytest.approx(33)
    assert first[-1].x_mm>next(f.x_mm for f in left.fragments if f.text=="试")
    assert next(f.line_index for f in justified.fragments if f.text=="1")>0
    assert [f.occurrence_id for f in left.fragments]==[f.occurrence_id for f in justified.fragments]
    for old,new in zip(left.fragments,justified.fragments):
        assert (old.advance_mm,old.baseline_mm,old.line_index)==(new.advance_mm,new.baseline_mm,new.line_index) or old.text.isspace()
        if old.asset_id:
            assert normalized(left,old)==normalized(justified,new)
    assert max(f.logical_bounds[2] for f in justified.fragments if f.line_index==0)<=33+1e-8
    plan_from_snapshot(justified)


@pytest.mark.parametrize("source", ["中文\\newline测试", "# 中文测试汉字后文", "`中文测试汉字`", "中文测试"])
def test_final_manual_heading_and_inline_code_lines_keep_original_spacing(source):
    session=SourceSession(source)
    left=render(session)
    right=render(session,FlowStyle(paragraph_align="justify"))
    assert left.pages==right.pages


def test_latin_words_keep_internal_spacing_and_only_spaces_expand():
    session=SourceSession("alpha beta gamma delta")
    page=PageProfile(62,160,5)
    left=render(session,page=page)
    right=render(session,FlowStyle(paragraph_align="justify"),page=page)
    assert right.plotter_exportable,right.diagnostics
    for word in ("alpha","beta"):
        start=session.source.index(word)
        original=[f for f in left.fragments if start<=f.span.start<start+len(word)]
        changed=[f for f in right.fragments if start<=f.span.start<start+len(word)]
        assert [f.x_mm-original[0].x_mm for f in original]==pytest.approx([f.x_mm-changed[0].x_mm for f in changed])
    assert next(f.x_mm for f in right.fragments if f.text=="b")>next(f.x_mm for f in left.fragments if f.text=="b")



@pytest.mark.parametrize("strength", [0,.35,1])
def test_variation_is_deterministic_bounded_and_keeps_layout_and_resources(strength):
    session,resolver=SourceSession("汉"*12),resources()
    base=render(session,resolver=resolver)
    raw=tuple(g.original_json for pool in resolver.pools.values() for g in pool)
    choices=resolver.selection_records()
    flow=FlowStyle(han_variation=HanVariation(enabled=True,seed=123,strength=strength,schema_version="inkstruct_han_variation_v1"))
    varied=render(session,flow,resolver=resolver)
    assert varied==render(session,flow,resolver=resolver)
    assert varied.plotter_exportable,varied.diagnostics
    assert tuple(g.original_json for pool in resolver.pools.values() for g in pool)==raw
    assert resolver.selection_records()==choices
    for a,b in zip(base.fragments,varied.fragments):
        assert (a.x_mm,a.baseline_mm,a.advance_mm,a.logical_bounds,a.asset_id)==(b.x_mm,b.baseline_mm,b.advance_mm,b.logical_bounds,b.asset_id)
        assert len(points(base,a))==len(points(varied,b))
        assert a.ink_bounds[0]-1e-8<=b.ink_bounds[0]<=b.ink_bounds[2]<=a.ink_bounds[2]+1e-8
        assert a.ink_bounds[1]-1e-8<=b.ink_bounds[1]<=b.ink_bounds[3]<=a.ink_bounds[3]+1e-8
    if strength:
        assert varied.pages!=base.pages
        assert len({normalized(varied,f) for f in varied.fragments})==12
        other=render(session,replace(flow,han_variation=replace(flow.han_variation,seed=124)),resolver=resolver)
        assert other.pages!=varied.pages
    else:
        assert varied.pages==base.pages


def test_math_code_and_latin_are_not_varied_and_source_anchors_survive_edit_and_undo():
    session,resolver=SourceSession("汉中文 `中文` $中$ abc"),resources()
    flow=FlowStyle(han_variation=HanVariation(enabled=True,seed=77,schema_version="inkstruct_han_variation_v1"))
    left=render(session,resolver=resolver)
    varied=render(session,flow,resolver=resolver)
    eligible={f.occurrence_id for f in varied.fragments if f.span.start<3}
    for a,b in zip(left.fragments,varied.fragments):
        if a.occurrence_id not in eligible:
            assert points(left,a)==points(varied,b)
    original={f.occurrence_id:normalized(varied,f) for f in varied.fragments if f.occurrence_id in eligible}
    session.apply(0,0,"汉")
    after=render(session,flow,resolver=resolver)
    for f in after.fragments:
        if f.occurrence_id in original:
            assert normalized(after,f)==original[f.occurrence_id]
    assert session.undo()
    assert render(session,flow,resolver=resolver).pages==varied.pages


def test_v5_package_roundtrip_seed_and_machine_svg_exact(tmp_path):
    session,resolver=SourceSession(r"中文测试 $\frac{1234}{56}$ 后文汉汉汉"),resources()
    flow=FlowStyle(paragraph_align="justify",han_variation=HanVariation(enabled=True,seed=42))
    before=render(session,flow,resolver=resolver)
    path=tmp_path/"varied.inkdoc"
    save_package(path,session,resolver,PageProfile(46,160,5),StyleProfile(),flow=flow)
    loaded=load_package(path)
    after=render(loaded.session,loaded.flow,loaded.page,loaded.resolver)
    assert before==after and loaded.flow==flow and flow.schema_version=="inkstruct_flow_style_v5"
    assert [page_svg(p) for p in plan_from_snapshot(before).pages]==[page_svg(p) for p in plan_from_snapshot(after).pages]
    for p in plan_from_snapshot(after).pages:
        assert "<path" in page_svg(p)


def test_legacy_saved_styles_remain_left_aligned_without_variation():
    data=package_bytes(SourceSession("中文测试"),resources(),PageProfile(),StyleProfile(),flow=FlowStyle())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        record=json.loads(archive.read("styles.json"))["flow"]
    assert "paragraph_align" not in record and "han_variation" not in record
    assert FlowStyle(**record).paragraph_align=="left"
    assert not FlowStyle(**record).han_variation.enabled
    assert LayoutDefaults().flow.paragraph_align=="justify"


def test_correction_preview_uses_same_varied_base_and_applies_correction_once():
    session,resolver=SourceSession("汉中文"),resources()
    flow=FlowStyle(han_variation=HanVariation(enabled=True,seed=8))
    rule=GlyphCorrection(scope="document",dx_em=.03,scale_x=.98)
    corrected=render(session,replace(flow,glyph_corrections=(rule,)),resolver=resolver)
    lookup={g.asset_id:g for pool in resolver.pools.values() for g in pool}
    context=surrounding_glyphs(corrected,corrected.fragments[0],lambda f:lookup[f.asset_id],flow=flow,document=parse_markdown(session))
    assert len(context)==3
    for c in context:
        expected=points(corrected,c.fragment)
        for actual, wanted in zip([p for stroke in c.corrected(rule) for p in stroke], expected):
            assert actual==pytest.approx(wanted)


@pytest.mark.parametrize("record", [{"enabled":1},{"seed":True},{"seed":-1},{"seed":2147483648},
                                     {"strength":True},{"strength":float("nan")},{"strength":1.1}])
def test_invalid_variation_parameters_are_rejected(record):
    with pytest.raises(ValueError):
        HanVariation(**record)


def test_unknown_flow_schema_cannot_be_hidden_by_enabling_a_new_feature():
    with pytest.raises(ValueError,match="Unsupported flow"):
        FlowStyle(schema_version="unknown",paragraph_align="justify")


def test_template_footnotes_and_caches_do_not_double_apply_variation(tmp_path):
    from test_break_commands import multi_frame

    from inkstruct.layout.continuation import ContinuationCache, continuation_scope
    from inkstruct.layout.measurement_cache import MeasurementCache, measurement_scope

    session,resolver=SourceSession("汉中文[^a]"*4+"\n\n[^a]: 汉中文"),resources()
    flow=FlowStyle(template=multi_frame(),paragraph_align="justify",han_variation=HanVariation(enabled=True,seed=1))
    document=parse_markdown(session,field_blocks=True)
    mc,cc=MeasurementCache(),ContinuationCache()
    for seed in (1,2,1):
        chosen=replace(flow,han_variation=replace(flow.han_variation,seed=seed))
        plain=layout_markdown(document,resolver,flow=chosen)
        with measurement_scope(mc),continuation_scope(cc):
            cached=layout_markdown(document,resolver,flow=chosen)
        assert plain==cached
    path=tmp_path/"template.inkdoc"
    save_package(path,session,resolver,PageProfile(),StyleProfile(),flow=flow)
    loaded=load_package(path)
    assert loaded.flow==flow
    assert layout_markdown(parse_markdown(loaded.session,field_blocks=True),loaded.resolver,flow=loaded.flow)==plain


def test_keyword_document_argument_supports_variation():
    document=parse_markdown("汉")
    result=layout_markdown(document=document,resolver=resources(),flow=FlowStyle(han_variation=HanVariation(enabled=True)))
    assert result.plotter_exportable
