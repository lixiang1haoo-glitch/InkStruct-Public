import json
from dataclasses import replace
from zipfile import ZipFile

import pytest
from test_document_layout import provider
from test_template_paper_grid import template

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import PaperGrid
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.layout.blocks import layout_markdown


SOURCE = "| 甲 | 乙 |\n| --- | --- |\n| 甲 | 乙乙乙 |"
PAGE = PageProfile(100, 120, 10)
STYLE = StyleProfile(5, 6)


def table_borders(page, *, vertical):
    axis = 0 if vertical else 1
    return sorted({
        round(op.points[0][axis], 6)
        for op in page.paint_ops
        if ":border:" in op.occurrence_id and op.points[0][axis] == op.points[-1][axis]
    })


def layout(source, table, paper=None, page=PAGE):
    resolver = AssetResolver(generated=provider("甲乙"))
    return layout_markdown(parse_markdown(source), resolver, page=page, style=STYLE,
                           flow=FlowStyle(table=table, template=paper))


@pytest.mark.parametrize("paper", [None, template(PaperGrid(7, 43, 5), 48)])
def test_auto_total_width_shrinks_both_layouts_and_retains_column_choice(paper):
    fixed = TableStyle(width_mm=75, width_mode="equal")
    auto = replace(fixed, total_width_mode="content")
    results = [layout(SOURCE, table, paper) for table in (fixed, auto, replace(auto, width_mode="content"))]
    assert all(result.exportable for result in results)
    manual, equal, content = [table_borders(result.pages[0], vertical=True) for result in results]
    assert manual[-1] - manual[0] == pytest.approx(75)
    assert equal[-1] - equal[0] < 75
    assert equal[1] - equal[0] == pytest.approx(equal[-1] - equal[1], abs=2e-6)
    assert content[-1] - content[0] < equal[-1] - equal[0]
    assert content[1] - content[0] < content[-1] - content[1]
    if paper:
        assert table_borders(results[-1].pages[0], vertical=False) == [17, 26, 35]


def test_auto_total_width_uses_frame_limit_and_wraps_content():
    source = SOURCE.replace("乙乙乙", "乙" * 30)
    page = PageProfile(60, 120, 10)
    table = TableStyle(total_width_mode="content", width_mode="ratio", columns=(1, 3))
    result = layout(source, table, page=page)
    assert result.exportable
    edges = table_borders(result.pages[0], vertical=True)
    assert edges[-1] - edges[0] == pytest.approx(40 - table.stroke_width_mm)
    assert edges[1] - edges[0] == pytest.approx((edges[-1] - edges[0]) / 4, abs=2e-6)
    assert len({f.baseline_mm for f in result.fragments if f.text == "乙"}) > 2


def test_width_mode_saves_as_override_and_legacy_style_stays_compatible(tmp_path):
    session = SourceSession(SOURCE)
    node = parse_markdown(session).nodes[0]
    resolver = AssetResolver(generated=provider("甲乙"))
    fixed = TableStyle(width_mm=75)
    auto = replace(fixed, total_width_mode="content")
    flow = FlowStyle(table=fixed, table_overrides=((node.node_id, auto),))
    path = tmp_path / "table.inkdoc"
    save_package(path, session, resolver, PAGE, STYLE, flow=flow)
    with ZipFile(path) as archive:
        record = json.loads(archive.read("styles.json"))["flow"]
    assert "total_width_mode" not in record["table"]
    assert record["table_overrides"][0][1]["total_width_mode"] == "content"
    assert load_package(path).flow == flow
    with pytest.raises(ValueError, match="固定列宽"):
        replace(auto, width_mode="fixed", columns=(30, 45))
