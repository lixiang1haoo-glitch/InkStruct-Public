"""Structural definition heads keep their own markers beside a separate number."""

from dataclasses import replace

import pytest
from test_footnote_atoms import render
from test_footnote_figures import figure_flow
from test_footnote_pages import assert_bands, assert_coverage
from test_math_layout import resolver

from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle


@pytest.mark.parametrize(
    "head",
    [
        "## 23",
        "- 23\n    - 45",
        "1. 23\n    2. 45",
        "- [x] 23\n    - [ ] 45",
        "> 23\n    >\n    > 45",
        "---",
        "> ",
        "```\n    23\n    ```",
        "```\n    ```",
        "$$\n    \\frac{2+3}{4}\n    $$",
        "|2|3|\n    |---|---|\n    |4|5|",
        "<table><tr><th>2</th></tr><tr><td>3</td></tr></table>",
        "| | |\n    |---|---|\n    | | |",
    ],
)
def test_supported_structural_heads_preserve_number_and_content(head):
    doc, s = render("1[^a]\n\n[^a]: " + head, resolver=resolver())
    assert s.plotter_exportable, s.diagnostics
    assert_coverage(doc, s)
    assert_bands(s)
    definition = doc.nodes[-1]
    labels = [f for f in s.fragments if f.node_id == definition.node_id]
    assert len(labels) == 1 and not labels[0].repeated
    reference = next(n for root in doc.nodes for n in root.walk() if n.kind == "footnote_reference")
    assert labels[0].page_index == next(
        f.page_index
        for f in s.fragments
        if f.occurrence_id == reference.occurrences[0].occurrence_id
    )
    if "[x]" in head:
        assert len([f for f in s.fragments if f.status.startswith("task-")]) == 2
    if head.startswith("1."):
        assert len([f for f in s.fragments if ":marker:" in f.occurrence_id]) == 4
    if head.startswith("- 23"):
        assert sum(op.occurrence_id.endswith(":bullet") for p in s.pages for op in p.paint_ops) == 2


@pytest.mark.parametrize("bitmap", [False, True])
def test_leading_figure_keeps_reference_number_and_entire_caption(tmp_path, bitmap):
    ext = "png" if bitmap else "svg"
    doc, s = render(
        "1\n\n2\n\n3[^a]\n\n[^a]: ![4 5 6 7 8](plot." + ext + ")",
        page=PageProfile(95, 65, 5),
        flow=figure_flow(tmp_path, bitmap=bitmap, width=40),
    )
    assert s.exportable, s.diagnostics
    assert s.plotter_exportable != bitmap
    definition = doc.nodes[-1]
    ids = {o.occurrence_id for n in definition.walk() for o in n.occurrences}
    placed = [f for f in s.fragments if f.occurrence_id in ids]
    assert len({f.page_index for f in placed}) == 1
    label = next(f for f in placed if f.node_id == definition.node_id)
    image = next(f for f in placed if f.status.startswith("image-"))
    assert label.logical_bounds[2] < image.logical_bounds[0]
    assert_coverage(doc, s)
    assert_bands(s)


def test_table_head_continues_with_definition_number_and_header():
    source = "1[^a]\n\n[^a]: |2|3|\n    |---|---|\n" + "    |4|5|\n" * 25
    doc, s = render(source)
    assert s.exportable, s.diagnostics
    assert len(s.pages) > 2
    definition = doc.nodes[-1]
    labels = [f for f in s.fragments if f.node_id == definition.node_id]
    assert len(labels) == len(s.pages)
    assert not labels[0].repeated and all(f.repeated for f in labels[1:])
    assert_coverage(doc, s)
    assert_bands(s)


def test_large_structural_head_moves_reference_or_reports_if_impossible(tmp_path):
    flow = figure_flow(tmp_path, width=60)
    doc, s = render("1[^a]\n\n[^a]: ![2](plot.svg)", flow=flow, page=PageProfile(95, 40, 5))
    assert not s.exportable and len(s.pages) < 4
    assert "footnote-anchor-overflow" in {d.code for d in s.diagnostics}
    assert_coverage(doc, s)


def test_structural_number_gutter_and_table_dimensions_are_independent():
    flow = FlowStyle(table=TableStyle(width_mm=60))
    flow = replace(flow, footnote=replace(flow.footnote, text_scale=1.5, label_indent_mm=16))
    doc, s = render("1[^a]\n\n[^a]: |2|\n    |---|\n    |3|", flow=flow)
    assert s.exportable, s.diagnostics
    assert_coverage(doc, s)
    assert_bands(s)


def test_distinct_table_head_notes_keep_visible_gap_between_frames():
    source = "1[^a] 2[^b]\n\n[^a]: |3|\n    |---|\n    |4|\n\n[^b]: |5|\n    |---|\n    |6|"
    doc, s = render(source)
    assert s.plotter_exportable, s.diagnostics
    tables = [
        n
        for d in doc.nodes
        if d.kind == "footnote_definition"
        for n in d.walk()
        if n.kind == "table"
    ]
    edges = [
        [
            op
            for p in s.pages
            for op in p.paint_ops
            if op.occurrence_id.startswith(t.node_id + ":note-border:")
        ]
        for t in tables
    ]
    assert all(edges)
    bottom = max(y + op.width_mm / 2 for op in edges[0] for x, y in op.points)
    top = min(y - op.width_mm / 2 for op in edges[1] for x, y in op.points)
    assert top - bottom >= 1
    assert_bands(s)
    assert_coverage(doc, s)
