"""Script placement is checked against actual strokes, not advance/metric boxes."""

from dataclasses import asdict, replace

import pytest
from test_math_layout import math_node, resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle


def glyph_edges(g, pen=0.3):
    points = [
        (
            g.x_mm + g.origin_offset_mm + x * g.em_mm,
            g.baseline_mm + (y - g.glyph.metrics.baseline) * g.em_mm,
        )
        for stroke in g.glyph.strokes
        for x, y in stroke
    ]
    return (
        min(x for x, y in points) - pen / 2,
        min(y for x, y in points) - pen / 2,
        max(x for x, y in points) + pen / 2,
        max(y for x, y in points) + pen / 2,
    )


def measure(source, style=None, pen=0.3, display=False):
    n = math_node("$" + source + "$")
    return measure_math(
        n.math,
        resolver("1234+∑∏∫∮limnax"),
        owner=n.node_id,
        style=style,
        stroke_width=pen,
        display=display,
    )


@pytest.mark.parametrize("pen", [0.15, 0.3, 0.8])
@pytest.mark.parametrize("source", ["1_2^3", "1^3_2", r"\frac{1}{2}_3^4", r"\left(1\right)_2^3"])
def test_scripts_keep_ink_separate_for_thin_thick_pens_and_tall_bases(source, pen):
    box = measure(source, MathStyle(superscript_raise_em=0, subscript_drop_em=0), pen)
    base, scripts = box.glyphs[:-2], box.glyphs[-2:]
    right = max(glyph_edges(g, pen)[2] for g in base)
    if box.rules:
        right = max(right, max(x + pen / 2 for r in box.rules for x, y in r.points))
    for g in scripts:
        assert glyph_edges(g, pen)[0] - right >= pen * 0.5 - 1e-8
    upper, lower = sorted(scripts, key=lambda g: g.baseline_mm)
    assert glyph_edges(lower, pen)[1] - glyph_edges(upper, pen)[3] >= pen * 0.5 - 1e-8


def test_legacy_gap_ignored_and_positions_do_not_change_horizontal_spacing():
    source = "1_2^3"
    base = measure(source)
    legacy = measure(source, MathStyle(script_clearance_em=1.8))
    assert (legacy.width, legacy.ascent, legacy.descent) == (base.width, base.ascent, base.descent)
    assert [(g.x_mm, g.baseline_mm, g.em_mm, g.glyph) for g in legacy.glyphs] == [
        (g.x_mm, g.baseline_mm, g.em_mm, g.glyph) for g in base.glyphs
    ]
    changed = measure(source, MathStyle(superscript_raise_em=1.2, subscript_drop_em=1.1))
    assert [g.x_mm for g in base.glyphs] == [g.x_mm for g in changed.glyphs]
    assert changed.glyphs[1].baseline_mm > base.glyphs[1].baseline_mm
    assert changed.glyphs[2].baseline_mm < base.glyphs[2].baseline_mm


@pytest.mark.parametrize(
    "command", [r"\sum", r"\sum\nolimits", r"\int", r"\int\limits", r"\prod", r"\oint"]
)
@pytest.mark.parametrize("display", [True, False])
def test_limit_scale_independent_of_regular_scripts_and_operator_size(command, display):
    style = MathStyle(script_scale=0.5, limits_scale=0.9, large_operator_scale=1.5)
    box = measure(command + "_{1}^{2}+3^4", style, display=display)
    assert [g.em_mm for g in box.glyphs[:3]] == pytest.approx([9, 5.4, 5.4])
    assert box.glyphs[-1].em_mm == 3
    smaller = measure(command + "_{1}^{2}+3^4", replace(style, limits_scale=0.6), display=display)
    assert [g.em_mm for g in smaller.glyphs[:3]] == pytest.approx([9, 3.6, 3.6])
    assert smaller.glyphs[-1].em_mm == 3


def test_legacy_scale_migration_and_independent_ratio_roundtrip(tmp_path):
    legacy = asdict(MathStyle(script_scale=0.83))
    legacy.pop("limits_scale")
    flow = FlowStyle(math=legacy)
    assert flow.math.limits_scale == 0.83
    flow = replace(flow, math=replace(flow.math, script_scale=0.55))
    assert flow.math.limits_scale == 0.83
    path = tmp_path / "limits.inkdoc"
    save_package(
        path,
        SourceSession(r"$\sum_{1}^{2}$"),
        resolver("12∑"),
        PageProfile(),
        StyleProfile(),
        flow=flow,
    )
    assert load_package(path).flow.math == flow.math
    with pytest.raises(ValueError):
        MathStyle(limits_scale=0.2)
