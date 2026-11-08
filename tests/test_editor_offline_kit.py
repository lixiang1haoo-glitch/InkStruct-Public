"""Offline materials fail closed on platform, wheel identity and integrity problems."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("offline_builder", ROOT / "packaging/build_editor_offline_kit.py")
installer = load("offline_installer", ROOT / "packaging/editor_offline/install.py")


def wheel(path, name, version="1.0", tag="py3-none-any"):
    normalized = name.replace("-", "_")
    result = path / f"{normalized}-{version}-{tag}.whl"
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr(
            f"{normalized}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n"
        )
    return result


def fixtures(tmp_path):
    house = tmp_path / "wheels"
    house.mkdir()
    for name in builder.REQUIRED - {"inkstruct"}:
        wheel(house, name)
    project = wheel(tmp_path, "inkstruct", "0.2.0")
    return house, project, tmp_path / "kit"


def test_materials_hash_lock_and_no_existing_output_replacement(tmp_path):
    house, project, output = fixtures(tmp_path)
    manifest = builder.assemble(house, project, output, "macos-arm64")
    assert installer.verify(output, check_host=False) == manifest
    lock = (output / "requirements.lock").read_text()
    assert "inkstruct[desktop]==0.2.0 --hash=sha256:" in lock
    assert len(lock.splitlines()) == len(builder.REQUIRED)
    assert not (output / "runtime").exists()
    assert not manifest["includes_python_runtime"] and not manifest["native_platform_verified"]
    saved = (output / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        builder.assemble(house, project, output, "macos-arm64")
    assert (output / "manifest.json").read_bytes() == saved


@pytest.mark.parametrize("failure", ["missing", "duplicate", "wrong-platform", "metadata"])
def test_reject_bad_wheelhouse_before_publishing(tmp_path, failure):
    house, project, output = fixtures(tmp_path)
    if failure == "missing":
        next(house.glob("numpy-*.whl")).unlink()
    elif failure == "duplicate":
        wheel(house, "numpy", "2.0")
    elif failure == "wrong-platform":
        next(house.glob("numpy-*.whl")).unlink()
        wheel(house, "numpy", tag="cp313-cp313-win_amd64")
    else:
        target = next(house.glob("numpy-*.whl"))
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("numpy-1.0.dist-info/METADATA", "Name: different\nVersion: 1.0\n")
    with pytest.raises(ValueError):
        builder.assemble(house, project, output, "macos-arm64")
    assert not output.exists()


@pytest.mark.parametrize("failure", ["corrupt", "extra-wheel", "traversal", "symlink", "missing"])
def test_integrity_rejects_damage_before_any_runtime_changes(tmp_path, failure):
    house, project, output = fixtures(tmp_path)
    builder.assemble(house, project, output, "windows-x64")
    manifest = json.loads((output / "manifest.json").read_text())
    if failure == "corrupt":
        (output / "requirements.lock").write_text("changed")
    elif failure == "extra-wheel":
        wheel(output / "wheels", "extra")
    elif failure == "traversal":
        manifest["files"]["../outside"] = "a" * 64
        (output / "manifest.json").write_text(json.dumps(manifest))
    elif failure == "symlink":
        target = output / "requirements.lock"
        data = target.read_bytes()
        target.unlink()
        outside = tmp_path / "outside"
        outside.write_bytes(data)
        target.symlink_to(outside)
    else:
        (output / "smoke.py").unlink()
    with pytest.raises(ValueError):
        installer.verify(output, check_host=False)
    assert not (output / "runtime").exists()


def test_host_mismatch_rejected(tmp_path, monkeypatch):
    house, project, output = fixtures(tmp_path)
    builder.assemble(house, project, output, "windows-x64")
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    with pytest.raises(ValueError):
        installer.verify(output)
