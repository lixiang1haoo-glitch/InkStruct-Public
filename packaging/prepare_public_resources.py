"""Download hash-locked upstream inputs and rebuild the portable structure database."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = Path(__file__).with_name("public-resources.lock.json")
DATABASE = ROOT / "artifacts/structures/characters.sqlite3"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(relative_path, record):
    target = ROOT / relative_path
    if target.is_symlink():
        raise ValueError(f"Refusing resource symlink: {relative_path}")
    if target.exists():
        if digest(target) != record["sha256"]:
            raise ValueError(f"Existing resource has the wrong hash: {relative_path}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        staged = Path(temporary) / "resource"
        request = urllib.request.Request(record["url"], headers={"User-Agent": "InkStruct resource verifier"})
        with urllib.request.urlopen(request, timeout=60) as source, staged.open("wb") as output:
            shutil.copyfileobj(source, output)
        if digest(staged) != record["sha256"]:
            raise ValueError(f"Downloaded resource has the wrong hash: {relative_path}")
        os.link(staged, target)


def rebuild(target, revision, locale_set, data_revision):
    from inkstruct.character_sets import CharacterSets
    from inkstruct.structures import build_database

    source = ROOT / "third_party/makemeahanzi"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        folder = Path(temporary)
        simplified = folder / "simplified.txt"
        simplified.write_text("".join(CharacterSets().characters(locale_set)), encoding="utf-8")
        staged = folder / target.name
        build_database(source / "graphics.txt", source / "dictionary.txt", staged,
                       simplified_path=simplified, source_version=revision)
        connection = sqlite3.connect(staged)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            metadata = {
                "created_at": "2026-11-09T00:00:00+00:00",
                "graphics_path": "third_party/makemeahanzi/graphics.txt",
                "dictionary_path": "third_party/makemeahanzi/dictionary.txt",
                "license_graphics": "Arphic Public License",
                "license_dictionary": "LGPL-3.0-or-later",
                "transformation": f"{data_revision}: graph extraction, coordinate normalization and locale labeling",
                "license_notice": "See licenses/THIRD_PARTY_NOTICES.md and the Make Me a Hanzi license texts",
            }
            connection.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)", metadata.items())
            connection.commit()
            connection.execute("VACUUM")
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Structure database integrity check failed")
        finally:
            connection.close()
        os.link(staged, target)


def verify_structure(path, expected):
    from inkstruct.structures import StructureRepository

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        count, = connection.execute("SELECT count(*) FROM characters").fetchone()
    logical_hash = StructureRepository(path).content_sha256()
    file_hash = digest(path)
    if (count, logical_hash, file_hash) != (
        expected["characters"], expected["content_sha256"], expected["file_sha256"]
    ):
        raise ValueError("Structure database differs from the locked content or file hash")
    if (metadata.get("graphics_path"), metadata.get("dictionary_path")) != (
        "third_party/makemeahanzi/graphics.txt", "third_party/makemeahanzi/dictionary.txt"
    ) or not metadata.get("transformation", "").startswith(expected["revision"] + ":"):
        raise ValueError("Structure database lacks portable provenance")
    return {"characters": count, "content_sha256": logical_hash, "file_sha256": file_hash}


def main():
    sys.path.insert(0, str(ROOT / "src"))
    lock = json.loads(LOCK.read_bytes())
    for path, record in lock["downloads"].items():
        fetch(path, record)
    expected = lock["structure"]
    if DATABASE.is_symlink():
        raise ValueError("Refusing structure database symlink")
    if DATABASE.exists():
        result = verify_structure(DATABASE, expected)
    else:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=DATABASE.parent) as directory:
            staged = Path(directory) / DATABASE.name
            rebuild(staged, lock["makemeahanzi_revision"], expected["locale_set"], expected["revision"])
            result = verify_structure(staged, expected)
            os.link(staged, DATABASE)
    print(json.dumps({"verified_downloads": len(lock["downloads"]), "structure": result}, indent=2))


if __name__ == "__main__":
    main()
