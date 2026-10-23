"""Settings change real geometry, preserve raw trajectories and respect pen clearance."""

from dataclasses import replace

import pytest
from test_math_layout import math_node, resolver

from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle


def measure(source, style=None):
    n = math_node("$" + source + "$")
    return measure_math(n.math, resolver("0123456789+−∑∫"), owner=n.node_id, style=style)


def test_script_fraction_root_matrix_and_delimiter_dimensions_are_effective():
    for source, key in [
        (r"\frac{12}{3}", "fraction_clearance_em"),
        (r"\sqrt{12}", "radical_clearance_em"),
        (r"\begin{matrix}1&2\\3&4\end{matrix}", "matrix_col_gap_em"),
        (r"\left(12\right)", "delimiter_width_em"),
        (r"\left(12\right)", "delimiter_clearance_em"),
    ]:
        before = measure(source)
        after = measure(source, replace(MathStyle(), **{key: 1.1}))
        assert after.ready and after.width > before.width
        assert [g.glyph.original_json for g in before.glyphs] == [
            g.glyph.original_json for g in after.glyphs
        ]
    source = r"\begin{matrix}1&2\\3&4\end{matrix}"
    a, b = measure(source), measure(source, MathStyle(matrix_row_gap_em=1.2))
    assert b.ascent + b.descent > a.ascent + a.descent
    a, b = measure("1^2"), measure("1^2", MathStyle(superscript_raise_em=1.5))
    assert b.glyphs[1].baseline_mm < a.glyphs[1].baseline_mm
    a, b = measure("1_2"), measure("1_2", MathStyle(subscript_drop_em=1.5))
    assert b.glyphs[1].baseline_mm > a.glyphs[1].baseline_mm


def test_large_operator_scales_isotropically_about_the_parent_math_axis():
    result = measure(r"\sum_{1}^{3}2", MathStyle(large_operator_scale=1.8))
    operator = result.glyphs[0]
    assert operator.em_mm == pytest.approx(10.8)
    assert operator.baseline_mm - 0.25 * operator.em_mm == pytest.approx(-1.5)
    assert result.glyphs[-1].em_mm == 6
    a = measure(r"\sum\limits_{1}^{3}2")
    b = measure(r"\sum\limits_{1}^{3}2", MathStyle(limits_clearance_em=1))
    assert b.ascent + b.descent > a.ascent + a.descent


def test_zero_requested_clearance_keeps_minimum_pen_separation():
    result = measure(r"\frac{1}{2}", MathStyle(fraction_source="geometric", fraction_clearance_em=0))
    line = result.rules[0].points[0][1]
    n, d = result.glyphs
    assert line - 0.15 - (n.baseline_mm + n.descent_mm) >= 0.45 - 1e-9
    assert d.baseline_mm - d.ascent_mm - (line + 0.15) >= 0.45 - 1e-9
    for key in ("matrix_row_gap_em", "delimiter_width_em", "fraction_clearance_em"):
        with pytest.raises(ValueError):
            MathStyle(**{key: float("nan")})
    with pytest.raises(ValueError):
        MathStyle(large_operator_scale=4)
