import json
from dataclasses import replace

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import Diagnostic
from inkstruct.document.table_export import table_export_view
from inkstruct.document.tables import table_model
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan


def test_explicit_numeric_scope_preserves_whole_values_grid_and_reports_omissions(tmp_path):
    source = "<table><tr><th>电压 $U_1$</th><th>电流</th></tr><tr><td>001.20</td><td>.005</td></tr><tr><td>-1.20</td><td>1e3</td></tr><tr><td>12%</td><td>12 V</td></tr></table>"
    document = parse_markdown(source)
    original = document.nodes[0]
    full, full_report = table_export_view(document, original)
    resolver = AssetResolver(builtin_numbers=True)
    assert not layout_markdown(full, resolver).exportable
    selected, report = table_export_view(document, original, numbers_only=True)
    snapshot = layout_markdown(selected, resolver)
    assert snapshot.exportable, snapshot.diagnostics
    assert "".join(f.text for f in snapshot.fragments) == "001.20.005"
    assert len(report["omitted_cells"]) == 6
    assert len(snapshot.diagnostics) == 6
    assert all(
        d.code == "table-cell-omitted" and d.severity == "warning" for d in snapshot.diagnostics
    )
    assert selected.content_key != full.content_key
    assert document.source == selected.source == source and document.nodes[0] == original
    assert [
        (c.row, c.column, c.rowspan, c.colspan) for c in table_model(selected.nodes[0]).cells
    ] == [(c.row, c.column, c.rowspan, c.colspan) for c in table_model(original).cells]
    assert not full_report["omitted_cells"]
    output = tmp_path / "plotter"
    export_plan(plan_from_snapshot(snapshot), output, export_scope=report, optimize=True)
    manifest = json.loads((output / "plotter.json").read_text())
    assert manifest["export_scope"] == report
    for item in report["omitted_cells"]:
        assert item["source"] == source[item["span"]["start"] : item["span"]["end"]]


def test_numeric_scope_does_not_suppress_structural_errors_or_fetch_inline_content():
    document = parse_markdown("|![123](https://invalid.test/asset)|1.20|\n|---|---|\n|2|3|")
    node = document.nodes[0]
    selected, report = table_export_view(document, node, numbers_only=True)
    assert len(report["omitted_cells"]) == 1
    assert layout_markdown(selected, AssetResolver(builtin_numbers=True)).exportable
    cell = table_model(node).cells[0]
    document = replace(
        document,
        diagnostics=document.diagnostics
        + (Diagnostic("structural-error", "Do not suppress", cell.node.span),),
    )
    selected, _ = table_export_view(document, node, numbers_only=True)
    assert not layout_markdown(selected, AssetResolver(builtin_numbers=True)).exportable
    with pytest.raises(ValueError, match="revision"):
        table_export_view(document, replace(node, node_id="stale"))


def test_numeric_export_key_differs_even_when_no_cells_omitted():
    document = parse_markdown("|1|\n|---|\n|2|")
    full, _ = table_export_view(document, document.nodes[0])
    numeric, report = table_export_view(document, document.nodes[0], numbers_only=True)
    assert not report["omitted_cells"] and full.nodes == numeric.nodes
    assert full.content_key != numeric.content_key
