"""Configured geometry, coordinated pagination, validation and native persistence."""

from dataclasses import asdict, replace

import pytest
from test_footnote_figures import figure_flow
from test_footnote_pages import assert_bands, assert_coverage

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.footnote_style import FootnoteStyle
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot


def layout(doc, settings=None, *, flow=None, page=None, resolver=None):
    return layout_markdown(
        doc,
        resolver or AssetResolver(builtin_numbers=True),
        flow=replace(flow or FlowStyle(), footnote=settings or FootnoteStyle()),
        page=page or PageProfile(190, 140, 10),
    )


@pytest.mark.parametrize("kind", ["paragraph", "heading", "table", "caption"])
def test_reference_size_and_raise_reach_all_body_containers(tmp_path, kind):
    text = {
        "paragraph": "12[^a]",
        "heading": "# 12[^a]",
        "table": "| 12[^a] |\n| --- |\n| 34 |",
        "caption": "![12[^a]](plot.svg)",
    }[kind]
    doc = parse_markdown(text + "\n\n[^a]: 56")
    flow = figure_flow(tmp_path) if kind == "caption" else FlowStyle()
    before = layout(doc, flow=flow)
    after = layout(doc, FootnoteStyle(reference_scale=0.9, reference_raise_em=0.8), flow=flow)
    assert before.plotter_exportable and after.plotter_exportable, after.diagnostics
    ref = next(n for root in doc.nodes for n in root.walk() if n.kind == "footnote_reference")
    rid = ref.occurrences[0].occurrence_id
    a, b = (next(f for f in s.fragments if f.occurrence_id == rid) for s in (before, after))
    assert b.advance_mm > a.advance_mm
    # Compare against the preceding character baseline; a whole line may grow.
    preceding = next(o for o in doc.occurrences if o.text == "2")
    baseline = lambda s: next(
        f.baseline_mm for f in s.fragments if f.occurrence_id == preceding.occurrence_id
    )
    assert baseline(after) - b.baseline_mm > baseline(before) - a.baseline_mm
    assert a.asset_id == b.asset_id
    assert_coverage(doc, after)
    assert_bands(after)


def test_note_text_line_height_and_label_gutter_change_actual_geometry():
    doc = parse_markdown("1[^a]\n\n[^a]: 2\\\n    3")
    before = layout(doc)
    after = layout(doc, FootnoteStyle(text_scale=0.9, line_height_scale=1.3, label_indent_mm=12))
    assert after.exportable, after.diagnostics
    select = lambda s, char: next(f for f in s.fragments if f.text == char)
    assert select(after, "2").advance_mm > select(before, "2").advance_mm
    assert select(after, "2").x_mm - select(before, "2").x_mm == pytest.approx(6)
    assert select(after, "3").baseline_mm - select(after, "2").baseline_mm > (
        select(before, "3").baseline_mm - select(before, "2").baseline_mm
    )
    assert_bands(after)


def test_separator_length_gap_and_body_reservation_use_configured_mm():
    doc = parse_markdown("1[^a]\n\n" + "2\n\n" * 15 + "[^a]: 3 4 5")
    config = FootnoteStyle(separator_length_mm=17, body_gap_mm=12, note_gap_mm=7)
    result = layout(doc, config, page=PageProfile(80, 80, 5))
    assert result.exportable, result.diagnostics
    assert_bands(result)
    page = result.pages[0]
    line = next(op for op in page.paint_ops if op.occurrence_id.startswith("footnotes:separator:"))
    assert line.points[1][0] - line.points[0][0] == pytest.approx(17 - 0.15)
    body = [f for f in page.fragments if not f.container_id]
    foot = [f for f in page.fragments if f.container_id]
    assert (
        line.points[0][1] - line.width_mm / 2 - max(f.logical_bounds[3] for f in body) >= 12 - 1e-8
    )
    assert (
        min(f.logical_bounds[1] for f in foot) - line.points[0][1] - line.width_mm / 2 >= 7 - 1e-8
    )
    clipped = layout(doc, replace(config, separator_length_mm=1000), page=PageProfile(80, 80, 5))
    assert clipped.exportable
    assert_bands(clipped)


def test_page_fraction_changes_reservation_but_long_note_still_finishes():
    doc = parse_markdown("1[^a]\n\n" + "2\n\n" * 20 + "[^a]: " + "12 34 " * 80)
    results = [
        layout(doc, FootnoteStyle(page_fraction=v), page=PageProfile(80, 90, 5)) for v in (0.2, 0.7)
    ]
    for s in results:
        assert s.exportable, s.diagnostics
        assert 1 < len(s.pages) < 100
        assert_coverage(doc, s)
        assert_bands(s)
    count = lambda s: sum(bool(f.container_id) for f in s.pages[0].fragments)
    assert count(results[1]) > count(results[0])


def test_settings_roundtrip_migrate_missing_field_and_preserve_source_assets(tmp_path):
    session = SourceSession("1[^a]\n\n[^a]: 2 $3^4$\n\n    ```\n    56\n    ```")
    doc = parse_markdown(session)
    resolver = AssetResolver(builtin_numbers=True)
    page, style = PageProfile(100, 150, 10), StyleProfile()
    config = FootnoteStyle(text_scale=0.8, reference_raise_em=0.6, body_gap_mm=4, page_fraction=0.6)
    flow = FlowStyle(footnote=config)
    before = layout(doc, config, page=page, resolver=resolver)
    assert before.plotter_exportable, before.diagnostics
    raw = {g.asset_id: g.original_json for pool in resolver.pools.values() for g in pool}
    choices = resolver.selection_records()
    old = asdict(flow)
    old.pop("footnote")
    assert FlowStyle(**old).footnote == FootnoteStyle()
    assert FlowStyle(**asdict(flow)) == flow
    path = tmp_path / "notes.inkdoc"
    save_package(path, session, resolver, page, style, flow=flow)
    loaded = load_package(path)
    after = layout(
        parse_markdown(loaded.session),
        loaded.flow.footnote,
        page=loaded.page,
        resolver=loaded.resolver,
    )
    assert before == after
    assert loaded.flow == flow and loaded.session.source == session.source
    assert loaded.resolver.selection_records() == choices
    assert raw == {
        g.asset_id: g.original_json for pool in loaded.resolver.pools.values() for g in pool
    }
    plan_from_snapshot(after)


@pytest.mark.parametrize(
    "settings,code",
    [
        (FootnoteStyle(reference_scale=0.1), "footnote-size-limit"),
        (FootnoteStyle(text_scale=0.1), "footnote-text-size-limit"),
        (FootnoteStyle(body_gap_mm=100, note_gap_mm=100), "footnote-anchor-overflow"),
    ],
)
def test_physically_unwritable_settings_are_diagnosed_and_terminate(settings, code):
    doc = parse_markdown("1[^a]\n\n[^a]: 23")
    result = layout(doc, settings, page=PageProfile(70, 65, 5))
    assert not result.exportable
    assert code in {d.code for d in result.diagnostics}
    assert len(result.pages) < 5
    assert_coverage(doc, result)


def test_short_separator_with_thick_pen_is_gated_and_debug_stays_inside_left_edge():
    doc = parse_markdown("1[^a]\n\n[^a]: 2")
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(200, 250, 10),
        style=StyleProfile(30, 45, 3),
        flow=FlowStyle(footnote=FootnoteStyle(separator_length_mm=1)),
    )
    assert not result.exportable
    assert "footnote-separator-size-limit" in {d.code for d in result.diagnostics}
    separator = next(
        op
        for op in result.pages[0].paint_ops
        if op.occurrence_id.startswith("footnotes:separator:")
    )
    assert all(x - separator.width_mm / 2 >= 10 for x, _ in separator.points)
    with pytest.raises(ValueError):
        plan_from_snapshot(result)


@pytest.mark.parametrize(
    "fields",
    [
        {"reference_scale": 0},
        {"text_scale": 3},
        {"line_height_scale": float("nan")},
        {"reference_raise_em": -1},
        {"body_gap_mm": -1},
        {"note_gap_mm": float("inf")},
        {"separator_length_mm": 0},
        {"page_fraction": 1},
        {"label_indent_mm": True},
        {"text_scale": "0.7"},
        {"schema_version": "future"},
    ],
)
def test_invalid_configuration_rejected(fields):
    with pytest.raises(ValueError):
        FlowStyle(footnote=fields)
