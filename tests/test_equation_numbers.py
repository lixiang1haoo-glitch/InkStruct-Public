"""Document-order numbering, source identities, tag gutters and references."""

from collections import Counter
from dataclasses import asdict, replace

import pytest
from test_math_layout import resolver
from test_template_fields import setup

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page


def display(raw):
    return "$$\n" + raw + "\n$$"


def env(body, name="equation"):
    return r"\begin{" + name + "}" + body + r"\end{" + name + "}"


def tags(doc):
    return [
        n
        for root in doc.nodes
        for node in root.walk()
        if node.math
        for n in node.math.walk()
        if n.kind == "EquationTag"
    ]


def text(n):
    return "".join(v.value for v in n.walk() if v.kind == "Symbol")


def render(source, **kwargs):
    doc = parse_markdown(source)
    return doc, layout_markdown(doc, resolver("0123456789=+−AB."), **kwargs)


def test_automatic_sequence_manual_tags_star_suppression_and_forward_references():
    source = (
        "$"
        + r"\eqref{last} + \ref{manual}"
        + "$\n\n"
        + "\n\n".join(
            map(
                display,
                [
                    env(r"1=2\label{first}"),
                    env(r"3=4", "equation*"),
                    env(r"5&=6\notag\\7&=8\tag{A.1}\label{manual}\\9&=0", "align"),
                    env(r"1\\2\nonumber\\3\label{last}", "gather"),
                    r"4=5\tag*{B}",
                ],
            )
        )
    )
    doc, s = render(source)
    assert s.plotter_exportable, s.diagnostics
    assert [text(n) for n in tags(doc)] == ["1", "A.1", "2", "3", "4", "B"]
    refs = [
        n
        for root in doc.nodes
        for node in root.walk()
        if node.math
        for n in node.math.walk()
        if n.kind == "EquationReference"
    ]
    assert [text(n) for n in refs] == ["4", "A.1"]
    assert Counter(o.occurrence_id for o in doc.occurrences) == Counter(
        f.occurrence_id for f in s.fragments if not f.repeated
    )


@pytest.mark.parametrize(
    "raw,code",
    [
        (r"1\tag{2}\tag{3}", "math-tag-conflict"),
        (r"1\tag{2}\notag", "math-tag-conflict"),
        (r"1\label{a}", "math-label-unnumbered"),
        (env(r"1\label{a}\notag"), "math-label-unnumbered"),
        (r"\eqref{missing}", "math-label-missing"),
        (r"\ref{bad key}", "math-label-key"),
        (r"\ref{}", "math-label-key"),
        (r"\frac{1\tag{2}}{3}", "math-numbering-context"),
        (env(r"1\tag{3}&=2", "align"), "math-tag-position"),
        (r"1\tag{2}+3", "math-tag-position"),
        (env("1", "align") + "+2", "math-alignment-context"),
        (env(env("1")), "math-numbering-context"),
    ],
)
def test_invalid_numbering_is_source_located_and_blocks_export(raw, code):
    doc, s = render(display(raw))
    assert not s.exportable
    assert code in {d.code for d in doc.diagnostics}
    assert all(0 <= d.span.start <= d.span.end <= len(doc.source) for d in doc.diagnostics)


@pytest.mark.parametrize("raw", [env("1"), r"1\tag{2}", env("1", "align"), env("1", "gather")])
def test_numbering_cannot_sneak_into_inline_math(raw):
    doc, s = render("$" + raw + "$")
    assert not s.exportable
    assert any(
        d.code in {"math-numbering-context", "math-alignment-context"} for d in doc.diagnostics
    )


def test_duplicate_labels_are_rejected_without_overwriting_first_target():
    doc, s = render(
        display(env(r"1\label{a}"))
        + "\n\n"
        + display(env(r"2\label{a}"))
        + "\n\n$"
        + r"\ref{a}"
        + "$"
    )
    assert not s.exportable and "math-label-duplicate" in {d.code for d in doc.diagnostics}
    ref = next(
        n
        for root in doc.nodes
        for v in root.walk()
        if v.math
        for n in v.math.walk()
        if n.kind == "EquationReference"
    )
    assert text(ref) == "1"


def test_numbered_split_single_tag_and_row_tag_right_edges_share_available_width():
    raw = env(env(r"1&=2\\33&=44", "split") + r"\label{a}")
    doc, s = render(
        display(raw) + "\n\n" + display(env(r"1&=2\\3&=4\tag{12.3}\\5&=6\notag", "align"))
    )
    assert s.plotter_exportable, s.diagnostics
    assert [text(n) for n in tags(doc)] == ["1", "2", "12.3"]
    numbers = tags(doc)
    tag_ids = {n.occurrence_id for t in numbers for n in t.walk() if n.kind == "Symbol"}
    ops = [
        op for page in s.pages for op in page.paint_ops if ":delimiter-right-" in op.occurrence_id
    ]
    right = s.page_profile.width_mm - s.page_profile.margin_mm
    assert len(ops) == 3
    assert all(max(x for x, y in op.points) + op.width_mm / 2 == pytest.approx(right) for op in ops)
    assert all(f.logical_bounds[2] < right for f in s.fragments if f.occurrence_id in tag_ids)
    for page in s.pages:
        assert all(
            x + op.width_mm / 2 <= right + 1e-8 for op in page.paint_ops for x, y in op.points
        )


def test_wide_tag_shifts_formula_without_distorting_or_colliding_and_overflow_blocks():
    source = display(r"1=2\tag{123456}")
    doc = parse_markdown(source)
    node = doc.nodes[0]
    style = MathStyle(tag_gap_em=0.8)
    small = measure_math(node.math, resolver(), owner=node.node_id, style=style, available_width=75)
    big = measure_math(node.math, resolver(), owner=node.node_id, style=style, available_width=150)
    assert small.ready and big.ready
    assert [g.advance_mm for g in small.glyphs] == [g.advance_mm for g in big.glyphs]
    assert max(g.x_mm + g.advance_mm for g in small.glyphs[:3]) + 4.8 < min(
        g.x_mm for g in small.glyphs[3:]
    )
    assert big.glyphs[0].x_mm > small.glyphs[0].x_mm
    _, bad = render(source, page=PageProfile(30, 80, 5))
    assert not bad.exportable and any("overflow" in d.code for d in bad.diagnostics)


def test_reference_renumber_preserves_unmodified_formula_symbols_and_undo(tmp_path):
    source = display(env(r"3=4\label{a}")) + "\n\n$" + r"\eqref{a}" + "$"
    session = SourceSession(source)
    r = resolver()
    doc = parse_markdown(session)
    before = layout_markdown(doc, r)
    formula_ids = {
        o.occurrence_id
        for o in doc.occurrences
        if session.source[o.span.start : o.span.end] in "3=4"
    }
    old_tag_id = next(n.occurrence_id for n in tags(doc)[0].walk() if n.kind == "Symbol")
    old_ref_id = doc.occurrences[-1].occurrence_id
    session.apply(0, 0, display(env("1=2")) + "\n\n")
    changed = parse_markdown(session)
    s = layout_markdown(changed, r)
    assert s.exportable, s.diagnostics
    assert [text(t) for t in tags(changed)] == ["1", "2"]
    assert formula_ids <= {o.occurrence_id for o in changed.occurrences}
    assert old_tag_id not in {o.occurrence_id for o in changed.occurrences}
    assert old_ref_id != changed.occurrences[-1].occurrence_id
    session.undo()
    restored = layout_markdown(parse_markdown(session), r)
    assert restored.pages == before.pages
    path = tmp_path / "numbers.inkdoc"
    save_package(
        path, session, r, before.page_profile, StyleProfile(), flow=FlowStyle(), optimize=True
    )
    p = load_package(path)
    assert layout_markdown(parse_markdown(p.session), p.resolver).pages == before.pages


def test_repeated_template_field_reference_does_not_repeat_or_increment_equations():
    source = "$" + r"\eqref{a}" + "$\n\n" + "1\n\n" * 8 + display(env(r"2\label{a}"))
    _, doc, r, flow = setup(source, repeat=True)
    s = layout_markdown(doc, r, flow=flow)
    assert s.plotter_exportable, s.diagnostics
    assert [text(t) for t in tags(doc)] == ["1"]
    ref = doc.nodes[0].children[0].children[0]
    ids = {o.occurrence_id for o in ref.occurrences}
    assert len([f for f in s.fragments if f.occurrence_id in ids]) == len(s.pages)
    for page in plan_from_snapshot(s).pages:
        routed = route_page(page, optimize=True)
        canonical = lambda pts: min(pts, tuple(reversed(pts)))
        assert Counter(canonical(st.points) for st in page.strokes) == Counter(
            canonical(st.points) for st in routed.page.strokes
        )


def test_numbered_formula_in_note_and_reference_in_table_preserve_all_sources():
    source = (
        "1[^a]\n\n|$"
        + r"\eqref{b}"
        + "$|\n|---|\n|2|\n\n[^a]: $$\n    "
        + env(r"3=4\label{b}")
        + "\n    $$"
    )
    doc, s = render(source)
    assert s.plotter_exportable, s.diagnostics
    assert Counter(o.occurrence_id for o in doc.occurrences) == Counter(
        f.occurrence_id for f in s.fragments if not f.repeated
    )
    assert [text(t) for t in tags(doc)] == ["1"]


def test_unnumbered_math_defaults_stay_opt_in_and_parameters_validate():
    doc, s = render(display("1=2") + "\n\n" + display(env("3=4", "equation*")))
    assert not tags(doc) and s.exportable
    old = asdict(MathStyle())
    old.pop("tag_scale")
    old.pop("tag_gap_em")
    assert MathStyle(**old) == MathStyle()
    for key in ("tag_scale", "tag_gap_em"):
        for value in (-1, 3, float("nan")):
            with pytest.raises(ValueError):
                replace(MathStyle(), **{key: value})


def test_empty_rows_and_two_digit_numbers_have_distinct_source_bound_slots():
    rows = [r"\label{empty}", *("1&=1" for _ in range(9)), r"2&=2\label{ten}"]
    source = display(env(r"\\".join(rows), "align")) + "\n\n$" + r"\eqref{ten}" + "$"
    doc, s = render(source)
    assert s.plotter_exportable, s.diagnostics
    assert [text(t) for t in tags(doc)] == [str(i) for i in range(1, 12)]
    assert len({o.occurrence_id for o in doc.occurrences}) == len(doc.occurrences)
    assert all(o.span.end > o.span.start for o in doc.occurrences)
    assert Counter(o.occurrence_id for o in doc.occurrences) == Counter(
        f.occurrence_id for f in s.fragments if not f.repeated
    )


def test_large_list_marker_reserves_numbered_equation_gutter_after_indent():
    source = "123456. $$\n        " + env("1=2") + "\n        $$"
    _, s = render(source)
    assert s.plotter_exportable, s.diagnostics
    assert "".join(f.text for f in s.fragments if ":marker:" in f.occurrence_id) == "123456."
    right = s.page_profile.width_mm - s.page_profile.margin_mm
    op = next(
        op for page in s.pages for op in page.paint_ops if ":delimiter-right-" in op.occurrence_id
    )
    assert max(x for x, y in op.points) + op.width_mm / 2 == pytest.approx(right)
