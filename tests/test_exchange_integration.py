"""Import, release lookup, frozen layout and normal rendering of common .inkfont v1."""
from base64 import b64decode
from pathlib import Path
from zipfile import ZipFile

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts import exchange_codec as codec
from inkstruct.fonts.core import FontPackage, cached_font
from inkstruct.fonts.identity import release_identity
from inkstruct.fonts.importer import build_font
from inkstruct.fonts.library import find_font_release, import_font
from inkstruct.fonts.management import inspect_font, summarize
from inkstruct.layout.blocks import layout_markdown
from test_font_packages import recorded


def test_exchange_and_legacy_document_roundtrips(tmp_path, monkeypatch):
    library = tmp_path / "library"
    legacy = tmp_path / "source.inkfont"
    build_font(legacy, writer="fixture", name="合成字体", symbols=recorded(tmp_path))
    original = FontPackage(legacy)
    session = SourceSession(r"A $A$ $\mathrm{A}$")
    doc = parse_markdown(session)
    resolver = AssetResolver(embedded=original.glyphs(), font_identity=release_identity(original.identity))
    layout = layout_markdown(doc, resolver)
    frozen = tmp_path / "original.inkdoc"
    save_package(frozen, session, resolver, PageProfile(), StyleProfile())

    result = import_font(legacy, library, include_dynamics=True)
    installed = Path(result["path"])
    archive = Path(result["original_path"])
    assert installed != archive and archive.read_bytes() == legacy.read_bytes()
    assert find_font_release(library, release_identity(original.identity)) == archive
    with ZipFile(installed) as z, ZipFile(legacy) as old:
        assert codec.decode(z.read("manifest.json"))["format"] == "inkfont"
        context = codec.decode(z.read("extensions/inkstruct-release-v1.json"))
        assert b64decode(context["license_base64"]) == old.read("license.txt")
        assert context["original_release"]["release_id"] == original.identity["release_id"]
        assert codec.EXTENSIONS["pressure"] in z.namelist() or codec.EXTENSIONS["timing"] in z.namelist()
    assert import_font(legacy, library, include_dynamics=True)["path"] == str(installed)
    assert import_font(installed, library)["path"] == str(installed)
    assert list(library.glob("*.inkfont")) == [installed]
    legacy.unlink()
    reopened = load_package(frozen)
    assert layout_markdown(parse_markdown(reopened.session), reopened.resolver) == layout
    assert reopened.resolver.selection_records() == resolver.selection_records()

    read = ZipFile.read
    def geometry_reads_only(z, name, *args, **kwargs):
        assert name not in (codec.EXTENSIONS["pressure"], codec.EXTENSIONS["timing"])
        return read(z, name, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "read", geometry_reads_only)
    package = cached_font(installed)
    assert package.identity != original.identity and package.identity["font_id"] == original.identity["font_id"]
    assert find_font_release(library, release_identity(package.identity)) == installed
    assert summarize(installed)["manifest"]["package_kind"] == "exchange"
    assert inspect_font(installed, "A", "A")["samples"] == 2
    resolver = AssetResolver(embedded=package.glyphs("A"), font_identity=release_identity(package.identity))
    layout = layout_markdown(doc, resolver)
    assert layout.exportable
    assert [v.resolved_style for v in resolver.selections.values()] == ["upright", "italic", "upright"]
    doc_path = tmp_path / "exchange.inkdoc"
    save_package(doc_path, session, resolver, PageProfile(), StyleProfile())
    reopened = load_package(doc_path)
    assert layout_markdown(parse_markdown(reopened.session), reopened.resolver) == layout
    assert reopened.resolver.selection_records() == resolver.selection_records()


def test_native_candidate_ids_styles_axes_and_singletons(tmp_path):
    from inkstruct.fonts.core import to_user

    path = tmp_path / "external.inkfont"
    index = {"ℏ": ["roman-b", "roman-a", "italic-one"], "。": ["dot"]}
    geometry = codec.encode({"strokes": [[[-.125, -.4]], [[0, .1], [.2, .2]]]})
    members = {f"glyphs/{cid}.json": geometry for ids in index.values() for cid in ids}
    members["index.json"] = codec.encode(index)
    binding = {"trajectory_digest": codec.digest(geometry)}
    members[codec.EXTENSIONS["provenance"]] = codec.encode({
        "schema_version": 1, "entries": {cid: dict(binding, source_kind="composed",
        letter_style="italic" if cid.startswith("italic") else "upright") for cid in index["ℏ"]}})
    members[codec.EXTENSIONS["math"]] = codec.encode({
        "schema_version": 1, "entries": {"italic-one": dict(binding, math_axis_em=-.35)}})
    members["extensions/vendor-v1.json"] = b'{"schema_version":1,"entries":{}}'
    manifest = dict(name="Synthetic exchange", format="inkfont", format_version=1,
                    font_id="00000000-0000-4000-8000-000000000001",
                    members={k: dict(bytes=len(v), sha256=codec.digest(v)) for k, v in members.items()})
    with ZipFile(path, "w") as z:
        z.writestr("manifest.json", codec.encode(manifest))
        for name, raw in members.items():
            z.writestr(name, raw)
    result = import_font(path, tmp_path / "library")
    font = cached_font(result["path"])
    assert [r["candidate_id"] for r in font.pools["ℏ"]] == index["ℏ"]
    pool = tuple(font.glyphs("ℏ"))
    assert all("priority" not in glyph.font_core["record"] for glyph in pool)
    occurrence = parse_markdown(SourceSession("ℏ")).occurrences[0]
    selected = {AssetResolver(embedded=pool, seed=seed).resolve(occurrence).sample_id for seed in range(32)}
    assert selected == {"roman-a", "roman-b"}
    italic = AssetResolver(embedded=pool).resolve(occurrence, letter_style="italic")
    assert italic.sample_id == "italic-one" and italic.math_axis_em == .35
    assert italic.metrics.baseline == 0 and italic.strokes[0] == ((-.125, -.4),)
    copy = tmp_path / "export.inkfont"
    to_user(result["path"], copy)
    assert copy.read_bytes() == path.read_bytes()


def test_failed_migration_preserves_usable_verified_original(tmp_path, monkeypatch):
    p = tmp_path / "old.inkfont"
    build_font(p, writer="fixture", name="fallback", symbols=recorded(tmp_path))
    library = tmp_path / "fonts"
    def failed(*args, **kwargs):
        raise ValueError("目标预算超限")
    with monkeypatch.context() as ctx:
        ctx.setattr(codec, "convert", failed)
        result = import_font(p, library)
    assert "目标预算超限" in result["message"]
    legacy = Path(result["path"])
    assert legacy.read_bytes() == p.read_bytes()
    assert len(tuple(cached_font(legacy).glyphs("A"))) == 2
    converted = import_font(p, library)
    assert Path(converted["path"]) != legacy and legacy.read_bytes() == p.read_bytes()
