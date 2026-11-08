"""Restore public Windows build inputs and check them against release provenance."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs/releases"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def restore(archive, target, record):
    if target.is_file() and digest(target) == record["sha256"]:
        return
    if target.exists() or target.is_symlink():
        raise ValueError(f"已有文件与发布记录不符，保留原文件 {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        staged = Path(directory) / "resource"
        with archive.open(record["member"]) as source, staged.open("wb") as output:
            shutil.copyfileobj(source, output)
        if digest(staged) != record["sha256"]:
            raise ValueError(f"资源哈希不符 {target}")
        os.link(staged, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Version with records under docs/releases, such as 0.1.59")
    parser.add_argument("archive", type=Path, nargs="?", help="Original Windows release ZIP")
    parser.add_argument("--resources-only", action="store_true",
                        help="Verify locked public resources for a newer source checkout")
    args = parser.parse_args()
    version = args.version
    if any(not part.isascii() or not part.isdecimal() for part in version.split(".")) or len(version.split(".")) != 3:
        parser.error("请输入三段式应用版本")
    try:
        resources = json.loads((RECORDS / f"{version}-windows-resources.json").read_bytes())
        source_hashes = {} if args.resources_only else json.loads(
            (RECORDS / f"{version}-build-provenance.json").read_bytes())["source_hashes"]
        if args.archive:
            if digest(args.archive) != resources["sha256"]:
                raise ValueError("Windows 发布 ZIP 与归档哈希不符")
            with ZipFile(args.archive) as archive:
                for path, record in resources["resources"].items():
                    restore(archive, ROOT / path, record)
        expected = {path: record["sha256"] for path, record in resources["resources"].items()}
        expected.update(source_hashes)
        mismatches = [path for path, value in expected.items()
                      if not (ROOT / path).is_file() or digest(ROOT / path) != value]
        if mismatches:
            raise ValueError("构建输入缺失或哈希不符\n" + "\n".join(mismatches))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"InkStruct {version} · {len(source_hashes)} 项源码输入及 {len(resources['resources'])} 项资源校验通过")


if __name__ == "__main__":
    main()
