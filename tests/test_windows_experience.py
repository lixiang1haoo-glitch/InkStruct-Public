import json
from hashlib import sha256
from pathlib import Path
import runpy
from zipfile import ZipFile

import pytest

from inkstruct.fonts import APP_VERSION

builder = runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging/build_windows_experience.py"))


def test_experience_packages_preserve_exact_app_files(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    name = f"InkStruct-{APP_VERSION}-Windows-x64"
    zip_path = base / f"{name}.zip"
    exe_path = base / f"{name}-Installer.exe"
    shared = {"InkStruct/InkStruct.exe": b"app", "InkStruct/_internal/module.pyd": b"module"}
    with ZipFile(zip_path, "w") as archive:
        for member, content in shared.items():
            archive.writestr(member, content)
    exe_path.write_bytes(b"installer")
    zip_hash = sha256(zip_path.read_bytes()).hexdigest()
    exe_hash = sha256(exe_path.read_bytes()).hexdigest()
    records = {
        "portable-verification.json": {"app_version": APP_VERSION, "archive": zip_path.name, "archive_sha256": zip_hash},
        "installer-build.json": {"file": exe_path.name, "input_zip_sha256": zip_hash, "sha256": exe_hash},
        "installer-verification.json": {"native": {"app_version": APP_VERSION}, "installer_sha256": exe_hash,
                                       "uninstall_preserved_synthetic_user_data": True,
                                       "installed_zip_members_exact": len(shared)},
    }
    for record, value in records.items():
        (base / record).write_text(json.dumps(value), encoding="utf-8")
    (base / "commit.txt").write_text("a" * 40, encoding="utf-8")
    font = tmp_path / "original.inkfont"
    template = tmp_path / "original.json"
    font.write_bytes(b"test font")
    template.write_bytes(b"test template")
    resources = {builder["FONT"]: font, builder["TEMPLATE"]: template}
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"resources": {key: {"bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest()} for key, path in resources.items()}}), encoding="utf-8")

    output = tmp_path / "output"
    result = builder["build"](base, output, font, template, lock=lock)
    extras = {"示例资源/" + key: path.read_bytes() for key, path in resources.items()}
    for row, originals in zip(result["assets"], (shared, {exe_path.name: exe_path.read_bytes()}), strict=True):
        with ZipFile(output / row["name"]) as archive:
            assert {name: archive.read(name) for name in archive.namelist()} == originals | extras
    assert result["portable_shared_member_count"] == len(shared)
    assert sha256(zip_path.read_bytes()).hexdigest() == zip_hash
    assert sha256(exe_path.read_bytes()).hexdigest() == exe_hash
    font.write_bytes(b"modified!")
    with pytest.raises(ValueError, match="SHA-256"):
        builder["build"](base, tmp_path / "bad", font, template, lock=lock)
    assert not (tmp_path / "bad").exists()
