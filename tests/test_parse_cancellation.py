"""Cooperative cancellation must preserve parsing semantics and abandon stale work early."""

import threading
from pathlib import Path

import pytest

from inkstruct.document import markdown
from inkstruct.document.cancellation import LayoutCancelled
from inkstruct.document.editing import SourceSession
from inkstruct.document.source_map import parser_view
from inkstruct.layout.inline import LayoutCancelled as LegacyCancelled


@pytest.mark.parametrize("path", sorted(Path("examples").glob("markdown*.md")))
def test_uncancelled_parser_keeps_exact_tree_ranges_and_diagnostics(path):
    session = SourceSession(path.read_text())
    for dialect in ("markdown", "obsidian"):
        expected = markdown.parse_markdown(session, dialect=dialect)
        assert (
            markdown.parse_markdown(session, dialect=dialect, cancelled=threading.Event())
            == expected
        )


def test_pre_cancelled_request_skips_even_normalization(monkeypatch):
    event = threading.Event()
    event.set()

    def unexpected(*args, **kwargs):
        raise AssertionError("cancelled request entered source normalization")

    monkeypatch.setattr(markdown, "parser_view", unexpected)
    assert LegacyCancelled is LayoutCancelled
    with pytest.raises(LayoutCancelled):
        markdown.parse_markdown(SourceSession("1"), cancelled=event)


def test_source_normalization_checks_cancellation_inside_long_input():
    class CancelAfterSecondCheck:
        calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls >= 2

    event = CancelAfterSecondCheck()
    with pytest.raises(LayoutCancelled):
        parser_view(("1\r\n" * 10000), cancelled=event)
    assert event.calls == 2


def test_tokenization_cancellation_stops_before_inline_and_is_request_local(monkeypatch):
    event = threading.Event()
    session = SourceSession("# 12\n\n- **34**\n  > 56\n\n" * 20)
    expected = markdown.parse_markdown(session)
    original = markdown.make_parser

    def factory(**kwargs):
        parser = original(**kwargs)

        def cancel(state):
            event.set()

        parser.core.ruler.after("block", "test_cancel", cancel)
        return parser

    with monkeypatch.context() as patch:
        patch.setattr(markdown, "make_parser", factory)
        with pytest.raises(LayoutCancelled):
            markdown.parse_markdown(session, cancelled=event)
    event.clear()
    assert markdown.parse_markdown(session, cancelled=event) == expected


def test_semantic_occurrence_construction_is_cancellable_without_changing_source(monkeypatch):
    event = threading.Event()
    session = SourceSession("1234567890 " * 1000)
    identity = session.identity_record()
    original = session.occurrence_id
    calls = []

    def occurrence(*args, **kwargs):
        calls.append(1)
        if len(calls) == 5:
            event.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(session, "occurrence_id", occurrence)
    with pytest.raises(LayoutCancelled):
        markdown.parse_markdown(session, cancelled=event)
    assert len(calls) == 5 and session.identity_record() == identity


def test_editor_worker_cancels_during_parse_before_resource_or_layout_work(monkeypatch):
    pytest.importorskip("PySide6")
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.schema import PageProfile, StyleProfile
    from inkstruct.document.styles import FlowStyle
    from inkstruct.editor import mixed

    event = threading.Event()
    session = SourceSession("12345 " * 1000)
    resolver = AssetResolver(builtin_numbers=True)
    identity = session.identity_record()
    original = session.occurrence_id

    def occurrence(*args, **kwargs):
        event.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(session, "occurrence_id", occurrence)

    def unexpected(*args, **kwargs):
        raise AssertionError("cancelled parser continued into layout")

    monkeypatch.setattr(mixed, "layout_markdown", unexpected)
    with pytest.raises(LayoutCancelled):
        mixed.build_markdown(
            session, 0, resolver, "", "", PageProfile(), StyleProfile(), FlowStyle(), event
        )
    assert not resolver.selections and session.identity_record() == identity
