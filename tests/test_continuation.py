"""Actual edits resume prefix placement, with exact full-rebuild output."""

import threading
from dataclasses import replace

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.layout import blocks, continuation
from inkstruct.layout.continuation import ContinuationCache, continuation_scope
from inkstruct.layout.inline import LayoutCancelled
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg

PREFIX = "\n\n".join(["12.34 56.78"] * 24)
TABLE = "| 1 | 2 |\n|---|---|\n" + "|3.4|5.6|\n" * 12


def build(session, resolver, cache=None, **kwargs):
    doc = parse_markdown(session)
    with continuation_scope(cache):
        return blocks.layout_markdown(doc, resolver, **kwargs)


def parity(session, resolver, cache, **kwargs):
    expected = build(session, resolver, **kwargs)
    actual = build(session, resolver, cache, **kwargs)
    assert actual == expected
    if actual.plotter_exportable:
        assert [page_svg(p) for p in plan_from_snapshot(actual).pages] == [
            page_svg(p) for p in plan_from_snapshot(expected).pages
        ]
    return actual


@pytest.mark.parametrize(
    "suffix",
    [
        "34",
        "# 1\n\n## 2\n\n34",
        TABLE + "\n\n34",
        "```\n123\n456\n```\n\n34",
        "> 12\n>\n> 34",
        "- [x] 12\n- [ ] 34",
        "1. 12\n2. 34",
        "***\n\n**12** ~~34~~",
        "$\\frac{1}{2}$\n\n34",
        "![12](absent.png)\n\n34",
    ],
)
def test_tail_edit_reuses_complete_pages_and_keeps_current_geometry_and_mapping(suffix):
    session = SourceSession(PREFIX + "\n\n" + suffix)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    kwargs = {"page": PageProfile(180, 80, 5), "flow": FlowStyle(table=TableStyle(width_mm=150))}
    before = build(session, resolver, cache, **kwargs)
    position = session.source.rfind("4")
    session.apply(position, position + 1, "5")
    after = parity(session, resolver, cache, **kwargs)
    stats = cache.statistics()
    assert stats["reused_blocks"] >= 24
    assert stats["reused_pages"] >= 2
    assert after.pages[0] is before.pages[0]
    assert after.revision == session.revision


@pytest.mark.parametrize(
    "edit", ["middle", "insert", "append", "delete", "delete-all", "front", "same"]
)
def test_source_transactions_and_prefix_boundary_counts(edit):
    session = SourceSession(PREFIX + "\n\n# 1\n\n## 2\n\n345")
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache)
    if edit == "middle":
        pos = session.source.find("12", 120)
        session.apply(pos, pos + 1, "9")
    elif edit == "insert":
        session.apply(150, 150, "123\n\n")
    elif edit == "append":
        session.apply(len(session.source), len(session.source), "\n\n789")
    elif edit == "delete":
        session.apply(session.source.index("#"), len(session.source), "")
    elif edit == "delete-all":
        session.apply(0, len(session.source), "")
    elif edit == "front":
        session.apply(0, 0, "9\n\n")
    parity(session, resolver, cache)
    assert (
        cache.statistics()["reused_blocks"] == 0
        if edit in {"delete-all", "front"}
        else cache.statistics()["reused_blocks"] > 0
    )


def test_heading_chain_is_rewound_and_old_pagination_diagnostics_not_duplicated():
    session = SourceSession("12\n\n34\n\n# 1\n\n## 2\n\n3")
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    kwargs = {"page": PageProfile(50, 65, 5)}
    before = build(session, resolver, cache, **kwargs)
    session.apply(len(session.source) - 1, len(session.source), "9 " * 40)
    actual = parity(session, resolver, cache, **kwargs)
    assert cache.statistics()["reused_blocks"] == 2
    assert actual.pages != before.pages
    # Keep a real prefix layout error, then remove a later offending block.
    bad = "1" * 150
    session = SourceSession(bad + "\n\n12\n\n" + bad)
    cache.clear()
    old = build(session, resolver, cache, **kwargs)
    assert old.diagnostics
    session.apply(len(bad) + 6, len(session.source), "3")
    parity(session, resolver, cache, **kwargs)


def test_literal_definition_edit_reuses_prior_body_checkpoints():
    session = SourceSession(PREFIX + "\n\n1[^n]\n\n[^n]: 2")
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache)
    session.apply(len(session.source) - 1, len(session.source), "3")
    parity(session, resolver, cache)
    assert cache.statistics()["entries"] == 1
    assert cache.statistics()["reused_blocks"] > 0


@pytest.mark.parametrize("mode", ["blank", "preprinted"])
@pytest.mark.parametrize("fields", [False, True])
def test_template_body_continuation_keeps_frames_offsets_and_repeated_fields(mode, fields):
    from test_template_fields import setup
    from test_templates import template

    if fields:
        session, _, resolver, flow = setup("123\n\n" + PREFIX, repeat=True, mode=mode)
    else:
        session = SourceSession(PREFIX)
        resolver = AssetResolver(builtin_numbers=True)
        flow = FlowStyle(template=template(mode))
    flow = replace(flow, template=replace(flow.template, offset_x_mm=0.5, offset_y_mm=-0.5))
    cache = ContinuationCache()
    before = build(session, resolver, cache, flow=flow)
    for pos in [session.source.rfind("8"), session.source.find("8", len(session.source) // 2)]:
        session.apply(pos, pos + 1, "9")
        after = parity(session, resolver, cache, flow=flow)
        assert cache.statistics()["reused_blocks"] > 0
        assert len(after.pages) == len(before.pages)
        assert [p.preview_ops for p in after.pages] == [p.preview_ops for p in before.pages]
    if fields:
        session.apply(0, 1, "9")
        parity(session, resolver, cache, flow=flow)
    changed = replace(flow, template=replace(flow.template, offset_x_mm=1))
    reused = cache.statistics()["reused_blocks"]
    parity(session, resolver, cache, flow=changed)
    assert cache.statistics()["reused_blocks"] == reused


def test_cache_capacity_cancellation_and_worker_scope(monkeypatch):
    session = SourceSession(PREFIX)
    resolver = AssetResolver(builtin_numbers=True)
    tiny = ContinuationCache(max_weight=1)
    parity(session, resolver, tiny)
    assert tiny.statistics()["entries"] == 0 and tiny.statistics()["skipped"] == 1
    cache = ContinuationCache()
    build(session, resolver, cache)
    prior = tuple(cache._entries.values())
    event = threading.Event()
    original = continuation._weight

    def cancel(*args, **kwargs):
        event.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(continuation, "_weight", cancel)
    session.apply(len(session.source) - 1, len(session.source), "9")
    with pytest.raises(LayoutCancelled):
        build(session, resolver, cache, cancelled=event)
    assert tuple(cache._entries.values()) == prior
    # A failed scoped build cannot attach a continuation cache to a later call.
    event.clear()
    build(session, resolver)
    assert tuple(cache._entries.values()) == prior


def test_resumed_points_remain_in_document_budget(monkeypatch):
    from inkstruct.document import limits

    session = SourceSession(PREFIX)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    snapshot = build(session, resolver, cache)
    count = sum(len(op.points) for p in snapshot.pages for op in p.paint_ops)
    # Prime checkpoints under this policy; appending must count the old prefix.
    monkeypatch.setattr(limits, "DEFAULT_LIMITS", replace(limits.DEFAULT_LIMITS, points=count))
    build(session, resolver, cache)
    session.apply(len(session.source), len(session.source), "\n\n123")
    with pytest.raises(limits.DocumentLimitError, match="路径点"):
        build(session, resolver, cache)


@pytest.mark.parametrize("change", ["choice", "geometry", "raw", "style", "version", "identity"])
def test_a_changed_prefix_dependency_is_rebuilt(change, monkeypatch):
    from test_symbol_provider import asset

    from inkstruct.document.schema import StyleProfile

    one, two = asset(sid="a"), asset(sid="b", height=20)
    session = SourceSession("11\n\n" + PREFIX)
    resolver = AssetResolver(embedded=(one, two), builtin_numbers=True)
    cache = ContinuationCache()
    build(session, resolver, cache)
    kwargs = {}
    if change == "choice":
        selected = next(iter(resolver.selections.values()))
        chosen = two if selected.sample_id == "a" else one
        resolver.selections[selected.occurrence_id] = replace(
            selected,
            asset_id=chosen.asset_id,
            sample_id=chosen.sample_id,
        )
    elif change in {"geometry", "raw"}:
        selected = next(iter(resolver.selections.values()))
        glyph = one if selected.sample_id == "a" else two
        updated = (
            replace(glyph, strokes=(((0.2, 0.2), (0.4, 0.8)),))
            if change == "geometry"
            else replace(glyph, original_json=glyph.original_json + b" ")
        )
        resolver = AssetResolver(
            embedded=tuple(updated if g == glyph else g for g in (one, two)),
            selections=resolver.selections.values(),
            builtin_numbers=True,
        )
    elif change == "style":
        kwargs["style"] = StyleProfile(em_mm=7)
    elif change == "version":
        monkeypatch.setattr(continuation, "VERSION", continuation.VERSION + "/test")
    elif change == "identity":
        session = SourceSession(session.source)
    parity(session, resolver, cache, **kwargs)
    assert cache.statistics()["reused_prefix_blocks"] == 0


def test_sequential_edits_with_changing_page_and_block_boundaries():
    import random

    rng = random.Random(91)
    session = SourceSession(PREFIX + "\n\n# 1\n\n" + TABLE + "\n\n```\n123\n```\n\n$1_2$\n\n345")
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    kwargs = {"page": PageProfile(180, 70, 5), "flow": FlowStyle(table=TableStyle(width_mm=150))}
    build(session, resolver, cache, **kwargs)
    for _ in range(24):
        positions = [i for i, c in enumerate(session.source) if c.isdigit()]
        position = rng.choice(positions)
        session.apply(position, position + 1, rng.choice(["9", "12345", "", "3 4 5"]))
        parity(session, resolver, cache, **kwargs)
