"""Add two locked offline resources to an already verified Windows distribution."""
from __future__ import annotations

import argparse
import json
from hashlib import file_digest, sha256
from pathlib import Path
from shutil import copyfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from inkstruct.fonts import APP_VERSION

RESOURCE_LOCK = Path(__file__).with_name("experience-resources.lock.json")
EXAMPLE_DIR = "示例资源"
FONT = "InkStruct 示例手写体.inkfont"
TEMPLATE = "双页预印教案.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def zip_hashes(path):
    with ZipFile(path) as archive:
        hashes = {}
        for entry in archive.infolist():
            if entry.filename in hashes:
                raise ValueError(f"Duplicate ZIP member: {entry.filename}")
            with archive.open(entry) as stream:
                hashes[entry.filename] = file_digest(stream, "sha256").hexdigest()
        return hashes


def add_resources(archive, resources):
    for name, path in resources.items():
        archive.write(path, f"{EXAMPLE_DIR}/{name}",
                      compress_type=ZIP_STORED if name == FONT else ZIP_DEFLATED)


def build(verified, output, font, template, *, lock=RESOURCE_LOCK):
    portable = load(verified / "portable-verification.json")
    installer_build = load(verified / "installer-build.json")
    installed = load(verified / "installer-verification.json")
    commit = (verified / "commit.txt").read_text(encoding="utf-8-sig").strip()
    base_name = f"InkStruct-{APP_VERSION}-Windows-x64"
    base_zip = verified / f"{base_name}.zip"
    installer = verified / f"{base_name}-Installer.exe"
    if (portable["app_version"] != APP_VERSION or portable["archive"] != base_zip.name
            or installed["native"]["app_version"] != APP_VERSION or installer_build["file"] != installer.name
            or portable["archive_sha256"] != installer_build["input_zip_sha256"]
            or installer_build["sha256"] != installed["installer_sha256"]
            or not installed["uninstall_preserved_synthetic_user_data"]
            or installed["installed_zip_members_exact"] <= 0):
        raise ValueError("基础 ZIP 和安装器必须来自同一次已验证的 Windows 构建")
    if digest(base_zip) != portable["archive_sha256"] or digest(installer) != installer_build["sha256"]:
        raise ValueError("基础分发文件的 SHA-256 与构建验证记录不一致")

    resources = {FONT: font, TEMPLATE: template}
    expected = load(lock)["resources"]
    if expected.keys() != resources.keys():
        raise ValueError("体验资源清单不完整")
    for name, path in resources.items():
        if path.stat().st_size != expected[name]["bytes"] or digest(path) != expected[name]["sha256"]:
            raise ValueError(f"体验资源 SHA-256 或大小不一致：{name}")
    members = {f"{EXAMPLE_DIR}/{name}": expected[name]["sha256"] for name in resources}
    originals = zip_hashes(base_zip)
    if set(members) & originals.keys():
        raise ValueError("基础 ZIP 已包含体验资源路径")

    output.mkdir(parents=True, exist_ok=False)
    portable_out = output / f"{base_name}-Portable-Experience.zip"
    installer_out = output / f"{base_name}-Installer-Experience.zip"
    copyfile(base_zip, portable_out)
    with ZipFile(portable_out, "a") as archive:
        add_resources(archive, resources)
    with ZipFile(installer_out, "x", ZIP_STORED) as archive:
        archive.write(installer, installer.name)
        add_resources(archive, resources)
    if zip_hashes(portable_out) != originals | members:
        raise ValueError("免安装体验包的共享文件或示例资源与原件不一致")
    if zip_hashes(installer_out) != {installer.name: installed["installer_sha256"]} | members:
        raise ValueError("安装体验包的安装程序或示例资源与原件不一致")

    return {
        "application_version": APP_VERSION,
        "commit": commit,
        "resources": {name: {key: expected[name][key] for key in ("bytes", "sha256")} for name in resources},
        "portable_base_sha256": portable["archive_sha256"],
        "portable_shared_member_count": len(originals),
        "portable_shared_members_sha256": sha256(json.dumps(originals, sort_keys=True).encode()).hexdigest(),
        "installer_exe_sha256": installed["installer_sha256"],
        "assets": [{"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
                   for path in (portable_out, installer_out)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.verified, args.output, args.font, args.template)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (args.output / "experience-verification.json").write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
