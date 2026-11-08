"""Explicit row/column anchors, source identities, and atomic page integration."""

import math
from collections import Counter
from dataclasses import asdict, replace

import pytest
from test_math_layout import resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.parser import parse_math
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page


def measured(raw, style=None):
    doc = parse_markdown("$$\n" + raw + "\n$$")
    assert not doc.diagnostics, doc.diagnostics
    n = doc.nodes[0]
    return measure_math(
        n.math, resolver("0123456789=+−∑"), owner=n.node_id, style=style, display=True
    )


def env(body, name="aligned", option=""):
    return r"\begin{" + name + "}" + option + body + r"\end{" + name + "}"


@pytest.mark.parametrize("name", ["aligned", "split", "align*", "gathered", "gather*"])
def test_alignment_ast_preserves_cells_and_source_spans(name):
    raw = env(r"12\\3\\" if "gather" in name else r"1&=2\\&=3\\", name)
    result = parse_math(raw, offset=17)
    assert result.valid, result.diagnostics
    n = result.root.children[0]
    assert n.kind == "Alignment" and len(n.children) == 2
    assert dict(n.attributes) == {"environment": name, "position": "c"}
    symbols = [s for s in n.walk() if s.kind == "Symbol"]
    assert all(raw[s.span.start - 17 : s.span.end - 17] == s.value for s in symbols)
    assert n.span.start == 17 and n.span.end == 17 + len(raw)


@pytest.mark.parametrize(
    "raw,code",
    [
        (env("1&2", "gathered"), "math-alignment-budget"),
        (env("1&2&3", "split"), "math-alignment-budget"),
        (env("&".join("1" * 9)), "math-alignment-budget"),
        (env(r"\\".join("1" * 33)), "math-alignment-budget"),
        (env("1", option="[x]"), "math-alignment-option"),
        (env("1", "align*", "[t]"), "math-alignment-option"),
        (env(r"1\\[2mm]2"), "math-alignment-option"),
        (env(r"1\\*2"), "math-alignment-option"),
        (r"\begin{aligned}1\end{gathered}", "math-environment"),
        (r"\begin{aligned}1", "math-environment"),
        (env(r"1\tag{}"), "math-empty"),
    ],
)
def test_budgets_options_and_incomplete_input_are_explicit(raw, code):
    parsed = parse_math(raw)
    assert not parsed.valid and parsed.diagnostics[0].code == code
    assert 0 <= parsed.diagnostics[0].span.start <= parsed.diagnostics[0].span.end <= len(raw)


def test_multiple_equation_pairs_have_shared_anchors_and_preserved_relation_spacing():
    box = measured(env(r"1&=2&33&=4\\555&=6&7&=88\\&+9"))
    assert box.ready
    glyphs = box.glyphs
    equal = [g for g in glyphs if g.occurrence.text == "="]
    assert equal[0].x_mm == pytest.approx(equal[2].x_mm)
    assert equal[1].x_mm == pytest.approx(equal[3].x_mm)
    one = glyphs[0]
    assert equal[0].x_mm - one.x_mm - one.advance_mm == pytest.approx(6 * 0.28)
    three_end = glyphs[4]
    assert equal[1].x_mm - three_end.x_mm - three_end.advance_mm == pytest.approx(6 * 0.28)
    for a, b in zip(equal[:2], equal[2:]):
        assert a.baseline_mm + a.descent_mm < b.baseline_mm - b.ascent_mm
    plus, nine = glyphs[-2:]
    assert nine.x_mm - plus.x_mm - plus.advance_mm == pytest.approx(6 * 0.18)
    narrow = measured(env(r"1&=2&33&=4\\555&=6&7&=88\\&+9"), MathStyle(alignment_pair_gap_em=0.5))
    assert box.width - narrow.width == pytest.approx(6)


@pytest.mark.parametrize("position", ["t", "c", "b"])
def test_gathered_centering_and_vertical_baseline_options(position):
    box = measured(env(r"1\\234", "gathered", "[" + position + "]"))
    first, *second = box.glyphs
    assert first.x_mm + first.advance_mm / 2 == pytest.approx(
        (second[0].x_mm + second[-1].x_mm + second[-1].advance_mm) / 2
    )
    if position == "t":
        assert first.baseline_mm == pytest.approx(0)
    elif position == "b":
        assert second[0].baseline_mm == pytest.approx(0)
    else:
        assert (box.descent - box.ascent) / 2 == pytest.approx(-box.axis)


def test_large_fractions_limits_nested_arrays_and_empty_rows_reserve_geometry():
    raw = env(r"1&=\frac{\sum_1^2 3}{4}\\&=\left(\begin{gathered}5\\6\end{gathered}\right)\\\\&=7")
    box = measured(raw)
    assert box.ready, box.diagnostics
    assert "".join(g.occurrence.text for g in box.glyphs) == "1=∑1234=56=7"
    equals = [g for g in box.glyphs if g.occurrence.text == "="]
    assert len({round(g.x_mm, 8) for g in equals}) == 1
    assert equals[-1].baseline_mm - equals[-2].baseline_mm > 2 * 6
    changed = measured(raw, MathStyle(alignment_row_gap_em=1))
    assert changed.ascent + changed.descent > box.ascent + box.descent
    assert all(math.isfinite(v) for v in (box.width, box.ascent, box.descent))


@pytest.mark.parametrize("name", ["align*", "gather*", "split"])
def test_display_only_environments_reject_inline_and_nested_contexts(name):
    raw = env("1", name)
    assert not parse_markdown("$$\n" + raw + "\n$$").diagnostics
    for source in ["$" + raw + "$", "$$\n1+" + raw + "\n$$", "$$\n" + env(raw) + "\n$$"]:
        doc = parse_markdown(source)
        assert "math-alignment-context" in {d.code for d in doc.diagnostics}
        assert not layout_markdown(doc, resolver()).exportable


def test_aligned_cells_page_atom_and_machine_paths_survive_save_edit_and_reopen(tmp_path):
    raw = env(r"1&=2\\33&=44")
    source = (
        "1\n\n$$\n" + raw + "\n$$\n\n|5|\n|---|\n|$" + raw + "$|\n\n6[^a]\n\n[^a]: $" + raw + "$"
    )
    session = SourceSession(source)
    r = resolver()
    flow = FlowStyle(math=MathStyle(alignment_row_gap_em=0.8, alignment_pair_gap_em=1.8))
    doc = parse_markdown(session)
    snapshot = layout_markdown(doc, r, flow=flow)
    assert snapshot.plotter_exportable, snapshot.diagnostics
    expected = Counter(o.occurrence_id for o in doc.occurrences)
    assert Counter(f.occurrence_id for f in snapshot.fragments if not f.repeated) == expected
    for n in (n for root in doc.nodes for n in root.walk() if n.math):
        ids = {o.occurrence_id for o in n.occurrences}
        assert len({f.page_index for f in snapshot.fragments if f.occurrence_id in ids}) == 1
    canonical = lambda pts: min(pts, tuple(reversed(pts)))
    for p in plan_from_snapshot(snapshot).pages:
        assert Counter(canonical(st.points) for st in p.strokes) == Counter(
            canonical(st.points) for st in route_page(p, optimize=True).page.strokes
        )
    path = tmp_path / "aligned.inkdoc"
    save_package(path, session, r, snapshot.page_profile, StyleProfile(), flow=flow, optimize=True)
    p = load_package(path)
    assert layout_markdown(parse_markdown(p.session), p.resolver, flow=p.flow) == snapshot
    choices = r.selection_records()
    session.apply(0, 0, "2\n\n")
    updated = parse_markdown(session)
    assert set(expected) <= {o.occurrence_id for o in updated.occurrences}
    layout_markdown(updated, r, flow=flow)
    assert all(record in r.selection_records() for record in choices)
    session.undo()
    assert parse_markdown(session).occurrences == doc.occurrences


def test_display_formula_moves_whole_and_oversize_fails_finitely():
    raw = env(r"1&=2\\3&=4")
    doc = parse_markdown("1\n\n2\n\n3\n\n$$\n" + raw + "\n$$")
    s = layout_markdown(doc, resolver(), page=PageProfile(80, 55, 5))
    assert s.exportable, s.diagnostics
    ids = {o.occurrence_id for o in doc.nodes[-1].occurrences}
    assert {f.page_index for f in s.fragments if f.occurrence_id in ids} == {1}
    big = parse_markdown("$$\n" + env(r"\\".join("1&=2" for _ in range(32))) + "\n$$")
    s = layout_markdown(big, resolver(), page=PageProfile(40, 40, 5))
    assert not s.exportable and len(s.pages) < 3
    assert any("overflow" in d.code for d in s.diagnostics)


def test_new_alignment_defaults_are_independent_and_validate_physical_dimensions():
    old = asdict(MathStyle())
    old.pop("alignment_row_gap_em")
    old.pop("alignment_pair_gap_em")
    assert MathStyle(**old) == MathStyle()
    for key in ("alignment_row_gap_em", "alignment_pair_gap_em"):
        for value in (-1, 3, float("nan")):
            with pytest.raises(ValueError):
                replace(MathStyle(), **{key: value})
    s = measured(env(r"1&2\\3&4"), MathStyle(alignment_row_gap_em=0))
    first, _, second, _ = s.glyphs
    assert (
        second.baseline_mm - second.ascent_mm - (first.baseline_mm + first.descent_mm) >= 0.6 - 1e-9
    )


def test_alignment_cells_use_display_limits_even_when_nested_inline():
    doc = parse_markdown("$" + env(r"\sum_1^2 3&=4") + "$")
    n = doc.nodes[0].children[0]
    while not n.math:
        n = n.children[0]
    box = measure_math(n.math, resolver("1234=∑"), owner=n.node_id, display=False)
    assert box.ready
    operator, sub, sup = box.glyphs[:3]
    assert sub.x_mm + sub.advance_mm / 2 == pytest.approx(operator.x_mm + operator.advance_mm / 2)
    assert sup.baseline_mm + sup.descent_mm < operator.baseline_mm - operator.ascent_mm
