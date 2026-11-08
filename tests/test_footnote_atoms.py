"""Figures, rules and atomic table groups inside page-bottom definitions."""

from collections import Counter, defaultdict
from dataclasses import replace

import pytest
from test_footnote_figures import figure_flow
from test_footnote_pages import assert_bands, assert_coverage
from test_math_layout import resolver as math_resolver

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.footnote_style import FootnoteStyle
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot


def render(source, *, page=None, flow=None, resolver=None):
    doc = parse_markdown(source)
    result = layout_markdown(
        doc,
        resolver or AssetResolver(builtin_numbers=True),
        page=page or PageProfile(95, 85, 5),
        flow=flow or FlowStyle(table=TableStyle(width_mm=70)),
    )
    return doc, result


@pytest.mark.parametrize("bitmap", [False, True])
def test_note_figure_caption_is_atomic_and_raster_gate_survives(tmp_path, bitmap):
    ext = "png" if bitmap else "svg"
    source = (
        "1[^a]\n\n"
        + "2\n\n" * 3
        + "[^a]: 3\n\n    ![4 5 6 7 8 9 0 1 2 3 4 5]("
        + "plot."
        + ext
        + ")\n\n    6"
    )
    doc, s = render(source, flow=figure_flow(tmp_path, bitmap=bitmap, width=40))
    assert s.exportable, s.diagnostics
    assert s.plotter_exportable != bitmap
    assert_coverage(doc, s)
    assert_bands(s)
    image = next(n for root in doc.nodes for n in root.walk() if n.kind == "image")
    ids = {o.occurrence_id for n in image.walk() for o in n.occurrences}
    pages = {f.page_index for f in s.fragments if f.occurrence_id in ids}
    assert len(pages) == 1
    actual = [op for page in s.pages for op in page.images]
    if bitmap:
        assert len(actual) == 1
        fragment = next(f for f in s.fragments if f.status == "image-reference")
        assert actual[0].bounds == fragment.logical_bounds
        with pytest.raises(ValueError, match="Raster image"):
            plan_from_snapshot(s)
    else:
        assert not actual
        plan_from_snapshot(s)


def test_note_rules_have_units_even_when_no_text_follows():
    doc, s = render("1[^a]\n\n[^a]: 2\n\n    ---\n\n    3\n\n    ---")
    assert s.exportable, s.diagnostics
    rules = [op for page in s.pages for op in page.paint_ops if op.occurrence_id.endswith(":rule")]
    assert len(rules) == 2
    assert all(op.execution_domain == "page-footnotes" for op in rules)
    assert_coverage(doc, s)
    assert_bands(s)


@pytest.mark.parametrize("repeat", [True, False])
def test_long_note_table_repeats_header_only_at_page_breaks(repeat):
    source = "1[^a]\n\n2\n\n[^a]: 3\n\n    |4|5|\n    |---|---|\n" + "    |6|7|\n" * 25 + "\n    8"
    flow = FlowStyle(table=TableStyle(width_mm=70, repeat_header=repeat))
    doc, s = render(source, flow=flow)
    assert s.plotter_exportable, s.diagnostics
    assert 2 < len(s.pages) < 15
    assert_coverage(doc, s)
    assert_bands(s)
    header = next(o for o in doc.occurrences if o.text == "4")
    headers = [f for f in s.fragments if f.occurrence_id == header.occurrence_id]
    row_pages = {f.page_index for f in s.fragments if f.text == "6"}
    assert len(headers) == (len(row_pages) if repeat else 1)
    assert not headers[0].repeated and all(f.repeated for f in headers[1:])
    for page in s.pages:
        borders = [op for op in page.paint_ops if ":note-border:" in op.occurrence_id]
        canonical = lambda p: min(p, tuple(reversed(p)))
        assert len({canonical(op.points) for op in borders}) == len(borders)
        # Each straight outside vertical edge is joined over all rows on its page.
        verticals = [op for op in borders if op.points[0][0] == op.points[1][0]]
        assert len(verticals) in (0, 3)
    plan_from_snapshot(s)


def test_note_rowspan_group_and_decorated_formula_cells_preserve_ink():
    source = '1[^a]\n\n[^a]: 2\n\n    <table><tr><th>3</th><th>4</th></tr><tr><td rowspan="2"><s>5</s></td><td>6</td></tr><tr><td>7</td></tr><tr><td>8</td><td>9</td></tr></table>\n\n    |1|2|\n    |---|---|\n    |$\\frac{3+4}{5}$|~~6~~|'
    doc, s = render(source, resolver=math_resolver())
    assert s.plotter_exportable, s.diagnostics
    assert_coverage(doc, s)
    assert_bands(s)
    table = next(n for root in doc.nodes for n in root.walk() if n.kind == "table")
    group = [o for n in table.walk() for o in n.occurrences if o.text in "567"]
    assert (
        len(
            {
                f.page_index
                for f in s.fragments
                if f.occurrence_id in {o.occurrence_id for o in group}
            }
        )
        == 1
    )
    assert any(":strike:" in op.occurrence_id for p in s.pages for op in p.paint_ops)


@pytest.mark.parametrize(
    "source",
    [
        "1[^a]\n\n[^a]: 2\n\n    |3|4|\n    |---|---|",
        "1[^a]\n\n[^a]: 2\n\n    | | |\n    |---|---|\n    | | |\n    | | |",
        "1[^a]\n\n[^a]: 2\n\n    <table><tr><td>3</td></tr><tr><td>4</td></tr></table>",
    ],
)
def test_empty_cells_header_only_and_no_header_tables(source):
    doc, s = render(source)
    assert s.plotter_exportable, s.diagnostics
    assert_coverage(doc, s)
    assert_bands(s)
    assert any(":note-border:" in op.occurrence_id for p in s.pages for op in p.paint_ops)


def test_multiple_definitions_with_table_and_figure_do_not_lose_sources(tmp_path):
    source = (
        "1[^a] 2[^b]\n\n"
        + "3\n\n" * 10
        + "[^a]: 4\n\n    |5|6|\n    |---|---|\n"
        + "    |7|8|\n" * 10
        + "\n[^b]: 9\n\n    ![0](plot.svg)"
    )
    doc, s = render(
        source, flow=replace(figure_flow(tmp_path, width=40), table=TableStyle(width_mm=70))
    )
    assert s.plotter_exportable, s.diagnostics
    assert_coverage(doc, s)
    assert_bands(s)
    assert len(s.pages) < 20


@pytest.mark.parametrize("kind", ["table", "figure", "missing"])
def test_impossible_atomic_note_units_terminate_with_explicit_errors(tmp_path, kind):
    tail = (
        "![3](missing.svg)"
        if kind == "missing"
        else "![3](plot.svg)"
        if kind == "figure"
        else "|3|4|\n    |---|---|\n    |5|6|"
    )
    flow = replace(
        figure_flow(tmp_path, width=60), table=TableStyle(width_mm=60, min_row_height_mm=60)
    )
    doc, s = render("1[^a]\n\n[^a]: 2\n\n    " + tail, flow=flow, page=PageProfile(90, 40, 5))
    assert not s.exportable
    assert len(s.pages) < 5
    codes = {d.code for d in s.diagnostics}
    assert (
        "image-resource-missing" if kind == "missing" else "footnote-line-height-overflow"
    ) in codes
    assert_coverage(doc, s)


def test_oversized_blank_row_group_has_source_diagnostic_without_fragment_crash():
    doc, s = render(
        "1[^a]\n\n[^a]: 2\n\n    | | |\n    |---|---|\n    | | |",
        flow=FlowStyle(table=TableStyle(width_mm=60, min_row_height_mm=60)),
        page=PageProfile(90, 40, 5),
    )
    assert not s.exportable and len(s.pages) < 5
    assert any(d.code == "footnote-line-height-overflow" for d in s.diagnostics)
    assert_coverage(doc, s)


def test_short_rule_only_continuation_reserves_the_repeated_number_height():
    doc, s = render(
        "1[^a]\n\n[^a]: 2\n\n    ---",
        page=PageProfile(70, 24, 2),
        flow=FlowStyle(paragraph_gap_mm=0, footnote=FootnoteStyle(line_height_scale=0.5)),
    )
    assert s.exportable, s.diagnostics
    assert len(s.pages) == 2 and all(f.repeated for f in s.pages[1].fragments)
    assert_coverage(doc, s)
    assert_bands(s)


def test_extreme_table_dimensions_report_errors_without_measurement_page_assertion():
    source = "1[^a]\n\n[^a]: 2\n\n    |3|\n    |---|\n" + ("    |" + "4 " * 12 + "|\n") * 60
    doc, s = render(
        source,
        flow=FlowStyle(table=TableStyle(width_mm=70, digit_height_mm=2000, line_height_mm=2000)),
    )
    assert not s.exportable and len(s.pages) < 80
    assert any(d.code == "footnote-line-height-overflow" for d in s.diagnostics)
    assert_coverage(doc, s)


def test_table_glyph_formula_and_decoration_paths_are_only_translated():
    source = (
        "1[^a]\n\n[^a]: 2\n\n    |3|4|\n    |---|---|\n" + "    |$\\frac{5+6}{7}$|~~8~~|\n" * 15
    )
    r = math_resolver()
    flow = FlowStyle(table=TableStyle(width_mm=70))
    doc, s = render(source, flow=flow, resolver=r)
    assert s.plotter_exportable, s.diagnostics
    table = next(n for root in doc.nodes for n in root.walk() if n.kind == "table")
    local = replace(doc, nodes=(table,), diagnostics=())
    reference = layout_markdown(
        local,
        r,
        flow=replace(flow, math=replace(flow.math, em_mm=flow.math.em_mm * 0.7)),
        page=PageProfile(95, 2000, 5),
    )

    def canonical_id(key):
        for name in ("strike", "underline"):
            if ":" + name + ":" in key:
                node, rest = key.split(":" + name + ":")
                return node + ":" + name + ":" + rest.split(":")[-1]
        return key

    def paths(snapshot):
        result = defaultdict(Counter)
        allowed = {
            op.occurrence_id
            for p in reference.pages
            for op in p.paint_ops
            if ":border:" not in op.occurrence_id
        }
        for page in snapshot.pages:
            for op in page.paint_ops:
                key = canonical_id(op.occurrence_id)
                if key not in allowed:
                    continue
                x0, y0 = op.points[0]
                shape = tuple((round(x - x0, 7), round(y - y0, 7)) for x, y in op.points)
                result[key][shape] += 1
        return result

    expected, actual = paths(reference), paths(s)
    assert set(expected) == set(actual)
    for key, shapes in expected.items():
        assert shapes.keys() == actual[key].keys()
        copies = {actual[key][shape] / count for shape, count in shapes.items()}
        assert len(copies) == 1 and next(iter(copies)).is_integer()
    assert_coverage(doc, s)
    assert_bands(s)
