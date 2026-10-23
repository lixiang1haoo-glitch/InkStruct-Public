import io
import json
import zipfile
from dataclasses import asdict
from hashlib import sha256

import pytest
from test_document_layout import provider
from test_symbol_provider import asset

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import SymbolProvider
from inkstruct.cli import main
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.layout.blocks import layout_markdown


def test_portable_package_preserves_source_choices_geometry_and_fixed_profiles(tmp_path):
    session = SourceSession("# 人人\r\n\r\n**1.20** 人\r\n" * 8)
    resolver = AssetResolver(
        provider("人"),
        SymbolProvider([asset(sid="one-a"), asset(sid="one-b", height=20)]),
        builtin_numbers=True,
    )
    page, style = PageProfile(90, 110, 10), StyleProfile()
    before = layout_markdown(parse_markdown(session), resolver, page=page, style=style)
    assert before.exportable and len(before.pages) > 1
    target = tmp_path / "saved.inkdoc"
    stamp = save_package(target, session, resolver, page, style, optimize=True)
    restored = load_package(target)
    assert restored.session.source == session.source
    assert restored.session.atom_ids == session.atom_ids
    assert restored.optimize and stamp == restored.file_hash
    after = layout_markdown(
        parse_markdown(restored.session),
        restored.resolver,
        page=restored.page,
        style=restored.style,
    )
    assert asdict(before) == asdict(after)
    assert restored.resolver.selection_records() == resolver.selection_records()
    with pytest.raises(ValueError, match="修改"):
        save_package(target, session, resolver, page, style)
    assert sha256(target.read_bytes()).hexdigest() == stamp


@pytest.mark.parametrize("damage", ["source", "version", "math-version", "geometry", "duplicate"])
def test_invalid_package_cannot_load_or_modify_original(tmp_path, damage):
    path = tmp_path / "original.inkdoc"
    session = SourceSession("1")
    resolver = AssetResolver(builtin_numbers=True)
    layout_markdown(parse_markdown(session), resolver)
    save_package(path, session, resolver, PageProfile(), StyleProfile())
    original = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as z:
        members = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(members["manifest.json"])
    if damage == "source":
        members["source.md"] = b"2"
    elif damage == "version":
        manifest["schema_version"] = "future-v2"
    elif damage == "math-version":
        manifest["math_version"] = "future-math"
    elif damage == "geometry":
        resources = json.loads(members["resources.json"])
        resources[0]["strokes"][0][0][0] += 0.1
        members["resources.json"] = json.dumps(resources).encode()
        manifest["sha256"]["resources.json"] = sha256(members["resources.json"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    broken = tmp_path / "broken.inkdoc"
    with zipfile.ZipFile(broken, "w") as z:
        for name, raw in members.items():
            z.writestr(name, raw)
        if damage == "duplicate":
            with pytest.warns(UserWarning):
                z.writestr("source.md", b"1")
    with pytest.raises(ValueError):
        load_package(broken)
    assert path.read_bytes() == original


def test_package_without_math_metadata_retains_existing_nonmath_geometry(tmp_path):
    path = tmp_path / "before-math.inkdoc"
    session = SourceSession("|1.20|\n|---|\n|0.005|")
    resolver = AssetResolver(builtin_numbers=True)
    before = layout_markdown(parse_markdown(session), resolver)
    save_package(path, session, resolver, PageProfile(), StyleProfile())
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    del manifest["math_version"]
    members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    loaded = load_package(path)
    assert layout_markdown(parse_markdown(loaded.session), loaded.resolver) == before


def test_cli_markdown_project_and_reopened_machine_output_are_equal(tmp_path, capsys):
    source = tmp_path / "numbers.md"
    source.write_text("# 123\n\n**1.20**\n\n1. 0.005\n2. 001")
    project = tmp_path / "portable.inkdoc"
    first, second = tmp_path / "first", tmp_path / "second"
    assert (
        main(
            [
                "document",
                "render",
                str(source),
                "--mode",
                "markdown",
                "--plotter",
                "--optimize-paths",
                "--output",
                str(first),
                "--save-project",
                str(project),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["exportable"]
    assert main(["document", "render", str(project), "--plotter", "--output", str(second)]) == 0
    assert (first / "page-001.svg").read_bytes() == (second / "page-001.svg").read_bytes()


def test_missing_selected_resource_does_not_publish_unopenable_package(tmp_path):
    session = SourceSession("1")
    resolver = AssetResolver(builtin_numbers=True)
    layout_markdown(parse_markdown(session), resolver)
    path = tmp_path / "stable.inkdoc"
    stamp = save_package(path, session, resolver, PageProfile(), StyleProfile())
    broken = AssetResolver(selections=resolver.selections.values())
    with pytest.raises(ValueError, match="selected resource"):
        save_package(path, session, broken, PageProfile(), StyleProfile(), expected_hash=stamp)
    assert sha256(path.read_bytes()).hexdigest() == stamp
