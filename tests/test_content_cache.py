"""Content cache bounds and invalidation are behavioral, not timing thresholds."""

import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_document_layout import glyph
from test_symbol_provider import specimen

from inkstruct.assets import glyph_provider, symbol_provider
from inkstruct.assets.glyph_provider import GlyphMetrics, GlyphProvider
from inkstruct.assets.symbol_provider import SymbolProfile, SymbolProvider
from inkstruct.cache import BoundedCache


def test_lru_aliases_share_budget_evict_together_and_support_none_key():
    cache = BoundedCache(max_entries=2, max_weight=10)
    value = object()
    cache.put((None, "a"), value, 6)
    assert cache.get(None) is value and cache.get("a") is value
    cache.put(("b", "b-post"), 2, 4)
    assert cache.statistics()["estimated_bytes"] == 10
    cache.get("a")
    cache.put(("c",), 3, 4)
    assert cache.get("b") is None and cache.get("b-post") is None
    assert cache.get("a") is value
    cache.put(("oversized",), 4, 11)
    assert cache.get("oversized") is None and cache.get("a") is value
    assert cache.statistics()["skipped"] == 1
    cache.clear()
    assert cache.statistics()["entries"] == 0 and cache.statistics()["estimated_bytes"] == 0


def test_alias_replacement_and_parallel_eviction_do_not_leave_stale_entries():
    cache = BoundedCache(max_entries=3, max_weight=10)
    cache.put(("a", "shared"), 1, 3)
    cache.put(("shared", "b"), 2, 3)
    assert cache.get("a") is None and cache.get("shared") == 2

    def visit(i):
        cache.put((i, ("alias", i)), i, 3)
        cache.get(i)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(visit, range(100)))
    assert cache.statistics()["entries"] <= 3 and cache.statistics()["estimated_bytes"] <= 10


def test_generated_cache_rechecks_content_even_when_size_and_mtime_unchanged(tmp_path, monkeypatch):
    folder = tmp_path / "trajectories"
    folder.mkdir()
    path = folder / "U+4EBA.json"
    value = glyph("人")
    path.write_text(json.dumps(value))
    cache = BoundedCache(max_entries=4, max_weight=1000000)
    original = glyph_provider.adapt_glyph
    calls = []

    def adapt(*a, **kw):
        calls.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(glyph_provider, "adapt_glyph", adapt)
    first = GlyphProvider.from_run(tmp_path, "人", cache=cache)
    assert (
        GlyphProvider.from_run(tmp_path, "人", cache=cache).assets == first.assets
        and len(calls) == 1
    )
    stamp = path.stat()
    # Whitespace alters bytes and provenance while preserving valid geometry.
    raw = path.read_bytes()
    assert b": " in raw
    changed = raw.replace(b": ", b":\t", 1)
    assert len(changed) == len(raw)
    path.write_bytes(changed)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    second = GlyphProvider.from_run(tmp_path, "人", cache=cache)
    assert len(calls) == 2 and second.assets["人"].asset_id != first.assets["人"].asset_id
    different = GlyphProvider.from_run(
        tmp_path, "人", {"人": GlyphMetrics(advance=1.2)}, cache=cache
    )
    assert len(calls) == 3 and different.assets["人"].metrics.advance == 1.2
    path.unlink()
    assert not GlyphProvider.from_run(tmp_path, "人", cache=cache).assets
    folder.rmdir()
    with pytest.raises(ValueError, match="Missing trajectory"):
        GlyphProvider.from_run(tmp_path, "人", cache=cache)


def test_symbol_cache_rechecks_archive_and_profile_and_does_not_cache_failure(
    tmp_path, monkeypatch
):
    path = tmp_path / "samples.zip"

    def write(height):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("sample.json", json.dumps(specimen(height=height)))

    write(10)
    cache = BoundedCache(max_entries=4, max_weight=1000000)
    original = symbol_provider.adapt_symbol
    calls = []

    def adapt(*a, **kw):
        calls.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(symbol_provider, "adapt_symbol", adapt)
    first = SymbolProvider.from_zip(path, cache=cache)
    assert SymbolProvider.from_zip(path, cache=cache).pools == first.pools and len(calls) == 1
    stamp = path.stat()
    write(11)
    assert path.stat().st_size == stamp.st_size
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    second = SymbolProvider.from_zip(path, cache=cache)
    assert len(calls) == 2 and first.archive_hash != second.archive_hash
    calibrated = SymbolProvider.from_zip(
        path, profile=SymbolProfile(advance_margin=0.2), cache=cache
    )
    assert len(calls) == 3 and calibrated.pools["1"][0].metrics != second.pools["1"][0].metrics
    path.write_bytes(b"broken")
    with pytest.raises(ValueError):
        SymbolProvider.from_zip(path, cache=cache)
    write(11)
    assert SymbolProvider.from_zip(path, cache=cache).pools == second.pools
