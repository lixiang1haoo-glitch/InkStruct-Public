import copy
import json
import zipfile
from dataclasses import asdict

import pytest
from test_document_layout import glyph
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import (
    FontPackage,
    decode,
    to_user,
    trajectory_hashes,
    validate_trajectory,
)
from inkstruct.fonts.importer import build_font, make_generated, make_symbol
from inkstruct.layout.blocks import layout_markdown


def recorded(tmp_path, styles=("upright", "italic")):
    folder = tmp_path / "symbols"
    folder.mkdir()
    for i, style in enumerate(styles):
        v = specimen("A", f"sample-{i}", height=-20 + i * 10)
        v["variant"] = {"letter_style": style}
        (folder / f"{i}.json").write_text(json.dumps(v))
    return folder


def test_styles_conversion_and_frozen_document(tmp_path):
    dev = tmp_path / "dev.inkfont"
    user = tmp_path / "user.inkfont"
    build_font(dev, writer="fixture", name="test", symbols=recorded(tmp_path))
    to_user(dev, user)
    a, b = FontPackage(dev), FontPackage(user)
    assert a.manifest["core_hash"] == b.manifest["core_hash"]
    assert a.manifest["content_hash"] != b.manifest["content_hash"]
    assert a.records == b.records
    assert list(a.glyphs()) == list(b.glyphs())
    with zipfile.ZipFile(user) as z:
        assert not any(n.startswith("development/") for n in z.namelist())
    session = SourceSession(r"A $A$ $\mathrm{A}$ $\text{A}$")
    resolver = AssetResolver(embedded=a.glyphs())
    from inkstruct.layout.measurement_cache import MeasurementCache, measurement_scope

    cache = MeasurementCache()
    with measurement_scope(cache):
        before = layout_markdown(parse_markdown(session), resolver)
        assert layout_markdown(parse_markdown(session), resolver) == before
    assert cache.reused > 0
    assert before.exportable, before.diagnostics
    assert [s.resolved_style for s in resolver.selections.values()] == [
        "upright",
        "italic",
        "upright",
        "upright",
    ]
    path = tmp_path / "frozen.inkdoc"
    save_package(path, session, resolver, PageProfile(), StyleProfile())
    dev.unlink()
    user.unlink()
    restored = load_package(path)
    after = layout_markdown(parse_markdown(restored.session), restored.resolver)
    assert asdict(before) == asdict(after)
    assert restored.resolver.selection_records() == resolver.selection_records()
    for old, new in zip(resolver.pools["A"], restored.resolver.pools["A"], strict=True):
        assert old.original_json == new.original_json


def test_unknown_source_is_usable_warned_and_frozen(tmp_path):
    run = tmp_path / "run" / "trajectories"
    run.mkdir(parents=True)
    original = glyph()
    (run / "U+4EBA.json").write_text(json.dumps(original))
    path = tmp_path / "legacy.inkfont"
    build_font(path, writer="test", name="legacy", run=run.parent)
    font = FontPackage(path)
    asset = next(font.glyphs())
    core = decode(asset.original_json)
    assert core["summary"]["author_source_status"] == "unknown"
    assert [s["points"] for s in core["trajectory"]["strokes"]] == [
        s["points"] for s in original["strokes"]
    ]
    session = SourceSession("人人")
    r = AssetResolver(embedded=[asset])
    before = layout_markdown(parse_markdown(session), r)
    assert before.exportable
    assert len(r.usage_warnings()) == 1 and r.usage_warnings()[0]["occurrences"] == 2
    assert not r.usage_warnings(occurrence_ids=set())
    r.accept_usage_warnings()
    before = layout_markdown(parse_markdown(session), r)
    doc = tmp_path / "saved.inkdoc"
    save_package(doc, session, r, PageProfile(), StyleProfile())
    reopened = load_package(doc)
    assert not reopened.resolver.usage_warnings(pending_only=True)
    assert reopened.resolver.usage_warnings()[0]["unknown_strokes"] == [1, 2]
    assert layout_markdown(parse_markdown(reopened.session), reopened.resolver) == before


def test_verified_preview_loads_the_selected_candidate_and_checks_its_member(tmp_path, monkeypatch):
    from threading import Event

    from inkstruct.cache import BoundedCache
    from inkstruct.fonts.core import verified_preview_font
    from inkstruct.fonts.identity import release_identity
    from inkstruct.fonts.library import fingerprint
    from inkstruct.fonts.preview_candidates import PreviewCandidates, PreviewFontError
    from inkstruct.resource_catalog import FontMetadata

    path = tmp_path / "preview.inkfont"
    build_font(path, writer="fixture", name="indexed", symbols=recorded(tmp_path, ("upright", "upright")))
    assert verified_preview_font(path) is None
    FontPackage(path).verify()
    FontMetadata(tmp_path).update(path.name, verified_stamp=list(fingerprint(path)))
    font = verified_preview_font(path)
    identity = release_identity(font.identity)
    candidates = tuple(font.glyphs("A"))
    session = SourceSession("A")
    occurrence = parse_markdown(session).occurrences[0]
    eager = AssetResolver(embedded=candidates, font_identity=identity)
    expected = eager.resolve(occurrence)
    reads = []
    checked = font._checked

    def tracked(archive, name):
        reads.append(name)
        return checked(archive, name)

    monkeypatch.setattr(font, "_checked", tracked)
    cache = BoundedCache(max_entries=1, max_weight=1024**2)
    indexed = PreviewCandidates(font, "A", cache, Event())
    resolver = AssetResolver(font_identity=identity, indexed=indexed)
    with indexed.opened():
        assert resolver.resolve(occurrence) == expected
        assert resolver.resolve(occurrence) == expected
    assert len(reads) == 1
    assert resolver.selection_records() == eager.selection_records()
    assert resolver.pools["A"] == (expected,)
    assert resolver.candidate_pool("A") == candidates
    assert cache.statistics()["entries"] == 1

    cache.clear()
    frozen = AssetResolver(font_identity=identity, indexed=indexed, selections=eager.selections.values())
    with indexed.opened():
        assert frozen.resolve(occurrence) == expected
    cache.clear()
    def damaged(*_args):
        raise ValueError("字体成员损坏")
    monkeypatch.setattr(font, "_checked", damaged)
    frozen = AssetResolver(font_identity=identity, indexed=indexed, selections=eager.selections.values())
    with indexed.opened(), pytest.raises(PreviewFontError, match="字体成员损坏"):
        frozen.resolve(occurrence)


def test_generated_partition_and_protocol_are_independent():
    g = glyph()
    sources = [
        {"order": 1, "standard_id": "s1", "kind": "author_complete_component"},
        {"order": 2, "standard_id": "s2", "kind": "explicit_gap"},
    ]
    missing = [{"order": 2, "reason": "no author donor"}]
    row = {
        "stroke_sources": sources,
        "missing": missing,
        "author_only_ready": False,
        "source_strokes": 1,
        "reference_strokes": 1,
    }
    payload = {**row, "provenance": {"0": {}}, "checks": {"protocol": []}}
    t, _m, s = make_generated(g, row, payload, {"same_character_sources_excluded": True})
    assert s["author_source_status"] == "partial" and s["protocol_status"] == "valid"
    assert s["reference_strokes"] == [2]
    assert t["strokes"][0]["dynamic_origin"]["time"] == "inherited_retimed"
    assert t["strokes"][1]["dynamic_origin"]["time"] == "synthesized"
    bad = copy.deepcopy(g)
    bad["strokes"][0]["points"][0]["x"] = 1.2
    with pytest.raises(ValueError):
        make_generated(bad, row, payload, {})
    payload["checks"]["protocol"] = ["broken"]
    with pytest.raises(ValueError):
        make_generated(g, row, payload, {})


def test_dynamic_hashes_and_outside_em_preserved(tmp_path):
    raw = specimen("A", height=-30)
    for s in raw["strokes"]:
        for p in s["points"]:
            p.pop("t_ms")
            p.pop("pressure")
    t, _, _ = make_symbol(json.dumps(raw).encode(), raw)
    validate_trajectory(t)
    assert t["strokes"][0]["points"][0]["y"] < 0
    assert t["strokes"][0]["dynamic_origin"]["time"] == "absent"
    other = copy.deepcopy(t)
    other["strokes"][0]["points"][0]["pressure"] = 0.3
    other["strokes"][0]["dynamic_origin"]["pressure"] = "measured"
    h, k = trajectory_hashes(t), trajectory_hashes(other)
    assert h["geometry_hash"] == k["geometry_hash"]
    assert h["pressure_hash"] != k["pressure_hash"] and h["trajectory_hash"] != k["trajectory_hash"]
    other["strokes"][0]["points"][0]["t_ms"] = 0
    assert trajectory_hashes(other)["time_hash"] != h["time_hash"]
    other["strokes"][0]["points"][0]["x"] = float("nan")
    with pytest.raises(ValueError):
        validate_trajectory(other)


def test_style_fallback_warning_and_damaged_archive(tmp_path):
    path = tmp_path / "one.inkfont"
    build_font(path, writer="fixture", name="test", symbols=recorded(tmp_path, ("unspecified",)))
    font = FontPackage(path)
    r = AssetResolver(embedded=font.glyphs())
    layout_markdown(parse_markdown("A $A$"), r)
    assert len(r.usage_warnings()) == 2
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        to_user(path, path)
    assert path.read_bytes() == original
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members["index.json"] += b" "
    bad = tmp_path / "bad.inkfont"
    with zipfile.ZipFile(bad, "w") as z:
        for n, v in members.items():
            z.writestr(n, v)
    with pytest.raises(ValueError):
        FontPackage(bad)
