import json
from dataclasses import replace

import pytest
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import SymbolProvider, adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan


def resolver(chars="0123456789.+−=×αmVsincostext", *, axis=0.25):
    glyphs = []
    for char in dict.fromkeys(chars):
        raw = specimen(char=char, sid=char)
        if axis is not None:
            raw["guides"]["math_axis_em"] = axis
        glyphs.append(adapt_symbol(json.dumps(raw).encode()))
    return AssetResolver(symbols=SymbolProvider(glyphs))


def math_node(source):
    doc = parse_markdown(source)
    return next(n for root in doc.nodes for n in root.walk() if n.math)


def test_spacing_unary_sign_and_axis_use_semantics_not_glyph_bounding_box():
    r = resolver()
    n = math_node("$−1+2=3$")
    s = MathStyle(em_mm=10, axis_em=0.4)
    box = measure_math(n.math, r, owner=n.node_id, style=s)
    assert box.ready
    by_text = {g.occurrence.text: g for g in box.glyphs}
    assert by_text["−"].baseline_mm == pytest.approx(-1.5)
    assert by_text["+"].baseline_mm == by_text["="].baseline_mm == pytest.approx(-1.5)
    assert by_text["1"].baseline_mm == 0
    minus, one, plus, two, equal, three = box.glyphs
    assert one.x_mm == pytest.approx(minus.advance_mm)  # Unary sign adds no binary gap.
    assert plus.x_mm - one.x_mm - one.advance_mm == pytest.approx(1.8)
    assert equal.x_mm - two.x_mm - two.advance_mm == pytest.approx(2.8)
    assert three.x_mm - equal.x_mm - equal.advance_mm == pytest.approx(2.8)
    assert box.axis == 4


def test_math_is_atomic_in_paragraph_and_each_symbol_keeps_its_trajectory():
    r = resolver()
    source = "1 2 3 $1+2=3$ 4 5 6"
    doc = parse_markdown(source)
    result = layout_markdown(doc, r, page=PageProfile(35, 80, 4))
    assert result.exportable, result.diagnostics
    formula = math_node(source)
    # Use the actual document's IDs, not a newly parsed independent source.
    formula = next(n for root in doc.nodes for n in root.walk() if n.math)
    fs = [f for f in result.fragments if f.node_id == formula.node_id]
    assert len({(f.page_index, f.line_index) for f in fs}) == 1
    assert [f.occurrence_id for f in result.fragments] == [o.occurrence_id for o in doc.occurrences]
    lookup = {g.asset_id: g for pool in r.pools.values() for g in pool}
    for fragment in fs:
        glyph = lookup[fragment.asset_id]
        strokes = [
            p
            for p in result.pages[fragment.page_index].paint_ops
            if p.occurrence_id == fragment.occurrence_id
        ]
        assert len(strokes) == len(glyph.strokes)
        for actual, raw in zip(strokes, glyph.strokes):
            assert len(actual.points) == len(raw)
            origin = (actual.points[0][0] - raw[0][0] * 6, actual.points[0][1] - raw[0][1] * 6)
            for point, src in zip(actual.points, raw):
                assert point == pytest.approx((origin[0] + src[0] * 6, origin[1] + src[1] * 6))


def test_display_alignment_pagination_and_oversize_formula_fail_without_splitting():
    r = resolver()
    doc = parse_markdown("1\n\n$$\n1+2=3\n$$\n\n2")
    page = PageProfile(50, 50, 5)
    centered = layout_markdown(doc, r, page=page)
    left = layout_markdown(doc, r, page=page, flow=FlowStyle(math=MathStyle(display_align="left")))
    n = next(n for n in doc.nodes if n.kind == "math_block")
    a = [f for f in centered.fragments if f.node_id == n.node_id]
    b = [f for f in left.fragments if f.node_id == n.node_id]
    assert a[0].x_mm > b[0].x_mm == 5
    assert len({f.page_index for f in a}) == 1
    bad = layout_markdown(parse_markdown("$" + "1" * 50 + "$"), r, page=page)
    assert not bad.exportable
    assert any(d.code == "line-width-overflow" for d in bad.diagnostics)
    assert len({(f.page_index, f.line_index) for f in bad.fragments}) == 1
    with pytest.raises(ValueError):
        plan_from_snapshot(bad)


def test_math_size_is_independent_from_numeric_table_height_and_persists(tmp_path):
    session = SourceSession("|1|2|\n|---|---|\n|1.20|$1+2$|")
    doc = parse_markdown(session)
    r = resolver()
    flow = FlowStyle(math=MathStyle(em_mm=7.125, axis_em=0.3))
    a = layout_markdown(doc, r, flow=flow)
    assert a.exportable, a.diagnostics
    other = replace(flow, table=replace(flow.table, digit_height_mm=2))
    b = layout_markdown(doc, r, flow=other)
    n = next(n for root in doc.nodes for n in root.walk() if n.math)
    af = [f for f in a.fragments if f.node_id == n.node_id]
    bf = [f for f in b.fragments if f.node_id == n.node_id]
    assert [f.advance_mm for f in af] == [f.advance_mm for f in bf]
    assert (
        a.pages[0].fragments[-1].logical_bounds[3] - a.pages[0].fragments[-1].logical_bounds[1] > 5
    )
    file = tmp_path / "math.inkdoc"
    save_package(file, session, r, PageProfile(), StyleProfile(), flow=flow)
    loaded = load_package(file)
    assert loaded.flow == flow
    assert layout_markdown(parse_markdown(loaded.session), loaded.resolver, flow=loaded.flow) == a
    out = tmp_path / "machine"
    export_plan(plan_from_snapshot(a), out, optimize=True)
    assert (out / "page-001.svg").exists()


def test_missing_axis_and_unsupported_syntax_are_not_silent_fallbacks():
    doc = parse_markdown("$1+2$")
    result = layout_markdown(doc, resolver(axis=None))
    assert not result.exportable and any(d.code == "math-axis-missing" for d in result.diagnostics)
    result = layout_markdown(parse_markdown("$1+x$"), resolver("1+"))
    assert not result.exportable and any(d.code == "asset-missing" for d in result.diagnostics)
    result = layout_markdown(parse_markdown(r"$\overbrace{1}$"), resolver())
    assert not result.exportable and any(
        d.code == "math-command-unsupported" for d in result.diagnostics
    )
    with pytest.raises(ValueError):
        plan_from_snapshot(result)


def test_functions_greek_and_units_use_individual_source_instances_and_em():
    doc = parse_markdown(r"$\sin \alpha+2\,\mathrm{m}+\text{V}$")
    r = resolver()
    source = {g.asset_id: g.original_json for p in r.pools.values() for g in p}
    result = layout_markdown(doc, r)
    assert result.exportable, result.diagnostics
    assert "".join(f.text for f in result.fragments) == "sinα+2m+V"
    assert [f.occurrence_id for f in result.fragments] == [o.occurrence_id for o in doc.occurrences]
    assert source == {g.asset_id: g.original_json for p in r.pools.values() for g in p}
    # Greek samples here are synthetic fixtures, not a claim of real resource availability.
