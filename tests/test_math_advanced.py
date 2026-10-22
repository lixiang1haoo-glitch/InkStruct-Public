"""Construction delimiters, limits and matrix geometry, without font outlines."""

import pytest
from test_math_auto_scripts import glyph_edges
from test_math_layout import math_node, resolver

from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg


def measured(source, *, display=False):
    n = math_node(source)
    return measure_math(n.math, resolver("0123456789+=−∑∫∮lim"), owner=n.node_id, display=display)


@pytest.mark.parametrize(
    "left,right,paths",
    [
        ("(", ")", 2),
        ("[", "]", 2),
        (r"\{", r"\}", 2),
        (r"\langle", r"\rangle", 2),
        (r"\vert", r"\vert", 2),
        (r"\Vert", r"\Vert", 4),
        (".", ")", 1),
    ],
)
def test_delimiters_are_constructions_with_source_spans_and_ink_clearance(left, right, paths):
    source = "$\\left" + left + r"\frac{1}{2}\right" + right + "$"
    box = measured(source)
    assert box.ready
    delimiters = [r for r in box.rules if "delimiter-" in r.occurrence_id]
    assert len(delimiters) == paths
    assert len({r.occurrence_id for r in delimiters}) == paths
    for rule in delimiters:
        raw = source[rule.span.start : rule.span.end]
        assert raw in (left, right)
        ys = [y for _, y in rule.points]
        assert min(ys) < min(g.baseline_mm - g.ascent_mm for g in box.glyphs)
        assert max(ys) > max(g.baseline_mm + g.descent_mm for g in box.glyphs)
        for glyph in box.glyphs:
            if "delimiter-left" in rule.occurrence_id:
                assert max(x for x, _ in rule.points) + 0.15 + 0.72 <= glyph.x_mm + 1e-9
            else:
                assert (
                    min(x for x, _ in rule.points) - 0.15 - 0.72
                    >= glyph.x_mm + glyph.advance_mm - 1e-9
                )
    # Construction delimiters do not demand fake or stretched captured bracket assets.
    assert "".join(g.occurrence.text for g in box.glyphs) == "12"


@pytest.mark.parametrize(
    "command,display,stacked",
    [
        (r"\sum", False, False),
        (r"\sum", True, True),
        (r"\sum\limits", False, True),
        (r"\sum\nolimits", True, False),
        (r"\int", True, False),
        (r"\int\limits", True, True),
        (r"\oint\nolimits", True, False),
        (r"\lim", True, True),
    ],
)
def test_operator_limits_follow_context_and_explicit_policy(command, display, stacked):
    box = measured("$" + command + "_{1}^{2}$", display=display)
    assert box.ready
    base, sub, sup = box.glyphs[:-2], box.glyphs[-2], box.glyphs[-1]
    left = min(g.x_mm for g in base)
    right = max(g.x_mm + g.advance_mm for g in base)
    if stacked:
        assert sub.x_mm + sub.advance_mm / 2 == pytest.approx((left + right) / 2)
        assert sup.x_mm + sup.advance_mm / 2 == pytest.approx((left + right) / 2)
        assert (
            sup.baseline_mm + sup.descent_mm + 0.72
            <= min(g.baseline_mm - g.ascent_mm for g in base) + 1e-9
        )
        assert (
            sub.baseline_mm - sub.ascent_mm - 0.72
            >= max(g.baseline_mm + g.descent_mm for g in base) - 1e-9
        )
    else:
        assert min(glyph_edges(sub)[0], glyph_edges(sup)[0]) > max(glyph_edges(g)[2] for g in base)


@pytest.mark.parametrize(
    "environment,count",
    [
        ("matrix", 0),
        ("pmatrix", 2),
        ("bmatrix", 2),
        ("Bmatrix", 2),
        ("vmatrix", 2),
        ("Vmatrix", 4),
        ("cases", 1),
    ],
)
def test_matrix_rows_columns_axis_and_case_alignment(environment, count):
    source = "$\\begin{" + environment + r"}1&22\\333&4\end{" + environment + "}$"
    box = measured(source)
    assert box.ready and len(box.rules) == count
    one, two1, two2, three1, _three2, three3, four = box.glyphs
    assert one.baseline_mm == two1.baseline_mm == two2.baseline_mm
    assert three1.baseline_mm == four.baseline_mm > one.baseline_mm
    assert one.baseline_mm + one.descent_mm < three1.baseline_mm - three1.ascent_mm
    if environment == "cases":
        assert one.x_mm == three1.x_mm
        assert two1.x_mm == four.x_mm
    else:
        assert one.x_mm + one.advance_mm / 2 == pytest.approx(
            (three1.x_mm + three3.x_mm + three3.advance_mm) / 2
        )
        assert four.x_mm + four.advance_mm / 2 == pytest.approx(
            (two1.x_mm + two2.x_mm + two2.advance_mm) / 2
        )
    if environment == "matrix":
        assert (box.descent - box.ascent) / 2 == pytest.approx(-box.axis)


def test_nested_matrix_and_display_limits_keep_all_instances_and_rules_in_export():
    source = (
        "$$\n"
        + r"\sum_{1}^{2}\left(\begin{pmatrix}\frac{1}{2}&3\\4&\sqrt{5}\end{pmatrix}\right)"
        + "\n$$"
    )
    doc = parse_markdown(source)
    result = layout_markdown(doc, resolver("12345−∑"))
    assert result.exportable, result.diagnostics
    assert [f.occurrence_id for f in result.fragments] == [o.occurrence_id for o in doc.occurrences]
    rules = [op for p in result.pages for op in p.paint_ops if ":math-rule:" in op.occurrence_id]
    assert len(rules) == len({r.occurrence_id for r in rules}) == 6
    for page in plan_from_snapshot(result).pages:
        page_svg(page)
    small = layout_markdown(doc, resolver("12345∑"), page=PageProfile(30, 30, 5))
    assert not small.exportable
    assert any("overflow" in d.code for d in small.diagnostics)


def test_bare_bracket_still_requires_a_sample_and_unsupported_syntax_is_blocked():
    result = layout_markdown(parse_markdown("$(1)$"), resolver("1"))
    assert not result.exportable and any(d.code == "asset-missing" for d in result.diagnostics)
    result = layout_markdown(parse_markdown(r"$\begin{align}1&=2\end{align}$"), resolver())
    assert not result.exportable


def test_scripts_follow_tall_base_corner_and_display_mode_does_not_leak_into_fraction():
    short = measured("$1^2$")
    tall = measured(r"$\left(\frac{1}{3}\right)^2$")
    assert tall.glyphs[-1].baseline_mm < short.glyphs[-1].baseline_mm - 2
    nested = measured(r"$\frac{\sum_{1}^{2}3}{4}$", display=True)
    operator, sub, sup = nested.glyphs[:3]
    assert min(glyph_edges(sub)[0], glyph_edges(sup)[0]) > glyph_edges(operator)[2]
    explicit = measured(r"$\frac{\sum\limits_{1}^{2}3}{4}$", display=True)
    operator, sub, sup = explicit.glyphs[:3]
    assert sub.x_mm + sub.advance_mm / 2 == pytest.approx(operator.x_mm + operator.advance_mm / 2)
