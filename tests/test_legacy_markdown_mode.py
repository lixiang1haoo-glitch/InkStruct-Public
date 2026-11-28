"""An old native dialect remains readable, with literal source and current output grammar."""
import hashlib
import json
from zipfile import ZipFile

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import dialect_version, parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle


def test_open_and_resave_legacy_dialect(tmp_path):
    source = "[[目标|标签]]\n\n> [!note] 12"
    path = tmp_path / "old.inkdoc"
    save_package(path, SourceSession(source), AssetResolver(builtin_numbers=True),
                 PageProfile(), StyleProfile(), flow=FlowStyle())
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    styles = json.loads(files["styles.json"])
    styles["flow"]["markdown_dialect"] = "obsidian"
    files["styles.json"] = json.dumps(styles).encode()
    manifest = json.loads(files["manifest.json"])
    manifest["sha256"]["styles.json"] = hashlib.sha256(files["styles.json"]).hexdigest()
    manifest["dialect"] = "inkstruct-obsidian-static-v1/markdown-it-py-4.0.0/break-commands-v2"
    files["manifest.json"] = json.dumps(manifest).encode()
    with ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    old = path.read_bytes()
    loaded = load_package(path)
    assert loaded.flow.source_dialect == "markdown" and loaded.session.source == source
    assert path.read_bytes() == old
    assert "[[目标|标签]]" in "".join(o.text for o in parse_markdown(loaded.session).occurrences)
    new = tmp_path / "new.inkdoc"
    save_package(new, loaded.session, loaded.resolver, loaded.page, loaded.style, flow=loaded.flow)
    assert load_package(new).session.source == source
    with ZipFile(new) as archive:
        assert json.loads(archive.read("manifest.json"))["dialect"] == dialect_version("markdown")

