from collections import Counter
from dataclasses import asdict, replace

import pytest
from test_document_layout import provider

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.document.tables import table_model
from inkstruct.layout.blocks import layout_markdown
from inkstruct.layout.table_pages import border_segments, paginate_table
from inkstruct.layout.tables import _interval_minimum, measure_table
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page


def table(source):
    doc = parse_markdown(source)
    return doc, table_model(doc.nodes[0])


def measure(source, style=None):
    doc, model = table(source)
    visible = "".join(o.text for o in doc.occurrences)
    return measure_table(model, AssetResolver(provider(visible), builtin_numbers=True), style)


def test_html_inline_entities_crlf_code_and_stable_source_identity():
    source = "<table>\r\n<tr><th>人</th><th>数字</th></tr>\r\n<tr><td><strong>人</strong>&amp;<em>天</em><br>人</td><td><code>001  </code></td></tr></table>"
    session = SourceSession(source)
    doc = parse_markdown(session)
    model = table_model(doc.nodes[0])
    assert (model.rows, model.columns, model.header_rows) == (2, 2, 1)
    assert not doc.diagnostics
    assert "".join(o.text for o in doc.occurrences) == "人数字人&天\n人001  "
    entity = next(o for o in doc.occurrences if o.text == "&")
    assert source[entity.span.start : entity.span.end] == "&amp;"
    before = [o.occurrence_id for o in doc.occurrences]
    session.apply(0, 0, "前文\n\n")
    after = parse_markdown(session)
    assert [o.occurrence_id for o in after.occurrences][-len(before) :] == before
    session.undo()
    assert [o.occurrence_id for o in parse_markdown(session).occurrences] == before


def test_pipe_cells_and_merged_html_have_one_grid_model():
    _, pipe = table("|**人**|1.20|\n|:---|---:|\n|天|0.005|")
    assert (pipe.rows, pipe.columns, pipe.header_rows) == (2, 2, 1)
    assert [c.align for c in pipe.cells] == ["left", "right", "left", "right"]
    _, merged = table(
        '<table><tr><td rowspan="2">1</td><td colspan="2">2</td></tr><tr><td>3</td><td>4</td></tr><tr><td>5</td><td>6</td><td>7</td></tr></table>'
    )
    assert (merged.rows, merged.columns, merged.header_rows) == (3, 3, 0)
    assert merged.row_groups == ((0, 2), (2, 3))


@pytest.mark.parametrize(
    "source",
    [
        '<table><tr><td rowspan="2">1</td></tr></table>',
        "<table><tr><td>1</td><td>2</td></tr><tr><td>3</td></tr></table>",
        '<table><thead><tr><th rowspan="2">1</th><th>2</th></tr></thead><tbody><tr><td>3</td></tr></tbody></table>',
        '<table><tr><td onclick="bad()">1</td></tr></table>',
        "<table><tr><td><script>1</script></td></tr></table>",
        "<table><tr><td><table><tr><td>1</td></tr></table></td></tr></table>",
        '<table style="background: url(https://example.com)"><tr><td>1</td></tr></table>',
        '<table><tr><td rowspan="1" rowspan="2">1</td></tr></table>',
    ],
)
def test_invalid_or_unsupported_html_is_retained_with_a_locatable_error(source):
    doc = parse_markdown(source)
    error = next(d for d in doc.diagnostics if d.code == "html-table-invalid")
    assert error.severity == "error" and 0 <= error.span.start < error.span.end <= len(source)
    assert doc.nodes[0].kind == "html_block" and source in doc.nodes[0].raw_content


def test_html_legacy_presentation_attributes_have_explicit_compatibility_diagnostics():
    doc, model = table(
        '<table border="1" cellpadding="6" style="border-collapse:collapse;text-align:center"><tr><td>1.20</td></tr></table>'
    )
    assert model.columns == 1
    assert len(doc.diagnostics) == 2
    assert all(
        d.code == "table-source-style-ignored" and d.severity == "warning" for d in doc.diagnostics
    )


def test_interval_constraint_minimum_is_exact_for_overlapping_colspans():
    constraints = [(0, 2, 10), (1, 3, 10)]
    widths = _interval_minimum(3, constraints, 1)
    # Feasible [1,9,1] uses only 11, while independent equal deficit additions overallocate.
    assert widths == [1, 9, 1]
    assert all(sum(widths[a:b]) >= w for a, b, w in constraints)


def test_width_modes_merged_constraints_and_fixed_overflow_are_explicit():
    source = '<table><tr><td colspan="2">123456789</td></tr><tr><td>1</td><td>2</td></tr></table>'
    content = measure(source, TableStyle(width_mm=80, width_mode="content"))
    assert sum(content.column_widths) == pytest.approx(80)
    assert not content.diagnostics
    for mode, columns, expected in [
        ("equal", (), (40, 40)),
        ("ratio", (1, 3), (20, 60)),
        ("fixed", (30, 50), (30, 50)),
    ]:
        measured = measure(source, TableStyle(width_mm=80, width_mode=mode, columns=columns))
        assert measured.column_widths == expected and not measured.diagnostics
    narrow = measure(source, TableStyle(width_mm=10, width_mode="content"))
    assert any(d.code == "table-width-overflow" for d in narrow.diagnostics)
    fixed = measure(source, TableStyle(width_mm=80, width_mode="fixed", columns=(10, 20)))
    assert any(d.code == "table-fixed-width-mismatch" for d in fixed.diagnostics)


def test_rows_grow_with_content_and_fixed_height_refuses_clipping():
    source = '<table><tr><td>人人人人人人人人人人人人人人人人人人</td><td rowspan="2">人<br>天<br>人</td></tr><tr><td>2</td></tr></table>'
    config = TableStyle(width_mm=40)
    measured = measure(source, config)
    assert max(measured.row_heights) > 8 and not measured.diagnostics
    fixed = measure(source, replace(config, fixed_row_height=True))
    assert fixed.row_heights == (8, 8)
    assert any(d.code == "table-fixed-row-overflow" for d in fixed.diagnostics)


def test_decimal_alignment_measures_both_sides_and_preserves_integer_strings():
    source = "|数值|\n|---|\n|1.20|\n|00012.5|\n|001|"
    measured = measure(source, TableStyle(column_alignments=("decimal",)))
    data = measured.cells[1:]
    assert all(c.align == "decimal" for c in data)
    assert data[-1].decimal_after == 0
    assert ["".join(b.run.occurrence.text for line in c.lines for b in line) for c in data] == [
        "1.20",
        "00012.5",
        "001",
    ]
    left, right = measured.decimal_columns[0]
    assert left == max(c.decimal_before for c in data)
    assert right == max(c.decimal_after for c in data)
    assert measured.cells[0].align == "center"


def test_body_table_body_paginates_repeats_only_headers_and_preserves_every_instance():
    source = (
        "# 12\n\n"
        + "|1|2|\n|---|---|\n"
        + "".join(f"|{i:03}|{i}.005|\n" for i in range(20))
        + "\n34\n"
    )
    document = parse_markdown(source)
    resolver = AssetResolver(builtin_numbers=True)
    snapshot = layout_markdown(
        document,
        resolver,
        page=PageProfile(100, 70, 10),
        flow=FlowStyle(table=TableStyle(width_mm=70)),
    )
    assert snapshot.exportable and len(snapshot.pages) >= 4
    original = [f for f in snapshot.fragments if not f.repeated]
    assert [f.occurrence_id for f in original] == [o.occurrence_id for o in document.occurrences]
    assert original[0].text == "1" and original[-1].text == "4"
    repeated = [f for f in snapshot.fragments if f.repeated]
    table_node = next(n for n in document.nodes if n.kind == "table")
    headers = {o.occurrence_id for n in table_node.children[0].walk() for o in n.occurrences}
    assert repeated and {f.occurrence_id for f in repeated} == headers
    assert all(f.container_id == table_node.node_id for f in repeated)
    choices = {f.occurrence_id: f.asset_id for f in original}
    assert all(f.asset_id == choices[f.occurrence_id] for f in repeated)
    for page in plan_from_snapshot(snapshot).pages:
        assert route_page(page, optimize=True).after_mm <= route_page(page).before_mm
        assert all(
            10 - 1e-7 <= x <= 90 + 1e-7 and 10 - 1e-7 <= y <= 60 + 1e-7
            for s in page.strokes
            for x, y in s.points
        )


def test_rowspan_groups_never_split_and_border_geometry_is_not_drawn_twice():
    source = '<table><thead><tr><th>1</th><th>2</th></tr></thead><tbody><tr><td rowspan="2">3</td><td>4</td></tr><tr><td>5</td></tr><tr><td>6</td><td>7</td></tr></tbody></table>'
    measured = measure(source, TableStyle(width_mm=40))
    chunks, errors = paginate_table(measured, 20, 27)
    assert not errors and chunks[0].new_page
    assert chunks[0].rows == (0, 1, 2) and chunks[1].rows == (0, 3)
    assert not chunks[0].repeated_header and chunks[1].repeated_header
    for chunk in chunks:
        segments, _, _ = border_segments(measured, chunk, 0, 0)
        assert len(set(segments)) == len(segments)
        # Shared edges may touch at endpoints but never overlap in positive length.
        for i, (a, b) in enumerate(segments):
            for c, d in segments[i + 1 :]:
                if a[1] == b[1] == c[1] == d[1]:
                    assert min(b[0], d[0]) <= max(a[0], c[0])
                if a[0] == b[0] == c[0] == d[0]:
                    assert min(b[1], d[1]) <= max(a[1], c[1])


def test_header_only_space_and_oversized_group_have_bounded_diagnostics():
    source = "<table><thead><tr><th>1</th></tr></thead><tbody><tr><td>2<br>3<br>4<br>5<br>6</td></tr><tr><td>7</td></tr></tbody></table>"
    measured = measure(source, TableStyle(width_mm=40))
    chunks, errors = paginate_table(measured, 8, 20)
    assert len(chunks) == 2 and len(errors) == 1
    assert errors[0].code == "table-group-height-overflow"
    counts = Counter(r for c in chunks for r in c.rows if r >= measured.model.header_rows)
    assert counts == {1: 1, 2: 1}
    document = parse_markdown(source)
    snapshot = layout_markdown(
        document,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(70, 40, 10),
        flow=FlowStyle(table=TableStyle(width_mm=40)),
    )
    assert len(snapshot.pages) == 2 and not snapshot.exportable
    assert all(c >= 1 for c in Counter(f.occurrence_id for f in snapshot.fragments).values())


def test_rendered_decimal_anchors_include_integer_endpoint():
    source = "|1|\n|---|\n|1.20|\n|00012.5|\n|001|"
    document = parse_markdown(source)
    snapshot = layout_markdown(
        document,
        AssetResolver(builtin_numbers=True),
        flow=FlowStyle(table=TableStyle(column_alignments=("decimal",))),
    )
    assert snapshot.exportable
    model = table_model(document.nodes[0])
    anchors = []
    for cell in model.cells[1:]:
        fs = [
            f
            for f in snapshot.fragments
            if cell.node.span.start <= f.span.start < cell.node.span.end
        ]
        point = next((f for f in fs if f.text == "."), None)
        anchors.append(point.x_mm if point else fs[-1].x_mm + fs[-1].advance_mm)
    assert max(anchors) - min(anchors) < 1e-8


def test_table_style_override_and_repeated_header_geometry_survive_package(tmp_path):
    from inkstruct.document.package import load_package, save_package
    from inkstruct.document.schema import StyleProfile

    session = SourceSession("|1|\n|---|\n" + "|0.005|\n" * 12)
    doc = parse_markdown(session)
    flow = FlowStyle(
        table_overrides=(
            (
                doc.nodes[0].node_id,
                TableStyle(width_mm=35, width_mode="equal", column_alignments=("decimal",)),
            ),
        )
    )
    resolver, page, style = (
        AssetResolver(builtin_numbers=True),
        PageProfile(70, 70, 10),
        StyleProfile(),
    )
    before = layout_markdown(doc, resolver, page=page, style=style, flow=flow)
    path = tmp_path / "table.inkdoc"
    save_package(path, session, resolver, page, style, flow=flow)
    loaded = load_package(path)
    after = layout_markdown(
        parse_markdown(loaded.session),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    assert asdict(before) == asdict(after)


def test_quote_html_mapping_retains_original_prefix_crlf_and_entity_ranges():
    source = "> <table>\r\n> <tr><td>1&amp;2</td></tr>\r\n> </table>"
    doc = parse_markdown(source)
    assert not doc.diagnostics
    assert [source[o.span.start : o.span.end] for o in doc.occurrences] == ["1", "&amp;", "2"]
    snapshot = layout_markdown(
        doc, AssetResolver(provider("1&2")), flow=FlowStyle(table=TableStyle(width_mm=100))
    )
    assert snapshot.exportable


def test_numeric_calibration_is_frozen_and_ignores_later_tall_math_symbols():
    from test_symbol_provider import asset

    from inkstruct.assets.symbol_provider import SymbolProvider
    from inkstruct.document.table_style import calibrate_tables

    one = asset()
    first = calibrate_tables(FlowStyle(), SymbolProvider([one]))
    later = calibrate_tables(
        FlowStyle(), SymbolProvider([one, asset(char="∫", sid="integral", height=-250)])
    )
    assert first.table == later.table
    assert first.table.numeric_height_em == pytest.approx(0.7)
    assert first.table.digit_height_mm == 3.8


def test_disabled_header_repeat_never_duplicates_source_and_blank_column_keeps_width():
    source = "| |1|\n|---|---|\n" + "| |2.005|\n" * 15
    doc = parse_markdown(source)
    config = TableStyle(width_mm=50, repeat_header=False)
    measured = measure_table(table_model(doc.nodes[0]), AssetResolver(builtin_numbers=True), config)
    assert min(measured.column_widths) > 15
    snapshot = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(80, 70, 10),
        flow=FlowStyle(table=config),
    )
    assert snapshot.exportable and len(snapshot.pages) > 1
    assert not any(f.repeated for f in snapshot.fragments)
    assert [f.occurrence_id for f in snapshot.fragments] == [
        o.occurrence_id for o in doc.occurrences
    ]
