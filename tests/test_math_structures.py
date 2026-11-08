"""Independent geometric invariants for scripts, fraction rules and radicals."""

from dataclasses import replace

import pytest
from test_math_auto_scripts import glyph_edges
from test_math_layout import math_node, resolver

from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg


def measured(source, **kwargs):
    n = math_node(source)
    return measure_math(n.math, resolver(), owner=n.node_id, **kwargs)


@pytest.mark.parametrize("source", ["$1_2^3$", "$1^3_2$"])
def test_scripts_preserve_source_order_and_have_clearance(source):
    box = measured(source)
    base = box.glyphs[0]
    by_text = {g.occurrence.text: g for g in box.glyphs}
    sub, sup = by_text["2"], by_text["3"]
    assert "".join(g.occurrence.text for g in box.glyphs) == source.replace("$", "").replace(
        "_", ""
    ).replace("^", "")
    assert sub.em_mm == sup.em_mm == pytest.approx(4.2)
    assert glyph_edges(sub)[0] > glyph_edges(base)[2]
    assert glyph_edges(sub)[1] > glyph_edges(sup)[3]
    assert sup.baseline_mm < 0 < sub.baseline_mm
    assert box.ascent >= sup.ascent_mm - sup.baseline_mm
    assert box.descent >= sub.descent_mm + sub.baseline_mm


@pytest.mark.parametrize("command,em", [("frac", 4.8), ("tfrac", 4.8), ("dfrac", 6)])
def test_fraction_axis_and_rule_separate_both_operands(command, em):
    # This invariant covers the retained, explicitly selected geometric mode.
    box = measured("$\\" + command + "{12}{3}$", style=MathStyle(fraction_source="geometric"))
    assert box.ready
    assert len(box.rules) == 1
    line = box.rules[0]
    assert all(y == -1.5 for _, y in line.points)
    assert all(g.em_mm == pytest.approx(em) for g in box.glyphs)
    for glyph in box.glyphs[:2]:
        assert glyph.baseline_mm + glyph.descent_mm <= -1.5 - 0.15 - 0.72 + 1e-9
    denom = box.glyphs[-1]
    assert denom.baseline_mm - denom.ascent_mm >= -1.5 + 0.15 + 0.72 - 1e-9
    assert line.points[0][0] < denom.x_mm < line.points[-1][0]


@pytest.mark.parametrize("source", [r"$\sqrt{12}$", r"$\sqrt[3]{12}$", r"$\sqrt{\frac{12}{3}}$"])
def test_radical_is_one_polyline_clear_of_content(source):
    box = measured(source)
    assert box.ready
    root = next(r for r in box.rules if ":radical:" in r.occurrence_id)
    assert len(root.points) == 5
    top = root.points[-1][1]
    assert root.points[-2][1] == top
    content = [g for g in box.glyphs if g.occurrence.text in "12"]
    for glyph in content:
        assert glyph.x_mm > root.points[-2][0]
        assert glyph.baseline_mm - glyph.ascent_mm > top + 0.15
    assert box.ascent >= -top + 0.15
    if "[3]" in source:
        degree = box.glyphs[0]
        assert degree.occurrence.text == "3"
        assert degree.x_mm + degree.advance_mm < root.points[0][0]


def test_nested_geometry_preserves_points_and_source_identity_and_exports_rules_once():
    source = r"$1_{2^3}+\frac{4}{\sqrt[5]{6}}$"
    doc = parse_markdown(source)
    r = resolver()
    snapshot = layout_markdown(doc, r)
    assert snapshot.exportable, snapshot.diagnostics
    assert [f.occurrence_id for f in snapshot.fragments] == [
        o.occurrence_id for o in doc.occurrences
    ]
    rules = [p for p in snapshot.pages[0].paint_ops if ":math-rule:" in p.occurrence_id]
    assert len(rules) == len({p.occurrence_id for p in rules}) == 2
    box = measured(source)
    glyphs = {g.occurrence.text: g for g in box.glyphs}
    for f in snapshot.fragments:
        g = glyphs[f.text]
        actual = [p for p in snapshot.pages[0].paint_ops if p.occurrence_id == f.occurrence_id]
        for path, original in zip(actual, g.glyph.strokes, strict=True):
            assert len(path.points) == len(original)
            ox, oy = (path.points[0][i] - original[0][i] * g.em_mm for i in (0, 1))
            for point, raw in zip(path.points, original):
                assert point == pytest.approx((ox + raw[0] * g.em_mm, oy + raw[1] * g.em_mm))
    plan = plan_from_snapshot(snapshot)
    assert len(plan.pages[0].strokes) == len(snapshot.pages[0].paint_ops)
    assert "<path " in page_svg(plan.pages[0])


def test_small_nested_scripts_and_thick_pen_block_export():
    box = measured("$1^{2^{3^{4^5}}}$")
    assert not box.ready and any(d.code == "math-size-limit" for d in box.diagnostics)
    box = measured("$1^2$", stroke_width=1)
    assert not box.ready
    with pytest.raises(ValueError):
        MathStyle(script_scale=0.1)


def test_tall_formula_expands_table_or_reports_fixed_height_and_stays_on_one_page():
    source = "|1|2|\n|---|---|\n|1|$\\frac{12}{\\sqrt{3}}$|"
    doc = parse_markdown(source)
    flow = FlowStyle()
    good = layout_markdown(doc, resolver(), flow=flow)
    assert good.exportable, good.diagnostics
    # All actual ink, including the construction lines, stays within page bounds.
    for page in plan_from_snapshot(good).pages:
        page_svg(page)
    fixed = replace(flow, table=replace(flow.table, fixed_row_height=True))
    bad = layout_markdown(doc, resolver(), flow=fixed)
    assert not bad.exportable
    assert any("height" in d.code or "overflow" in d.code for d in bad.diagnostics)
    body = parse_markdown("1\n\n$$\n\\frac{12}{3}\n$$")
    result = layout_markdown(body, resolver(), page=PageProfile(60, 40, 5))
    assert result.exportable
    formula = [f for f in result.fragments if f.node_id == body.nodes[-1].node_id]
    assert len({f.page_index for f in formula}) == 1
