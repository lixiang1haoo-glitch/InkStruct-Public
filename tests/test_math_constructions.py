"""Array rules, pen clearances, accents and compact matrices retain source ink."""

from collections import Counter
from dataclasses import asdict, replace

import pytest
from test_math_alignment import measured
from test_math_layout import resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.parser import ACCENTS, parse_math
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page
from inkstruct.plotter.svg import page_svg


def array(body, spec="lcr", position=""):
    return r"\begin{array}" + position + "{" + spec + "}" + body + r"\end{array}"


def test_array_rules_keep_exact_source_locations_and_pad_missing_cells():
    raw = array(r"\hline 1&2&3\\\cline{2-3}44&55\\\hline\hline", "|l||cr|")
    p = parse_math(raw, offset=11)
    assert p.valid, p.diagnostics
    n = p.root.children[0]
    assert n.kind == "Array"
    assert dict(n.attributes)["columns"] == "lcr"
    rows = [c for c in n.children if c.kind == "ArrayRow"]
    assert len(rows) == 2 and len(rows[-1].children) == 3
    assert not rows[-1].children[-1].children
    for rule in (c for c in n.children if c.kind == "ArrayRule"):
        token = raw[rule.span.start - 11 : rule.span.end - 11]
        assert token in {"|", r"\hline", r"\cline{2-3}"}


@pytest.mark.parametrize("position", ["t", "c", "b"])
def test_array_column_alignment_baseline_and_double_rules(position):
    box = measured(
        array(r"\hline 1&2&3\\\hline\hline 44&55&66\\\hline", "|l||cr|", "[" + position + "]")
    )
    assert box.ready, box.diagnostics
    a, b, c, d, _e, f, g, _h, i = box.glyphs
    assert a.x_mm == pytest.approx(d.x_mm)
    assert b.x_mm + b.advance_mm / 2 == pytest.approx((f.x_mm + g.x_mm + g.advance_mm) / 2)
    assert c.x_mm + c.advance_mm == pytest.approx(i.x_mm + i.advance_mm)
    if position == "t":
        assert a.baseline_mm == pytest.approx(0)
    elif position == "b":
        assert d.baseline_mm == pytest.approx(0)
    else:
        assert (box.descent - box.ascent) / 2 == pytest.approx(-box.axis)
    vertical = [r for r in box.rules if "array-vertical" in r.occurrence_id]
    horizontal = [r for r in box.rules if "array-horizontal" in r.occurrence_id]
    assert len(vertical) == len(horizontal) == 4
    assert vertical[0].points[0][1] == horizontal[0].points[0][1]
    assert vertical[-1].points[-1] == horizontal[-1].points[-1]
    assert vertical[2].points[0][0] - vertical[1].points[0][0] >= 0.6
    # Ink on either side of the double horizontal separator remains clear.
    assert horizontal[1].points[0][1] - 0.15 - (a.baseline_mm + a.descent_mm) >= 0.72 - 1e-9
    assert d.baseline_mm - d.ascent_mm - (horizontal[2].points[0][1] + 0.15) >= 0.72 - 1e-9


def test_partial_lines_empty_rows_and_pen_floor():
    box = measured(
        array(r"\cline{1-1}\cline{3-3}1&2&3\\\\4&5&6\\", "lll"),
        MathStyle(matrix_row_gap_em=0, matrix_col_gap_em=0, array_rule_clearance_em=0),
    )
    assert box.ready and len(box.rules) == 2
    a, b = box.rules
    assert a.points[-1][0] < b.points[0][0]
    assert box.glyphs[-1].baseline_mm - box.glyphs[0].baseline_mm > 2 * 6
    first = box.glyphs[0]
    assert first.baseline_mm - first.ascent_mm - (a.points[0][1] + 0.15) >= 0.45 - 1e-9


@pytest.mark.parametrize(
    "raw, code",
    [
        (array("1", "p{2cm}"), "math-array-format"),
        (array("1", "|||l"), "math-array-format"),
        (array("1", ""), "math-array-budget"),
        (array("1", "l" * 9), "math-array-budget"),
        (array("1&2", "l"), "math-array-columns"),
        (array("", "c"), "math-array-empty"),
        (array("1", "c", "[x]"), "math-array-option"),
        (array(r"1\\[2mm]2", "c"), "math-array-option"),
        (array(r"1\\*2", "c"), "math-array-option"),
        (array(r"\cline{0-2}1"), "math-array-rule"),
        (array(r"\cline{2-1}1"), "math-array-rule"),
        (array(r"\cline{1-4}1"), "math-array-rule"),
        (array(r"\cline{a}1"), "math-array-rule"),
        (array(r"\hline\hline\hline 1"), "math-array-rule-overlap"),
        (array(r"\hline\cline{1-2}1"), "math-array-rule-overlap"),
        (array(r"\cline{1-2}\cline{2-3}1"), "math-array-rule-overlap"),
        (array(r"1\hline"), "math-array-rule-position"),
        (array(r"\\".join("1" * 33), "l"), "math-array-budget"),
        (r"\begin{array}{c}1\end{matrix}", "math-environment"),
        (r"\begin{array}{c}1", "math-environment"),
        (r"\vec{}", "math-empty"),
        (r"\hat", "math-argument"),
        (r"\vec" * 40 + "1", "math-depth"),
    ],
)
def test_unsupported_syntax_is_diagnosed(raw, code):
    p = parse_math(raw)
    assert not p.valid and p.diagnostics[0].code == code
    assert 0 <= p.diagnostics[0].span.start <= p.diagnostics[0].span.end <= len(raw)


@pytest.mark.parametrize("name", sorted(ACCENTS))
def test_accents_preserve_original_glyph_and_source_and_have_real_pen_clearance(name):
    plain = measured("12")
    box = measured("\\" + name + "{12}", MathStyle(accent_clearance_em=0, accent_height_em=0))
    assert box.ready
    assert len(box.glyphs) == 2 and box.rules
    for old, new in zip(plain.glyphs, box.glyphs):
        assert old.glyph.asset_id == new.glyph.asset_id
        assert old.glyph.strokes == new.glyph.strokes
        assert new.em_mm == old.em_mm and new.baseline_mm == old.baseline_mm
        assert new.x_mm - box.glyphs[0].x_mm == old.x_mm - plain.glyphs[0].x_mm
    ys = [y for r in box.rules for x, y in r.points]
    if name == "underline":
        assert min(ys) - 0.15 - plain.descent >= 0.45 - 1e-9
        assert box.descent > plain.descent
    else:
        assert -plain.ascent - (max(ys) + 0.15) >= 0.45 - 1e-9
        assert box.ascent > plain.ascent
    for rule in box.rules:
        assert all(a != b for a, b in zip(rule.points, rule.points[1:]))
        assert min(x for x, y in rule.points) >= 0.15 - 1e-9
        assert max(x for x, y in rule.points) <= box.width - 0.15 + 1e-9


def test_nested_accents_scripts_and_compact_matrix_axis():
    box = measured(r"\vec{\widehat{12}}_3^4")
    assert box.ready and len(box.rules) == 3
    assert box.glyphs[-1].baseline_mm + box.glyphs[-1].descent_mm < -6
    raw = r"\begin{smallmatrix}1&2\\3&4\end{smallmatrix}"
    compact = measured(raw)
    normal = measured(raw.replace("smallmatrix", "matrix"))
    assert compact.width < normal.width and compact.ascent < normal.ascent
    assert {g.em_mm for g in compact.glyphs} == {6 * 0.7}
    assert (compact.descent - compact.ascent) / 2 == pytest.approx(-compact.axis)
    full = measured(raw, MathStyle(small_matrix_scale=1))
    assert (full.width, full.ascent, full.descent) == pytest.approx(
        (normal.width, normal.ascent, normal.descent)
    )


def test_new_settings_are_optional_and_bounded():
    old = asdict(MathStyle())
    for key in (
        "small_matrix_scale",
        "accent_clearance_em",
        "accent_height_em",
        "array_rule_clearance_em",
    ):
        old.pop(key)
        for value in (-1, 3, float("nan")):
            with pytest.raises(ValueError):
                replace(MathStyle(), **{key: value})
    assert MathStyle(**old) == MathStyle()


def test_document_numbered_array_inline_table_footnote_and_machine_roundtrip(tmp_path):
    raw = array(r"\hline\vec{1}&\frac{2}{3}\\\cline{1-1}\ddot{4}&5\\\hline", "|lr|")
    source = (
        "$$\n"
        + raw
        + r"\tag{1}\label{array}"
        + "\n$$\n\n6[^a]\n\n|7|\n|---|\n|$"
        + raw.replace("|", r"\|")
        + "$|\n\n[^a]: $"
        + raw
        + "$ $\\eqref{array}$"
    )
    session = SourceSession(source)
    doc = parse_markdown(session)
    assert not doc.diagnostics
    r = resolver()
    flow = FlowStyle(
        math=MathStyle(accent_height_em=0.3, array_rule_clearance_em=0.2, small_matrix_scale=0.8)
    )
    s = layout_markdown(doc, r, flow=flow)
    assert s.plotter_exportable, s.diagnostics
    expected = Counter(o.occurrence_id for o in doc.occurrences)
    assert Counter(f.occurrence_id for f in s.fragments if not f.repeated) == expected
    canonical = lambda pts: min(pts, tuple(reversed(pts)))
    for p in plan_from_snapshot(s).pages:
        routed = route_page(p, optimize=True).page
        assert Counter(canonical(st.points) for st in p.strokes) == Counter(
            canonical(st.points) for st in routed.strokes
        )
        assert "<path" in page_svg(routed)
    path = tmp_path / "constructions.inkdoc"
    save_package(path, session, r, s.page_profile, StyleProfile(), flow=flow)
    p = load_package(path)
    assert layout_markdown(parse_markdown(p.session), p.resolver, flow=p.flow) == s
    session.apply(0, 0, "2\n\n")
    assert set(expected) <= {o.occurrence_id for o in parse_markdown(session).occurrences}
    session.undo()
    assert parse_markdown(session).occurrences == doc.occurrences


def test_oversize_array_remains_atomic_and_fails_finitely():
    raw = array(r"\\".join("1&2" for _ in range(32)), "lr")
    s = layout_markdown(
        parse_markdown("$$\n" + raw + "\n$$"), resolver(), page=PageProfile(40, 40, 5)
    )
    assert not s.exportable and len(s.pages) < 3
    assert any("overflow" in d.code for d in s.diagnostics)
