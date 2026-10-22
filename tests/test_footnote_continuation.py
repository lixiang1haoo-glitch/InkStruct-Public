"""Coordinated body resume preserves note reservations, cursors and final expansion."""

from dataclasses import replace
from threading import Event

import pytest
from test_continuation import build, parity
from test_footnote_pages import assert_bands, assert_coverage
from test_math_sample_constructions import assets as construction_assets
from test_template_fields import setup

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.layout.continuation import ContinuationCache
from inkstruct.layout.footnotes import FootnotePager
from inkstruct.layout.inline import LayoutCancelled


def source(note):
    body = ["12.34 56.78"] * 28
    body[0] += "[^a]"
    body[12] += "[^b]"
    body[20] += "[^a]"
    return "\n\n".join(body) + "\n\n[^a]: " + note + "\n\n[^b]: 34 56"


NOTES = [
    "12 34",
    "12 34 56 78 90 " * 100,
    "- [x] 12\n    - [ ] 34\n\n    > 56",
    "|1|2|\n    |---|---|\n" + "    |3|4|\n" * 20,
    "$\\frac{12}{3}$\n\n    ```\n    12 34\n    56 78\n    ```",
    "***\n\n    # 12\n\n    34 56",
]


@pytest.mark.parametrize("note", NOTES)
@pytest.mark.parametrize("where", ["head", "middle", "tail"])
def test_real_body_edits_reuse_blocks_with_exact_note_page_bands(note, where):
    session = SourceSession(source(note))
    resolver, cache = AssetResolver(embedded=construction_assets()[:1], builtin_numbers=True), ContinuationCache()
    kw = {"page": PageProfile(80, 85, 5), "flow": FlowStyle(table=TableStyle(width_mm=50))}
    before = build(session, resolver, cache, **kw)
    assert before.plotter_exportable, before.diagnostics
    # A fresh pager is created each build. Its post-body drain must not mutate
    # the cached pre-drain allocations or the final pre-commit checkpoint.
    initial_record = next(iter(cache._entries.values())).value
    initial_record_text = repr(initial_record)
    candidates = [
        i for i in range(session.source.index("[^a]:")) if session.source.startswith("12.34", i)
    ]
    pos = candidates[{"head": 0, "middle": 14, "tail": -1}[where]]
    session.apply(pos, pos + 1, "9")
    actual = parity(session, resolver, cache, **kw)
    assert actual.plotter_exportable, actual.diagnostics
    stats = cache.statistics()
    assert stats["reused_blocks"] > 0
    assert (
        stats["reused_suffix_blocks"] > 0 if where != "tail" else stats["reused_prefix_blocks"] > 0
    )
    assert_coverage(parse_markdown(session), actual)
    assert_bands(actual)
    # Undo and redo reuse a third/fourth generation of checkpoints.
    session.undo()
    parity(session, resolver, cache, **kw)
    session.redo()
    parity(session, resolver, cache, **kw)
    assert repr(initial_record) == initial_record_text


@pytest.mark.parametrize("mode", ["blank", "preprinted"])
@pytest.mark.parametrize("repeat", [False, True])
def test_template_fixed_references_and_body_notes_resume_together(mode, repeat):
    session, _, resolver, flow = setup(
        "1[^a]\n\n" + source("12 34 56 " * 30), repeat=repeat, mode=mode
    )
    flow = replace(flow, table=TableStyle(width_mm=50))
    cache = ContinuationCache()
    before = build(session, resolver, cache, flow=flow)
    assert before.plotter_exportable, before.diagnostics
    pos = session.source.index("12.34", 100)
    session.apply(pos, pos + 1, "9")
    actual = parity(session, resolver, cache, flow=flow)
    assert actual.plotter_exportable, actual.diagnostics
    assert cache.statistics()["reused_blocks"] > 0
    assert cache.statistics()["reused_suffix_blocks"] > 0
    # Changing the field reference changes the mandatory initial note heads.
    session.apply(3, 4, "b")
    old_reused = cache.statistics()["reused_blocks"]
    parity(session, resolver, cache, flow=flow)
    assert cache.statistics()["reused_blocks"] == old_reused


@pytest.mark.parametrize("edit", ["note", "reference", "offset", "height", "source-delete"])
def test_changed_note_dependencies_or_pagination_never_reuse_stale_allocations(edit):
    session = SourceSession(source("12 34 56 " * 35))
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    kw = {"page": PageProfile(80, 80, 5)}
    build(session, resolver, cache, **kw)
    if edit == "note":
        pos = session.source.index("[^a]:") + 6
        session.apply(pos, pos + 1, "9")
    elif edit == "reference":
        pos = session.source.index("[^a]") + 2
        session.apply(pos, pos + 1, "b")
    elif edit == "offset":
        session.apply(40, 40, "12 ")
    elif edit == "height":
        pos = session.source.index("12.34", 60)
        # Same scalar count changes paragraph shape and ensuing reservations.
        session.apply(pos, pos + 11, "1\n\n2\n\n3\n\n4 ")
    else:
        session.apply(0, session.source.index("[^a]:"), "1[^a] 2[^b]\n\n")
    actual = parity(session, resolver, cache, **kw)
    assert actual.plotter_exportable, actual.diagnostics
    if edit != "height":
        assert cache.statistics()["reused_blocks"] == 0


def test_invalid_notes_do_not_publish_unsafe_body_checkpoints():
    session = SourceSession("1[^a]\n\n[^a]: 2\n\n[^a]: 3")
    cache = ContinuationCache()
    result = build(session, AssetResolver(builtin_numbers=True), cache)
    assert not result.exportable
    assert cache.statistics()["entries"] == 0


@pytest.mark.parametrize("bitmap", [False, True])
def test_figures_in_body_and_notes_keep_current_geometry_and_export_capability(tmp_path, bitmap):
    from test_footnote_figures import figure_flow

    ext = "png" if bitmap else "svg"
    session = SourceSession(
        "![1[^a]](plot." + ext + ")\n\n" + source("![2](plot." + ext + ")\n\n    34")
    )
    kw = {"page": PageProfile(95, 95, 5), "flow": figure_flow(tmp_path, bitmap=bitmap, width=30)}
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    before = build(session, resolver, cache, **kw)
    assert before.exportable, before.diagnostics
    pos = session.source.index("12.34", 100)
    session.apply(pos, pos + 1, "9")
    actual = parity(session, resolver, cache, **kw)
    assert cache.statistics()["reused_suffix_blocks"] > 0
    assert actual.exportable and actual.plotter_exportable != bitmap
    assert_coverage(parse_markdown(session), actual)
    assert_bands(actual)


def test_note_resource_provenance_change_invalidates_even_when_ink_is_identical():
    from test_math_layout import resolver as make_resolver

    resolver, cache = make_resolver("1234567890."), ContinuationCache()
    session = SourceSession(source("99"))
    build(session, resolver, cache)
    glyphs = [g for pool in resolver.pools.values() for g in pool]
    glyphs = [
        replace(g, original_json=g.original_json + b"\n") if g.character == "9" else g
        for g in glyphs
    ]
    changed = AssetResolver(embedded=glyphs, selections=tuple(resolver.selections.values()))
    parity(session, changed, cache)
    assert cache.statistics()["reused_blocks"] == 0


def test_suffix_boundary_rejects_different_note_reservations_with_same_body_position():
    from inkstruct.layout.continuation import Checkpoint

    pager = FootnotePager({}, {}, lambda _: (0, 0, 100, 100), 0.3)
    state = Checkpoint(0, 0, 0, 0, 0, 0, None, 0, pager.checkpoint())
    for change in [
        {"cursors": (("a", 2),)},
        {"started": ("a",)},
        {"new": ("a",)},
        {"allocation": (("a", 0, 1),)},
        {"body_bottom": 1},
        {"pages": 1},
    ]:
        other = replace(state, footnotes=replace(state.footnotes, **change))
        assert other.position() != state.position()
    assert (
        replace(state, footnotes=replace(state.footnotes, diagnostics=2)).position()
        == state.position()
    )


def test_final_expansion_and_note_only_drain_are_recomputed_from_precommit_state():
    session = SourceSession("12[^a]\n\n[^a]: " + "12 34 " * 120)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    kw = {"page": PageProfile(65, 60, 5)}
    before = build(session, resolver, cache, **kw)
    record = next(iter(cache._entries.values())).value
    assert len(record.note_pages) == 1 < len(before.pages)
    assert record.checkpoints[-1].footnotes.pages == 0
    assert record.checkpoints[-1].footnotes.cursors[0][1] == 0
    parity(session, resolver, cache, **kw)
    assert cache.statistics()["reused_blocks"] == 1


def test_cancellation_during_note_restore_preserves_prior_complete_record(monkeypatch):
    session = SourceSession(source("12 34 " * 50))
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache)
    prior = tuple(cache._entries.values())
    pos = session.source.index("12.34", 100)
    session.apply(pos, pos + 1, "9")
    cancelled = Event()
    restore = FootnotePager.restore

    def cancel(self, *args, **kwargs):
        cancelled.set()
        return restore(self, *args, **kwargs)

    monkeypatch.setattr(FootnotePager, "restore", cancel)
    with pytest.raises(LayoutCancelled):
        build(session, resolver, cache, cancelled=cancelled)
    assert tuple(cache._entries.values()) == prior
    monkeypatch.setattr(FootnotePager, "restore", restore)
    parity(session, resolver, cache)


def test_capacity_accounts_for_measured_notes_even_with_tiny_body():
    session = SourceSession("12[^a]\n\n[^a]: " + "12 34 " * 100)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache)
    record = next(iter(cache._entries.values())).value
    assert record.coordination
    weight = cache.statistics()["estimated_bytes"]
    tiny = ContinuationCache(max_weight=weight - 1)
    parity(session, resolver, tiny)
    assert tiny.statistics()["entries"] == 0
