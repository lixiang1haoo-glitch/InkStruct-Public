import copy

import pytest

from inkstruct.document.editing import SourceSession
from inkstruct.document.schema import SourceSpan
from inkstruct.document.source_map import MappedText, parser_view


def test_normalization_keeps_original_unicode_and_crlf_ranges():
    source = "人\r\n😀\r甲\x00乙\n"
    view = parser_view(source)
    assert view.text == "人\n😀\n甲�乙\n"
    assert view.ranges[1] == SourceSpan(1, 3)
    assert view.ranges[2] == SourceSpan(3, 4)
    assert view.ranges[5] == SourceSpan(6, 7)
    assert view.slice(0, 3).covering_span() == SourceSpan(0, 4)
    assert source[view.ranges[1].start : view.ranges[1].end] == "\r\n"


def test_entities_and_escapes_can_map_without_searching_repeated_text():
    view = MappedText.original("&amp; &amp; \\*")
    decoded = view.replace_segment(0, 5, "&")
    decoded = decoded.replace_segment(2, 7, "&")
    decoded = decoded.replace_segment(4, 6, "*")
    assert decoded.text == "& & *"
    assert decoded.ranges[0] == SourceSpan(0, 5)
    assert decoded.ranges[2] == SourceSpan(6, 11)
    assert decoded.ranges[4] == SourceSpan(12, 14)


def test_insert_before_duplicate_text_keeps_distinct_occurrences_and_undo_ids():
    session = SourceSession("1.20 1.20\r\n😀")
    ids = [session.occurrence_id(SourceSpan(a, a + 4), role="text", text="1.20") for a in (0, 5)]
    assert ids[0] != ids[1]
    original_atoms = session.atom_ids
    session.apply(0, 0, "1.20 ")
    for start, identifier in zip((5, 10), ids):
        assert session.occurrence_id(SourceSpan(start, start + 4), role="text", text="1.20") == (
            identifier
        )
    copied = session.occurrence_id(SourceSpan(0, 4), role="text", text="1.20")
    assert copied not in ids
    edited_atoms = session.atom_ids
    assert session.undo() and session.atom_ids == original_atoms
    assert session.redo() and session.atom_ids == edited_atoms
    assert session.revision == 3


def test_replace_invalidates_only_touched_anchors_and_undo_restores():
    session = SourceSession("012345")
    original = session.atom_ids
    session.apply(2, 4, "23")  # Replacing by identical pasted text still creates a new instance.
    assert session.atom_ids[:2] == original[:2]
    assert session.atom_ids[2:4] != original[2:4]
    assert session.atom_ids[4:] == original[4:]
    assert session.undo()
    assert session.atom_ids == original
    session.apply(0, 1, "x")
    assert not session.redo()


def test_identity_save_restore_requires_exact_source():
    session = SourceSession("人\r\n😀")
    session.apply(0, 0, "0.")
    record = session.identity_record()
    restored = SourceSession.restore(session.source, record)
    assert restored.atom_ids == session.atom_ids
    assert restored.revision == session.revision
    assert restored.occurrence_id(SourceSpan(0, 1), role="text", text="0") == (
        session.occurrence_id(SourceSpan(0, 1), role="text", text="0")
    )
    with pytest.raises(ValueError, match="match source"):
        SourceSession.restore(session.source.replace("\r\n", "\n"), record)
    for key, value in (
        ("schema_version", "future"),
        ("atom_ids", ["x"] * len(session.source)),
        ("revision", -1),
    ):
        broken = copy.deepcopy(record)
        broken[key] = value
        with pytest.raises(ValueError):
            SourceSession.restore(session.source, broken)


def test_rejected_edits_do_not_modify_source_or_history():
    session = SourceSession("原文")
    record = session.identity_record()
    for start, end, text, kwargs in (
        (0, 0, "x", {"expected_revision": 4}),
        (0, 3, "x", {}),
        (0, 0, "x" * 100000, {}),
    ):
        with pytest.raises(ValueError):
            session.apply(start, end, text, **kwargs)
        assert session.identity_record() == record
    assert not session.undo()
