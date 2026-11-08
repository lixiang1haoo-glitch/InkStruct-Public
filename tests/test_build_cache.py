"""Cached editor results have current request revisions and exact uncached semantics."""

import threading
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")
from test_math_sample_constructions import assets as construction_assets
from test_symbol_provider import asset

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.layout.inline import LayoutCancelled


def args(source="12.50 $12_3$"):
    return {
        "session": SourceSession(source),
        "revision": 1,
        "resolver": AssetResolver(embedded=construction_assets()[:1], builtin_numbers=True),
        "run": "",
        "symbols": "",
        "page": PageProfile(),
        "style": StyleProfile(),
        "flow": FlowStyle(),
        "cancelled": threading.Event(),
    }


@pytest.mark.parametrize("change", ["tail", "shift", "math", "table", "code", "footnote", "page"])
def test_measurements_survive_full_layout_misses_with_exact_current_mapping(change):
    source = (
        "12.50\n\n$\\frac{12}{34}$\n\n|12|34|\n|---|---|\n|5.6|7.8|\n\n"
        "```\n12.5\n```\n\n12[^n]\n\n[^n]: 34\n\n9.0"
    )
    inputs, cache = args(source), MarkdownBuildCache()
    first = mixed.build_markdown(**inputs, cache=cache)
    assert first["snapshot"].exportable
    inputs["resolver"] = first["resolver"]
    before = cache.measurements.statistics()
    if change == "tail":
        inputs["session"].apply(len(source) - 1, len(source), "5")
    elif change == "shift":
        inputs["session"].apply(0, 0, "123\n\n")
    elif change == "page":
        inputs["page"] = replace(inputs["page"], width_mm=220)
    else:
        field = {
            "math": "em_mm",
            "table": "digit_height_mm",
            "code": "advance_mm",
            "footnote": "text_scale",
        }[change]
        config = getattr(inputs["flow"], change)
        inputs["flow"] = replace(
            inputs["flow"], **{change: replace(config, **{field: getattr(config, field) * 1.1})}
        )
    inputs["revision"] = 47
    expected = mixed.build_markdown(**inputs)
    actual = mixed.build_markdown(**inputs, cache=cache)
    assert actual["snapshot"] == expected["snapshot"]
    assert actual["resolver"].selection_records() == expected["resolver"].selection_records()
    assert cache.layouts.statistics()["hits"] == 0
    if change != "shift":
        assert cache.measurements.statistics()["hits"] > before["hits"]
    # Fresh resolvers and returned snapshots retain current request ownership.
    assert actual["snapshot"].revision == 47
    assert actual["resolver"].selections is not first["resolver"].selections


def test_cold_and_warm_results_match_and_do_not_share_mutable_selections(monkeypatch):
    inputs = args()
    cache = MarkdownBuildCache()
    cold = mixed.build_markdown(**inputs, cache=cache)
    assert not inputs["resolver"].selections

    def forbidden(*a, **kw):
        raise AssertionError("cache did not skip parsing/layout")

    monkeypatch.setattr(mixed, "parse_markdown", forbidden)
    monkeypatch.setattr(mixed, "layout_markdown", forbidden)
    for resolver in [inputs["resolver"], cold["resolver"]]:
        hit = mixed.build_markdown(**{**inputs, "revision": 78, "resolver": resolver}, cache=cache)
        assert hit["snapshot"] == replace(cold["snapshot"], revision=78)
        assert hit["document"] == replace(cold["document"], revision=78)
        assert hit["resolver"].selections == cold["resolver"].selections
        hit["resolver"].selections.clear()
    assert cold["resolver"].selections and cache.layouts.statistics()["hits"] == 2


@pytest.mark.parametrize(
    "change",
    [
        "page",
        "body",
        "flow",
        "math",
        "table",
        "code",
        "footnote",
        "dialect",
        "seed",
        "anchors",
        "document",
        "selection",
        "geometry",
        "metrics",
        "provenance",
        "version",
        "numeric_type",
        "negative_zero",
    ],
)
def test_invalidations_equal_uncached_rebuild(change, monkeypatch):
    inputs = args("11 $1_1$")
    one, two = asset(sid="a"), asset(sid="b", height=20)
    inputs["resolver"] = AssetResolver(embedded=(one, two), builtin_numbers=True)
    cache = MarkdownBuildCache()
    before = mixed.build_markdown(**inputs, cache=cache)
    inputs["resolver"] = before["resolver"]
    if change == "page":
        inputs["page"] = replace(inputs["page"], height_mm=290)
    elif change == "numeric_type":
        inputs["page"] = replace(inputs["page"], width_mm=210)
    elif change == "negative_zero":
        inputs["flow"] = replace(inputs["flow"], first_line_indent_mm=-0.0)
    elif change == "body":
        inputs["style"] = replace(inputs["style"], em_mm=7)
    elif change == "flow":
        inputs["flow"] = replace(inputs["flow"], paragraph_gap_mm=3)
    elif change in {"math", "table", "code", "footnote"}:
        field = {
            "math": "em_mm",
            "table": "digit_height_mm",
            "code": "em_mm",
            "footnote": "text_scale",
        }[change]
        current = getattr(inputs["flow"], change)
        inputs["flow"] = replace(
            inputs["flow"], **{change: replace(current, **{field: getattr(current, field) * 1.1})}
        )
    elif change == "dialect":
        inputs["flow"] = replace(inputs["flow"], markdown_dialect="obsidian")
    elif change == "seed":
        inputs["resolver"] = AssetResolver(embedded=(one, two), seed=3, builtin_numbers=True)
    elif change == "document":
        inputs["session"] = SourceSession(inputs["session"].source)
    elif change == "anchors":
        inputs["session"].atom_ids = tuple("changed-" + x for x in inputs["session"].atom_ids)
    elif change == "selection":
        r = inputs["resolver"]
        previous = next(iter(r.selections.values()))
        chosen = two if previous.sample_id == "a" else one
        r.selections[previous.occurrence_id] = replace(
            previous, asset_id=chosen.asset_id, sample_id=chosen.sample_id
        )
    elif change in {"geometry", "metrics", "provenance"}:
        updated = (
            replace(one, strokes=(((0.2, 0.2), (0.4, 0.8)),))
            if change == "geometry"
            else replace(one, metrics=replace(one.metrics, advance=one.metrics.advance + 0.2))
            if change == "metrics"
            else replace(one, original_json=one.original_json + b" ")
        )
        inputs["resolver"] = AssetResolver(embedded=(updated, two), builtin_numbers=True)
    elif change == "version":
        from inkstruct.layout import blocks

        monkeypatch.setattr(blocks, "LAYOUT_VERSION", blocks.LAYOUT_VERSION + "/test")
    expected = mixed.build_markdown(**inputs)
    actual = mixed.build_markdown(**inputs, cache=cache)
    assert actual["snapshot"] == expected["snapshot"]
    assert actual["document"] == expected["document"]
    assert actual["resolver"].selection_records() == expected["resolver"].selection_records()
    assert cache.layouts.statistics()["hits"] == 0


def test_undo_hits_without_reassigning_source_identity():
    inputs = args()
    cache = MarkdownBuildCache()
    first = mixed.build_markdown(**inputs, cache=cache)
    inputs["session"].apply(0, 1, "2")
    inputs["revision"] = 2
    second = mixed.build_markdown(**inputs, cache=cache)
    assert second["snapshot"].pages != first["snapshot"].pages
    assert inputs["session"].undo()
    inputs["revision"] = 3
    undo = mixed.build_markdown(**inputs, cache=cache)
    assert undo["snapshot"] == replace(first["snapshot"], revision=3)
    assert cache.layouts.statistics()["hits"] == 1


def test_cancellation_cannot_publish_or_cache_an_incomplete_layout(monkeypatch):
    inputs = args()
    cache = MarkdownBuildCache()
    original = mixed.layout_markdown

    def cancel(*a, **kw):
        result = original(*a, **kw)
        inputs["cancelled"].set()
        return result

    monkeypatch.setattr(mixed, "layout_markdown", cancel)
    with pytest.raises(LayoutCancelled):
        mixed.build_markdown(**inputs, cache=cache)
    assert cache.layouts.statistics()["entries"] == 0 and not inputs["resolver"].selections
    inputs["cancelled"].clear()
    monkeypatch.setattr(mixed, "layout_markdown", original)
    mixed.build_markdown(**inputs, cache=cache)
    hits = cache.layouts.statistics()["hits"]
    inputs["cancelled"].set()
    with pytest.raises(LayoutCancelled):
        mixed.build_markdown(**inputs, cache=cache)
    assert cache.layouts.statistics()["hits"] == hits


def test_editor_style_undo_with_accumulated_choices_keeps_uncached_identity():
    inputs = args()
    cache = MarkdownBuildCache()
    first = mixed.build_markdown(**inputs, cache=cache)
    inputs["resolver"] = first["resolver"]
    inputs["session"].apply(0, 1, "2")
    inputs["revision"] = 2
    second = mixed.build_markdown(**inputs, cache=cache)
    inputs["resolver"] = second["resolver"]
    inputs["session"].undo()
    inputs["revision"] = 3
    expected = mixed.build_markdown(**inputs)
    actual = mixed.build_markdown(**inputs, cache=cache)
    assert actual["snapshot"] == expected["snapshot"]
    assert actual["snapshot"].pages == first["snapshot"].pages
    assert actual["resolver"].selection_records() == expected["resolver"].selection_records()
    assert cache.parsed.statistics()["hits"] >= 1
    # Removed instances retain their selected assets for history. That enlarged
    # registry changes the layout identity, so this first undo must not fake a hit.
    assert cache.layouts.statistics()["hits"] == 0
