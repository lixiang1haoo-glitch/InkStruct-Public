import hashlib
import json
import zipfile
from dataclasses import asdict, replace

import pytest
from test_font_packages import recorded

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.glyph_corrections import GlyphCorrection, correction_for, update_corrections
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.editor.mixed import build_markdown
from inkstruct.fonts.core import FontPackage, decode, to_user
from inkstruct.fonts.corrections import correct_font
from inkstruct.fonts.importer import build_font
from inkstruct.layout.blocks import layout_markdown
from inkstruct.renderers.pages import page_svg


@pytest.fixture
def font(tmp_path):
    source = tmp_path / "source.inkfont"
    build_font(source, writer="fixture", name="correction", symbols=recorded(
        tmp_path, styles=("upright", "upright", "italic")))
    return FontPackage(source)


def points(snapshot, fragment):
    return tuple(p for op in snapshot.pages[fragment.page_index].paint_ops
                 if op.occurrence_id == fragment.occurrence_id for p in op.points)


def test_scopes_precedence_geometry_frozen_reopen_and_svg(font, tmp_path):
    session = SourceSession(r"AA $A$ $\mathrm{A}$" + "\n\n|A|\n|---|\n|A|")
    resolver = AssetResolver(embedded=font.glyphs())
    document = parse_markdown(session)
    before = layout_markdown(document, resolver)
    f = before.fragments[1]
    rules = (GlyphCorrection(scope="document", dx_em=.05),
             GlyphCorrection(scope="character", character="A", asset_id=f.asset_id, scale_x=1.2),
             GlyphCorrection(character="A", occurrence_id=f.occurrence_id, asset_id=f.asset_id,
                             dx_em=-.1, dy_em=.08, scale_x=.8, scale_y=1.1))
    flow = FlowStyle(glyph_corrections=rules)
    frozen = tuple(g.original_json for g in resolver.pools["A"])
    selections = resolver.selection_records()
    after = layout_markdown(document, resolver, flow=flow)
    assert after.exportable, after.diagnostics
    assert len(after.fragments) == len(before.fragments)
    assert tuple(g.original_json for g in resolver.pools["A"]) == frozen
    assert resolver.selection_records() == selections
    assert page_svg(before, 0) != page_svg(after, 0)
    for old, new in zip(before.fragments, after.fragments, strict=True):
        assert (old.x_mm, old.baseline_mm, old.advance_mm, old.logical_bounds, old.asset_id) == (
            new.x_mm, new.baseline_mm, new.advance_mm, new.logical_bounds, new.asset_id)
        expected = rules[2] if old.occurrence_id == f.occurrence_id else (
            rules[1] if old.asset_id == f.asset_id else rules[0])
        origin = old.x_mm + old.glyph_origin_offset_mm
        em = old.glyph_em_mm
        for (x, y), (a, b) in zip(points(before, old), points(after, new), strict=True):
            assert a == pytest.approx(origin+(x-origin)*expected.scale_x+expected.dx_em*em)
            assert b == pytest.approx(old.baseline_mm+(y-old.baseline_mm)*expected.scale_y+expected.dy_em*em)
    path = tmp_path / "corrected.inkdoc"
    save_package(path, session, resolver, PageProfile(), StyleProfile(), flow=flow)
    restored = load_package(path)
    result = layout_markdown(parse_markdown(restored.session), restored.resolver, flow=restored.flow)
    assert asdict(result) == asdict(after)
    assert restored.flow == flow
    assert resolver.usage_warnings() == restored.resolver.usage_warnings()


def test_nested_footnotes_and_cache_never_double_correct(font):
    session = SourceSession("A[^a]\n\n[^a]: A")
    resolver = AssetResolver(embedded=font.glyphs(), builtin_numbers=True)
    cache = MarkdownBuildCache()
    args = (session, 1, resolver, "", "", PageProfile(), StyleProfile())
    before = build_markdown(*args, FlowStyle(), None, cache)["snapshot"]
    flow = FlowStyle(glyph_corrections=(GlyphCorrection(scope="document", dy_em=.1),))
    after = build_markdown(*args, flow, None, cache)["snapshot"]
    again = build_markdown(*args, flow, None, cache)["snapshot"]
    assert after == again
    for a, b in zip(before.fragments, after.fragments, strict=True):
        if a.asset_id:
            for p, q in zip(points(before, a), points(after, b), strict=True):
                assert q[0] == p[0]
                assert q[1] == pytest.approx(p[1] + a.glyph_em_mm*.1)
    restored = build_markdown(*args, FlowStyle(), None, cache)["snapshot"]
    assert page_svg(restored, 0) == page_svg(before, 0)


def test_outside_page_is_error_and_noop_is_exact(font):
    session = SourceSession("A")
    resolver = AssetResolver(embedded=font.glyphs())
    doc = parse_markdown(session)
    before = layout_markdown(doc, resolver)
    flow = FlowStyle(glyph_corrections=(GlyphCorrection(scope="document"),))
    noop = layout_markdown(doc, resolver, flow=flow)
    assert page_svg(noop, 0) == page_svg(before, 0)
    bad = layout_markdown(doc, resolver, flow=replace(flow, glyph_corrections=(
        GlyphCorrection(scope="document", dx_em=-2, dy_em=-2),)))
    assert not bad.exportable
    assert any(d.code == "glyph-correction-overflow" for d in bad.diagnostics)


@pytest.mark.parametrize("fields", [{"dx_em": float("nan")}, {"scale_x": 0},
    {"scope": "document", "character": "A"}, {"character": "AA", "occurrence_id": "x"},
    {"dx_em": True}, {"scope": "no"}, {"character": "A"}, {"scale_y": 5}])
def test_reject_invalid_corrections(fields):
    with pytest.raises(ValueError):
        GlyphCorrection(**fields)


@pytest.mark.parametrize("all_samples,count", [(False, 1), (True, 2)])
def test_derive_font_preserves_raw_dynamics_other_styles_and_source(font, tmp_path, all_samples, count):
    glyph = next(g for g in font.glyphs() if g.font_core["record"]["letter_style"] == "upright")
    before = hashlib.sha256(font.path.read_bytes()).hexdigest()
    output = tmp_path / "corrected.inkfont"
    rule = GlyphCorrection(scope="character", character="A", dx_em=.1, dy_em=-.1,
                           scale_x=.9, scale_y=1.1)
    result = correct_font(font.path, output, glyph, rule, all_samples=all_samples)
    assert len(result["corrected_candidates"]) == count
    assert hashlib.sha256(font.path.read_bytes()).hexdigest() == before
    derived = FontPackage(output)
    assert derived.verify()["candidates"] == 3
    assert derived.manifest["font_id"] == font.manifest["font_id"]
    assert derived.manifest["release_id"] != font.manifest["release_id"]
    assert derived.manifest["package_id"] != font.manifest["package_id"]
    with zipfile.ZipFile(output) as archive:
        for record in derived.records:
            cid = record["candidate_id"]
            summary = derived.provenance[cid]
            if "geometric_corrections" not in summary:
                assert record in font.records
                continue
            audit = summary["geometric_corrections"][-1]
            raw = decode(archive.read(audit["source_record"]))
            assert raw["identity"] == font.identity
            trajectory = decode(archive.read(record["file"]))
            for old, new in zip(raw["trajectory"]["strokes"], trajectory["strokes"], strict=True):
                assert old["dynamic_origin"] == new["dynamic_origin"]
                for a, b in zip(old["points"], new["points"], strict=True):
                    assert rule.point(a["x"], a["y"]) == pytest.approx((b["x"], b["y"]))
                    assert {k:v for k,v in a.items() if k not in {"x", "y"}} == {
                        k:v for k,v in b.items() if k not in {"x", "y"}}
            assert summary["author_source_status"] == raw["summary"]["author_source_status"]
            assert summary["warnings"] == raw["summary"]["warnings"]
    with pytest.raises(FileExistsError):
        correct_font(font.path, output, glyph, rule)
    exported = tmp_path / "user.inkfont"
    to_user(output, exported)
    assert FontPackage(exported).verify()["candidates"] == 3


def test_wrong_source_and_corrupt_geometry_do_not_publish(font, tmp_path):
    glyph = next(font.glyphs())
    bad = replace(glyph, original_json=json.dumps({**glyph.font_core, "identity": {}}).encode())
    with pytest.raises(ValueError, match="版本不一致"):
        correct_font(font.path, tmp_path/"bad.inkfont", bad,
                     GlyphCorrection(scope="character", character="A"))
    assert not (tmp_path/"bad.inkfont").exists()
    flow = FlowStyle(glyph_corrections=(GlyphCorrection(scope="document"),))
    with pytest.raises(ValueError):
        replace(flow, glyph_corrections=flow.glyph_corrections * 2)


def test_global_defaults_preserve_document_corrections():
    from inkstruct.global_defaults import LayoutDefaults, document_flow
    flow = FlowStyle(glyph_corrections=(GlyphCorrection(scope="document", dx_em=.1),))
    assert document_flow(LayoutDefaults(), flow).glyph_corrections == flow.glyph_corrections
    with pytest.raises(ValueError):
        LayoutDefaults(flow=flow)


def test_font_and_document_corrections_match_even_with_negative_bearings(font, tmp_path):
    session = SourceSession(r"AA $\mathrm{A}$")
    original = AssetResolver(embedded=font.glyphs())
    base_flow = FlowStyle(first_line_indent_mm=12)
    before = layout_markdown(parse_markdown(session), original, flow=base_flow)
    glyph = next(g for g in original.pools["A"] if g.asset_id == before.fragments[0].asset_id)
    rule = GlyphCorrection(scope="character", character="A", dx_em=-.2, dy_em=.06,
                           scale_x=.9, scale_y=1.1)
    rules = tuple(replace(rule, asset_id=g.asset_id) for g in original.pools["A"]
                  if g.font_core["record"]["letter_style"] == "upright")
    doc = layout_markdown(parse_markdown(session), original,
                          flow=replace(base_flow, glyph_corrections=rules))
    output = tmp_path/"same.inkfont"
    result = correct_font(font.path, output, glyph, rule, all_samples=True)
    derived = FontPackage(output)
    candidates = {g.sample_id:g for g in derived.glyphs()}
    mapping = {r["source_candidate_id"]:r["candidate_id"] for r in result["corrected_candidates"]}
    choices = []
    for choice in original.selections.values():
        g = candidates[mapping.get(choice.sample_id, choice.sample_id)]
        choices.append(replace(choice, asset_id=g.asset_id, sample_id=g.sample_id,
                               metrics_key=g.metrics_key))
    resolver = AssetResolver(embedded=candidates.values(), selections=choices)
    corrected_font = layout_markdown(parse_markdown(session), resolver, flow=base_flow)
    assert corrected_font.exportable, corrected_font.diagnostics
    assert page_svg(corrected_font,0) == page_svg(doc,0)


def test_template_fields_correct_once():
    from test_template_fields import setup
    _, doc, resolver, flow = setup(repeat=True)
    before = layout_markdown(doc, resolver, flow=flow)
    after = layout_markdown(doc, resolver, flow=replace(flow, glyph_corrections=(
        GlyphCorrection(scope="document", dy_em=.02),)))
    for p, q in zip(before.pages, after.pages, strict=True):
        original = {f.occurrence_id:f for f in p.fragments}
        for a, b in zip(p.paint_ops, q.paint_ops, strict=True):
            f = original.get(a.occurrence_id)
            if f and f.asset_id:
                for old, new in zip(a.points,b.points,strict=True):
                    assert new == pytest.approx((old[0],old[1]+f.glyph_em_mm*.02))
            else:
                assert a==b


def test_repeated_table_headers_and_source_identity_keep_optical_correction():
    from inkstruct.document.table_style import TableStyle
    session = SourceSession("|1|2|\n|---|---|\n" + "|3|4|\n"*18)
    resolver = AssetResolver(builtin_numbers=True)
    flow = FlowStyle(table=TableStyle(width_mm=55))
    page = PageProfile(80,70,5)
    before = layout_markdown(parse_markdown(session),resolver,flow=flow,page=page)
    assert any(f.repeated for f in before.fragments)
    target = next(f for f in before.fragments if f.text=="1")
    rule = GlyphCorrection(character="1",occurrence_id=target.occurrence_id,
                           asset_id=target.asset_id,dy_em=.02)
    after = layout_markdown(parse_markdown(session),resolver,page=page,
                            flow=replace(flow,glyph_corrections=(rule,)))
    for p,q in zip(before.pages,after.pages,strict=True):
        for a,b in zip(p.paint_ops,q.paint_ops,strict=True):
            if a.occurrence_id==target.occurrence_id:
                for old,new in zip(a.points,b.points,strict=True):
                    assert new==pytest.approx((old[0],old[1]+target.glyph_em_mm*.02))
            else:
                assert a==b
    session.apply(0,0,"\n\n")
    updated = layout_markdown(parse_markdown(session),resolver,page=page,
                              flow=replace(flow,glyph_corrections=(rule,)))
    assert any(f.occurrence_id==target.occurrence_id for f in updated.fragments)
    assert session.undo()
    restored = layout_markdown(parse_markdown(session),resolver,page=page,
                               flow=replace(flow,glyph_corrections=(rule,)))
    assert [page_svg(after,i) for i in range(len(after.pages))]==[
        page_svg(restored,i) for i in range(len(restored.pages))]


@pytest.mark.parametrize("frame", [None,{}, {"bounds":[0,1,2],"metrics":{}},
    {"bounds":[0,0,float("nan"),1],"metrics":{}},
    {"bounds":[1,0,0,1],"metrics":{}},
    {"bounds":[0,0,1,1],"metrics":{"advance":True,"baseline":.88,"ascent":.88,"descent":.12}}])
def test_bad_optical_frame_is_rejected(font,frame):
    from inkstruct.fonts.core import validate_summary
    summary=dict(next(font.glyphs()).font_core["summary"],optical_layout_frame=frame)
    with pytest.raises(ValueError):
        validate_summary(summary,len(next(font.glyphs()).strokes))


@pytest.mark.parametrize("scope", ["occurrence", "sample", "character"])
def test_three_ranges_update_exact_instances_and_preserve_other_characters(font, tmp_path, scope):
    from inkstruct.assets.resolver import SelectedAsset
    session=SourceSession(r"AAAA1 $A$")
    doc=parse_markdown(session)
    glyphs=list(font.glyphs())
    upright=[g for g in glyphs if g.font_core['record']['letter_style']=='upright']
    a1,a2=upright
    r=AssetResolver(embedded=glyphs,builtin_numbers=True)
    first=layout_markdown(doc,r)
    body=[f for f in first.fragments if f.text=='A'][:4]
    for f,g in zip(body,(a1,a2,a2,a1),strict=True):
        r.selections[f.occurrence_id]=SelectedAsset(f.occurrence_id,'A',g.asset_id,g.sample_id,g.metrics_key,
                                                   requested_style='upright',resolved_style='upright')
    first=layout_markdown(doc,r)
    selected=first.fragments[1]
    old=(GlyphCorrection(scope='document',dx_em=.01),
         GlyphCorrection(scope='character',character='A',dx_em=.02),
         GlyphCorrection(character='A',occurrence_id=body[1].occurrence_id,asset_id=a2.asset_id,dy_em=.03),
         GlyphCorrection(character='A',occurrence_id=body[2].occurrence_id,dy_em=.04),
         GlyphCorrection(character='A',occurrence_id=body[0].occurrence_id,asset_id=a1.asset_id,dy_em=.05))
    baseline=layout_markdown(doc,r,flow=FlowStyle(glyph_corrections=old))
    ids=(a1.asset_id,a2.asset_id) if scope=='character' else (a2.asset_id,)
    targets=tuple(GlyphCorrection(scope='occurrence' if scope=='occurrence' else 'character',character='A',
                                  asset_id=a,occurrence_id=selected.occurrence_id if scope=='occurrence' else '',
                                  dx_em=.06,dy_em=.01,scale_y=.95) for a in ids)
    updated=update_corrections(old,targets,first.fragments)
    flow=FlowStyle(glyph_corrections=updated)
    result=layout_markdown(doc,r,flow=flow)
    for f in first.fragments:
        if f.asset_id is None:
            continue
        expected=f.asset_id in ids and (scope!='occurrence' or f.occurrence_id==selected.occurrence_id)
        if expected:
            assert correction_for(updated,f) in targets
        else:
            assert correction_for(updated,f)==correction_for(old,f)
            assert points(baseline,f)==points(result,f)
    saved=tmp_path/f'{scope}.inkdoc'
    save_package(saved,session,r,PageProfile(),StyleProfile(),flow=flow)
    loaded=load_package(saved)
    reopened=layout_markdown(parse_markdown(loaded.session),loaded.resolver,flow=loaded.flow)
    assert page_svg(result,0)==page_svg(reopened,0)
    # Restoring really returns the target to its font, masking legacy broad rules.
    restored=update_corrections(updated,targets,first.fragments,reset=True)
    for f in first.fragments:
        if f.asset_id in ids and (scope!='occurrence' or f.occurrence_id==selected.occurrence_id):
            rule=correction_for(restored,f)
            assert rule is None or rule.point(.2,.3)==pytest.approx((.2,.3))


def test_explicit_cross_style_font_and_bad_scope_do_not_touch_source(font,tmp_path):
    glyph=next(g for g in font.glyphs() if g.font_core['record']['letter_style']=='upright')
    transform=GlyphCorrection(scope='character',character='A',dy_em=.02)
    result=correct_font(font.path,tmp_path/'cross-style.inkfont',glyph,transform,
                        all_samples=True,include_styles=True)
    assert len(result['corrected_candidates'])==3
    with pytest.raises(ValueError):
        correct_font(font.path,tmp_path/'invalid.inkfont',glyph,transform,include_styles=True)
    assert not (tmp_path/'invalid.inkfont').exists()


def test_failed_output_verification_never_publishes(font,tmp_path,monkeypatch):
    import inkstruct.fonts.corrections as module
    original=module.verify_font
    def verify(f,**options):
        if f.path.name=="corrected.inkfont":
            raise ValueError("injected final verification failure")
        return original(f,**options)
    monkeypatch.setattr(module,"verify_font",verify)
    output=tmp_path/"no-partial.inkfont"
    with pytest.raises(ValueError,match="injected"):
        correct_font(font.path,output,next(font.glyphs()),
                     GlyphCorrection(scope="character",character="A"))
    assert not output.exists()
