from collections import defaultdict
from dataclasses import asdict

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot


def render(text, flow=None, page=None):
    return layout_markdown(
        parse_markdown(text), AssetResolver(builtin_numbers=True), flow=flow, page=page or PageProfile(70, 100, 10)
    )


def test_first_line_indent_reduces_only_first_line_and_respects_paragraph_start():
    snapshot = render("1 " * 20 + "\n\n2 3", FlowStyle(first_line_indent_mm=12))
    assert snapshot.exportable
    lines = defaultdict(list)
    for f in snapshot.fragments:
        lines[f.line_index].append(f)
    assert lines[0][0].x_mm == 22
    assert lines[1][0].x_mm == 10
    assert snapshot.fragments[-3].x_mm == 22
    assert all(f.logical_bounds[2] <= 60 + 1e-9 for f in snapshot.fragments)


def test_flow_spacing_headings_and_nested_indentation_change_geometry():
    text = "# 1\n\n## 2\n\n3\n\n4\n\n- 5\n  - 6\n\n> 7\n> > 8"
    flow = FlowStyle(
        paragraph_gap_mm=5,
        heading_gap_mm=6,
        list_indent_mm=9,
        quote_indent_mm=6,
        heading_scales=(2, 1.8, 1.6, 1.4, 1.2, 1),
    )
    snapshot = render(text, flow, PageProfile(120, 250, 10))
    assert snapshot.exportable
    fs = {f.text: f for f in snapshot.fragments}
    assert fs["1"].advance_mm > fs["2"].advance_mm > fs["3"].advance_mm
    assert fs["4"].baseline_mm - fs["3"].baseline_mm == pytest.approx(14)
    assert [fs[c].x_mm for c in "5678"] == [19, 28, 16, 22]
    assert plan_from_snapshot(snapshot).pages[0].strokes


def test_heading_chain_moves_together_and_three_line_paragraph_has_no_lonely_last_line():
    snapshot = render("1\n\n2\n\n# 3\n\n## 4\n\n5", page=PageProfile(80, 80, 10))
    fs = {f.text: f for f in snapshot.fragments}
    assert fs["2"].page_index == 0
    assert {fs[c].page_index for c in "345"} == {1}
    # Hard breaks fix the paragraph at three lines; all fit on the next page.
    snapshot = render("1\n\n2\n\n3\\\n4\\\n5", page=PageProfile(80, 65, 10))
    fs = {f.text: f for f in snapshot.fragments}
    assert {fs[c].page_index for c in "345"} == {1}


def test_small_list_indent_keeps_bullet_inside_page_and_large_indent_reports_once():
    snapshot = render("- 1", FlowStyle(list_indent_mm=0.5))
    assert snapshot.exportable
    plan_from_snapshot(snapshot)
    assert all(x >= 10 for op in snapshot.pages[0].paint_ops for x, y in op.points)
    snapshot = render("1", FlowStyle(first_line_indent_mm=100))
    assert not snapshot.exportable and len(snapshot.pages) == 1
    assert sum(d.code == "line-width-overflow" for d in snapshot.diagnostics) == 1


def test_package_persists_flow_settings_and_preserves_geometry(tmp_path):
    session = SourceSession("1 2 3\n\n## 4\n\n- 5")
    resolver = AssetResolver(builtin_numbers=True)
    page, style = PageProfile(80, 90, 10), StyleProfile()
    flow = FlowStyle(first_line_indent_mm=8, paragraph_gap_mm=5, list_indent_mm=12)
    before = layout_markdown(parse_markdown(session), resolver, page=page, style=style, flow=flow)
    path = tmp_path / "style.inkdoc"
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


@pytest.mark.parametrize(
    "fields",
    [
        {"first_line_indent_mm": -1},
        {"heading_scales": [1, 2]},
        {"paragraph_gap_mm": float("nan")},
        {"list_indent_mm": 0},
    ],
)
def test_invalid_flow_settings_are_rejected(fields):
    with pytest.raises(ValueError):
        FlowStyle(**fields)
