"""Complex row connectivity and explicit, finite rejection of internal page splits."""

from collections import Counter
from dataclasses import replace

import pytest
from test_mixed_tables import measure

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.document.tables import table_model
from inkstruct.layout.blocks import layout_markdown
from inkstruct.layout.table_pages import paginate_table
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.renderers.pages import export_pages

CHAIN = (
    "<table><thead><tr><th>8</th><th>9</th></tr></thead><tbody>"
    '<tr><td rowspan="2">1</td><td>2</td></tr>'
    '<tr><td rowspan="2">3</td></tr>'
    '<tr><td rowspan="2">4</td></tr>'
    "<tr><td>5</td></tr><tr><td>6</td><td>7</td></tr></tbody></table>"
)


def coverage(doc, snapshot):
    expected = Counter(o.occurrence_id for o in doc.occurrences)
    actual = Counter(f.occurrence_id for f in snapshot.fragments if not f.repeated)
    assert actual == expected


def test_transitive_rowspan_connectivity_not_just_each_cell_span():
    measured = measure(CHAIN, TableStyle(width_mm=60))
    assert measured.model.row_groups == ((0, 1), (1, 5), (5, 6))
    chunks, issues = paginate_table(measured, 28, 40)
    assert not issues
    assert chunks[0].new_page and chunks[0].rows == (0, 1, 2, 3, 4)
    assert chunks[1].rows == (0, 5) and chunks[1].repeated_header
    chunks, issues = paginate_table(measured, 30, 30)
    assert len(issues) == 1 and len(chunks) == 2
    issue = issues[0]
    span = CHAIN[issue.span.start : issue.span.end]
    assert span.startswith('<td rowspan="2">1') and span.endswith("<td>5</td>")
    assert "<th>" not in span and "<td>6" not in span
    assert (
        "rowspan" in issue.message and "40.000 mm" in issue.message and "30.000 mm" in issue.message
    )
    assert Counter(r for c in chunks for r in c.rows if r > 0) == Counter(range(1, 6))


@pytest.mark.parametrize("notes", [False, True])
def test_body_overflow_points_to_group_and_blocks_both_exporters(tmp_path, notes):
    source = ("1[^a]\n\n" if notes else "") + CHAIN + ("\n\n[^a]: 2" if notes else "")
    doc = parse_markdown(source)
    s = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(80, 48, 5),
        flow=FlowStyle(table=TableStyle(width_mm=60)),
    )
    assert not s.plotter_exportable and not s.exportable and len(s.pages) <= 4
    issues = [d for d in s.diagnostics if d.code == "table-group-height-overflow"]
    assert len(issues) == 1 and "Cell contents are not split" in issues[0].message
    assert source[issues[0].span.start : issues[0].span.end].startswith('<td rowspan="2">1')
    coverage(doc, s)
    with pytest.raises(ValueError):
        plan_from_snapshot(s)
    with pytest.raises(ValueError):
        export_pages(s, tmp_path / "final")
    assert not (tmp_path / "final").exists()


def test_header_only_and_tall_unmerged_cell_have_specific_spans():
    header = "<table><thead><tr><th>1</th></tr><tr><th>2</th></tr></thead></table>"
    m = measure(header, TableStyle(width_mm=40, min_row_height_mm=12))
    chunks, issues = paginate_table(m, 15, 15)
    assert len(chunks) == len(issues) == 1 and "Header rows 1–2" in issues[0].message
    assert header[issues[0].span.start : issues[0].span.end].startswith("<th>1")
    source = "<table><tr><td>" + "<br>".join("1" * 15) + "</td><td>2</td></tr></table>"
    m = measure(source, TableStyle(width_mm=40))
    chunks, issues = paginate_table(m, 40, 40)
    assert len(chunks) == len(issues) == 1 and "Atomic rows 1–1" in issues[0].message
    assert "linked by rowspan" not in issues[0].message
    assert len(m.cells[0].lines) == 15


def test_repeat_header_toggle_only_changes_subsequent_group_capacity():
    source = (
        "<table><tr><th>1</th></tr><tr><td>2</td></tr><tr><td>"
        + "<br>".join("3" * 4)
        + "</td></tr></table>"
    )
    m = measure(source, TableStyle(width_mm=40))
    height = m.row_heights[-1] + 0.1
    _, issues = paginate_table(m, height, height)
    assert len(issues) == 1
    off = replace(m, style=replace(m.style, repeat_header=False))
    chunks, issues = paginate_table(off, height, height)
    assert not issues and chunks[0].rows == (0, 1) and chunks[1].rows == (2,)
    assert not chunks[1].repeated_header


def test_colspan_does_not_connect_rows_or_justify_internal_splitting():
    source = '<table><tr><th colspan="2">1</th></tr><tr><td colspan="2">2</td></tr><tr><td>3</td><td>4</td></tr></table>'
    m = measure(source, TableStyle(width_mm=40))
    assert m.model.row_groups == ((0, 1), (1, 2), (2, 3))
    chunks, issues = paginate_table(m, 16, 16)
    assert not issues and [c.rows for c in chunks] == [(0, 1), (0, 2)]




def test_valid_chain_cells_stay_on_one_page_and_preserve_instances():
    doc = parse_markdown("1\n\n2\n\n" + CHAIN)
    s = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(80, 65, 5),
        flow=FlowStyle(table=TableStyle(width_mm=60)),
    )
    assert s.plotter_exportable, s.diagnostics
    coverage(doc, s)
    model = table_model(next(n for n in doc.nodes if n.kind == "table"))
    for a, b in model.row_groups:
        ids = {
            o.occurrence_id
            for cell in model.cells
            if a <= cell.row < b
            for n in cell.node.walk()
            for o in n.occurrences
        }
        assert (
            len({f.page_index for f in s.fragments if f.occurrence_id in ids and not f.repeated})
            == 1
        )
