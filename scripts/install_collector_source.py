"""Install one pinned source dependency pack without replacing existing files."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "configs/dependencies/collector-source-20261022.json"


def install(archive_path: Path) -> Path:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != lock["sha256"]:
        raise ValueError("Collector source archive hash does not match the pinned manifest")
    destination = ROOT / "artifacts/external/data_collection"
    if destination.exists():
        raise FileExistsError(f"Existing collector directory preserved: {destination}")
    expected = {"handwriting_collector/" + name: digest for name, digest in lock["files"].items()}
    with ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != {*expected, "manifest.json"}:
            raise ValueError("Archive members do not match the pinned file list")
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Unsupported source archive member")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema_version") != lock["schema_version"] or manifest.get("files") != lock["files"]:
            raise ValueError("Internal source manifest differs from the pinned manifest")
        content = {name: archive.read(name) for name in expected}
        for name, data in content.items():
            if hashlib.sha256(data).hexdigest() != expected[name]:
                raise ValueError(f"Source member hash mismatch: {name}")
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in content.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(install(args.archive.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
