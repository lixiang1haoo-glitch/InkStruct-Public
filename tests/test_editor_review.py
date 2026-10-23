from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from test_document_layout import glyph

from inkstruct.assets.glyph_provider import adapt_glyph
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.editor.review import (
    ReviewBook,
    SourceBuffer,
    atomic_write,
    file_hash,
    load_session,
    session_bytes,
)


def test_source_newline_mapping_and_undo():
    original = "人\r\n𠀀人\r天\n地"
    buffer = SourceBuffer(original)
    assert buffer.display == "人\n𠀀人\n天\n地"
    assert buffer.boundaries() == [0, 1, 3, 4, 5, 6, 7, 8, 9]
    buffer.update("人\n𠀀好人\n天\n地")
    assert buffer.raw == "人\r\n𠀀好人\r天\n地"
    assert buffer.raw_to_display(4) == 3
    buffer.update("人\n𠀀人\n天\n地")
    assert buffer.raw == original
    buffer.update("人\n𠀀人\n新\n天\n地")
    assert buffer.raw == "人\r\n𠀀人\r新\r\n天\n地"


def test_review_is_bound_to_exact_asset_and_history(tmp_path):
    first = adapt_glyph(glyph())
    other = adapt_glyph(glyph(profile_version="new-profile"))
    book = ReviewBook()
    book.set(first, "bad", "偏大", tmp_path, "人人人", 1)
    assert other.asset_id not in book.records
    assert len(book.records) == 1
    r = book.records[first.asset_id]
    assert r.character == "人" and r.source_start == 1 and r.context == "人人人"
    assert r.writer_id == "test" and r.note == "偏大"
    book.set(first, "good", "", tmp_path, "人人人", 2)
    assert book.records[first.asset_id].rating == "good"
    book.undo()
    assert book.records[first.asset_id].rating == "bad"
    book.redo()
    assert book.records[first.asset_id].rating == "good"
    book.set(first, None, "", tmp_path, "人人人", 1)
    assert not book.records
    book.undo()
    assert first.asset_id in book.records
    book.set(first, "review", "再看", tmp_path, "人", 0)
    assert not book.redo_stack


def test_session_round_trip_preserves_raw_source_reviews_and_settings(tmp_path):
    book = ReviewBook()
    book.set(adapt_glyph(glyph()), "bad", '=HYPERLINK("bad")', tmp_path, "人人", 0)
    p = tmp_path / "review.inkreview"
    source = "人人\r\n人"
    page, style = PageProfile(), StyleProfile(8, 11, 0.2)
    data = session_bytes(source, str(tmp_path), book, page, style)
    saved = atomic_write(p, data)
    assert saved == file_hash(p)
    buffer, run, reopened, page2, style2 = load_session(p)
    assert buffer.raw == source and run == str(tmp_path)
    assert reopened.records == book.records
    assert page2 == page and style2 == style
    assert not reopened.undo_stack
    assert "'=HYPERLINK" in book.csv_bytes().decode("utf-8-sig")
    assert json.loads(data)["reviews"][0]["note"].startswith("=HYPERLINK")


def test_atomic_save_conflict_and_failure_preserve_file(tmp_path, monkeypatch):
    p = tmp_path / "project"
    old = atomic_write(p, b"original")
    p.write_bytes(b"external change")
    with pytest.raises(ValueError, match="修改"):
        atomic_write(p, b"overwrite", old)
    assert p.read_bytes() == b"external change"
    from inkstruct.editor import review

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(review.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        atomic_write(p, b"changed", file_hash(p))
    assert p.read_bytes() == b"external change"
    assert list(tmp_path.iterdir()) == [p]


def test_unknown_session_version_rejected(tmp_path):
    p = tmp_path / "unknown"
    p.write_text(json.dumps({"schema_version": "future"}))
    with pytest.raises(ValueError, match="版本"):
        load_session(p)


def test_invalid_rating_rejected(tmp_path):
    with pytest.raises(ValueError):
        ReviewBook().set(adapt_glyph(glyph()), "invented", "", tmp_path, "人", 0)


def test_invalid_session_rating_rejected(tmp_path):
    book = ReviewBook()
    asset = adapt_glyph(glyph())
    book.set(asset, "bad", "", tmp_path, "人", 0)
    row = asdict(book.records[asset.asset_id])
    row["rating"] = "invented"
    data = json.loads(session_bytes("人", str(tmp_path), book, PageProfile(), StyleProfile()))
    data["reviews"] = [row]
    p = tmp_path / "invalid"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_session(p)
