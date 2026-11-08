"""Suffix reuse requires current inputs and exact pagination convergence."""

import threading
from dataclasses import replace

import pytest
from test_continuation import TABLE, build, parity

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.images import ImageStyle
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.layout import continuation
from inkstruct.layout.continuation import ContinuationCache
from inkstruct.layout.inline import LayoutCancelled

LEAD = "12\n\n34\n\n56\n\n"
TAIL = "\n\n" + "\n\n".join(["123.45 678.90"] * 40)
OPTIONS = {"page": PageProfile(180, 80, 5), "flow": FlowStyle(table=TableStyle(width_mm=150))}


@pytest.mark.parametrize(
    "middle",
    [
        "123",
        "# 123\n\n## 1\n\n234",
        "- [ ] 123\n- [x] 45",
        "> 123\n>\n> 456",
        "```\n123\n456\n```",
        TABLE,
        "$12_3$",
    ],
)
def test_middle_edit_reuses_suffix_pages_and_current_join_page(middle):
    session = SourceSession(LEAD + middle + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    first = build(session, resolver, cache, **OPTIONS)
    position = len(LEAD) + middle.index("1")
    session.apply(position, position + 1, "8")
    actual = parity(session, resolver, cache, **OPTIONS)
    stats = cache.statistics()
    assert stats["reused_prefix_blocks"] == 3
    assert stats["reused_suffix_blocks"] >= 40
    assert actual.pages[-1] is first.pages[-1]
    assert actual.pages != first.pages
    # Use a checkpoint after the joined boundary on the very next edit.
    position = session.source.index("123.45", len(LEAD) + len(middle) + 30)
    session.apply(position, position + 1, "9")
    parity(session, resolver, cache, **OPTIONS)


@pytest.mark.parametrize(
    "old,new",
    [
        ("**1**", "12345"),  # 1 -> 5 fragments and a different decoration count
        ("![](a.png)", "1234567890"),  # 1 image -> 0 images with equal height/line index
        ("1234567890", "![](a.png)"),
    ],
)
def test_fragment_path_and_image_offsets_are_rebased_across_repeated_edits(old, new):
    assert len(old) == len(new)
    options = {**OPTIONS, "flow": replace(OPTIONS["flow"], image=ImageStyle(width_mm=18))}
    session = SourceSession(LEAD + old + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    original = build(session, resolver, cache, **options)
    for replacement in [new, old, new]:
        session.apply(len(LEAD), len(LEAD) + len(old), replacement)
        before = cache.statistics()
        actual = parity(session, resolver, cache, **options)
        assert cache.statistics()["reused_suffix_blocks"] - before["reused_suffix_blocks"] == 40
        assert actual.pages[-1] is original.pages[-1]


def test_suffix_diagnostics_and_later_checkpoint_offsets_follow_current_prefix():
    wide = "1" * 100
    source = LEAD + "```\n" + wide + "\n```" + TAIL + "\n\n```\n" + wide + "\n```"
    session, resolver, cache = (
        SourceSession(source),
        AssetResolver(builtin_numbers=True),
        ContinuationCache(),
    )
    first = build(session, resolver, cache, **OPTIONS)
    assert sum(d.code == "code-line-width-overflow" for d in first.diagnostics) == 2
    session.apply(len(LEAD) + 4, len(LEAD) + 4 + len(wide), " " * len(wide))
    actual = parity(session, resolver, cache, **OPTIONS)
    # Whitespace still occupies fixed grid cells, but no longer paints overflow.
    assert sum(d.code == "code-line-width-overflow" for d in actual.diagnostics) == 2
    assert sum(d.code == "ink-overflow" for d in actual.diagnostics) * 2 == sum(
        d.code == "ink-overflow" for d in first.diagnostics
    )
    assert cache.statistics()["reused_suffix_blocks"] > 30
    # The last block used rebased diagnostic counts when saved as a new prefix.
    session.apply(len(session.source) - 5, len(session.source) - 4, "9")
    parity(session, resolver, cache, **OPTIONS)


def test_multiple_changes_cannot_reuse_between_them():
    session = SourceSession(LEAD + "123" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache, **OPTIONS)
    before = cache.statistics()
    one, two = len(LEAD), session.source.rfind("123.45")
    session.apply(one, one + 1, "8")
    session.apply(two, two + 1, "9")
    parity(session, resolver, cache, **OPTIONS)
    after = cache.statistics()
    assert after["reused_suffix_blocks"] == 0
    assert after["placed_blocks"] - before["placed_blocks"] == 41


def test_block_count_changes_rebase_suffix_checkpoints_in_both_directions():
    old = "```\n1\n2\n```"
    new = "1\n\n2" + " " * (len(old) - 4)
    options = {
        **OPTIONS,
        "flow": replace(OPTIONS["flow"], code=replace(OPTIONS["flow"].code, line_height_mm=10)),
    }
    session = SourceSession(old + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    original = build(session, resolver, cache, **options)
    for replacement in [new, old, new]:
        before = cache.statistics()
        session.apply(0, len(old), replacement)
        actual = parity(session, resolver, cache, **options)
        assert cache.statistics()["reused_suffix_blocks"] - before["reused_suffix_blocks"] == 40
        assert actual.pages[-1] is original.pages[-1]


def test_different_source_offsets_cannot_reuse_suffix_even_when_geometry_fits():
    session = SourceSession(LEAD + "123" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache, **OPTIONS)
    session.apply(len(LEAD), len(LEAD), " ")
    parity(session, resolver, cache, **OPTIONS)
    assert cache.statistics()["reused_suffix_blocks"] == 0


def test_input_match_waits_until_pagination_actually_converges():
    from test_table_pagination_policy import CHAIN

    math = "$\\frac{1}{2}$"
    session = SourceSession(LEAD + math + "\n\n" + CHAIN + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache, **OPTIONS)
    before = cache.statistics()
    session.apply(len(LEAD), len(LEAD) + len(math), "$" + "1" * (len(math) - 2) + "$")
    parity(session, resolver, cache, **OPTIONS)
    after = cache.statistics()
    assert after["placed_blocks"] - before["placed_blocks"] >= 2
    assert after["reused_suffix_blocks"] > 0


def test_changed_line_indices_cannot_reuse_visually_matching_later_pages():
    session = SourceSession(LEAD + "12345 67890 12345 67890" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    options = {"page": PageProfile(50, 80, 5)}
    build(session, resolver, cache, **options)
    session.apply(len(LEAD), len(LEAD) + 23, "1" + " " * 22)
    parity(session, resolver, cache, **options)
    assert cache.statistics()["reused_suffix_blocks"] == 0


def test_cancel_during_suffix_splice_does_not_publish_partial_record(monkeypatch):
    session = SourceSession(LEAD + "123" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache, **OPTIONS)
    prior = tuple(cache._entries.values())
    original = continuation.suffix_checkpoints
    event = threading.Event()

    def cancelled(*args, **kwargs):
        event.set()
        yield from original(*args, **kwargs)

    from inkstruct.layout import blocks

    monkeypatch.setattr(blocks, "suffix_checkpoints", cancelled)
    session.apply(len(LEAD), len(LEAD) + 1, "8")
    with pytest.raises(LayoutCancelled):
        build(session, resolver, cache, cancelled=event, **OPTIONS)
    assert tuple(cache._entries.values()) == prior


def test_reused_suffix_points_cannot_bypass_current_budget(monkeypatch):
    from inkstruct.document import limits

    session = SourceSession("1" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    first = build(session, resolver, cache, **OPTIONS)
    count = sum(len(o.points) for p in first.pages for o in p.paint_ops)
    monkeypatch.setattr(limits, "DEFAULT_LIMITS", replace(limits.DEFAULT_LIMITS, points=count))
    build(session, resolver, cache, **OPTIONS)
    prior = tuple(cache._entries.values())
    session.apply(0, 1, "8")
    with pytest.raises(limits.DocumentLimitError, match="路径点"):
        build(session, resolver, cache, **OPTIONS)
    assert tuple(cache._entries.values()) == prior


def test_ordered_list_start_changes_create_new_marker_instances_without_losing_choices():
    session = SourceSession("1. 12\n2. 34\n3. 56" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    first = build(session, resolver, cache, **OPTIONS)
    original_choices = dict(resolver.selections)
    first_ids = {f.occurrence_id for f in first.fragments if ":marker:" in f.occurrence_id}
    first_digits = {i for i in first_ids if original_choices[i].character != "."}
    first_stops = first_ids - first_digits
    owners = {f.occurrence_id: f.node_id for f in first.fragments}
    for action, digit in [
        ("edit", "2"),
        ("edit", "3"),
        ("undo", "2"),
        ("undo", "1"),
        ("redo", "2"),
    ]:
        if action == "edit":
            session.apply(0, 1, digit)
        else:
            assert getattr(session, action)()
        actual = parity(session, resolver, cache, **OPTIONS)
        assert actual.plotter_exportable
        current_ids = {f.occurrence_id for f in actual.fragments if ":marker:" in f.occurrence_id}
        current_nodes = {f.node_id for f in actual.fragments}
        assert {i for i in first_stops if owners[i] in current_nodes} <= current_ids
        if digit != "1":
            assert not first_digits.intersection(current_ids)
        else:
            assert current_ids == first_ids
        assert all(resolver.selections[i] == selection for i, selection in original_choices.items())


def test_inserting_list_item_updates_following_numbers_and_keeps_unchanged_digits():
    session = SourceSession("8. 12\n9. 34\n10. 56" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache, **OPTIONS)
    position = session.source.index("9.")
    session.apply(position, position, "9. 90\n")
    actual = parity(session, resolver, cache, **OPTIONS)
    assert actual.plotter_exportable
    by_line = {}
    for fragment in actual.fragments:
        if ":marker:" in fragment.occurrence_id:
            by_line.setdefault(fragment.line_index, []).append(fragment.text)
    assert ["".join(chars) for chars in by_line.values()] == ["8.", "9.", "10.", "11."]


def test_unavailable_or_incompatible_unchanged_marker_choice_still_blocks_export():
    session = SourceSession("1. 12" + TAIL)
    resolver, cache = AssetResolver(builtin_numbers=True), ContinuationCache()
    build(session, resolver, cache, **OPTIONS)
    identity = next(i for i in resolver.selections if ":marker:" in i)
    resolver.selections[identity] = replace(resolver.selections[identity], sample_id="unavailable")
    actual = parity(session, resolver, cache, **OPTIONS)
    assert not actual.exportable
    assert any(d.code == "asset-missing" for d in actual.diagnostics)
