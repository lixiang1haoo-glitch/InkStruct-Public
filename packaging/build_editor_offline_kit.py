"""Assemble platform-specific, hash-locked editor installation materials from wheels."""

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from pip._vendor.packaging.tags import compatible_tags, cpython_tags, mac_platforms
from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "inkstruct",
    "numpy",
    "pillow",
    "markdown-it-py",
    "mdurl",
    "pyside6",
    "pyside6-addons",
    "pyside6-essentials",
    "shiboken6",
}


def assemble(wheelhouse, project_wheel, output, target):
    if target not in {"macos-arm64", "windows-x64"}:
        raise ValueError("Unsupported target")
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; choose a new directory")
    platforms = list(mac_platforms((14, 0), "arm64")) if target == "macos-arm64" else ["win_amd64"]
    supported = set(cpython_tags((3, 13), abis=["cp313"], platforms=platforms)) | set(
        compatible_tags((3, 13), interpreter="cp313", platforms=platforms)
    )
    wheels = [project_wheel, *sorted(wheelhouse.glob("*.whl"))]
    packages = {}
    for path in wheels:
        name, version, _, tags = parse_wheel_filename(path.name)
        if name in packages or name not in REQUIRED or not supported.intersection(tags):
            raise ValueError(f"Duplicate, unexpected or incompatible wheel: {path.name}")
        with zipfile.ZipFile(path) as archive:
            metadata_paths = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
            if len(metadata_paths) != 1:
                raise ValueError(f"Invalid wheel metadata: {path.name}")
            metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
            if canonicalize_name(metadata["Name"]) != name or metadata["Version"] != str(version):
                raise ValueError(f"Wheel identity mismatch: {path.name}")
        packages[name] = {
            "version": str(version),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "wheel": path.name,
        }
    if set(packages) != REQUIRED:
        raise ValueError(f"Missing runtime wheels: {sorted(REQUIRED - set(packages))}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".editor-kit-", dir=output.parent) as temp:
        stage = Path(temp) / "kit"
        (stage / "wheels").mkdir(parents=True)
        for path in wheels:
            shutil.copyfile(path, stage / "wheels" / path.name)
        lines = []
        for name, item in sorted(packages.items()):
            requirement = name + ("[desktop]" if name == "inkstruct" else "")
            lines.append(f"{requirement}=={item['version']} --hash=sha256:{item['sha256']}")
        (stage / "requirements.lock").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for name in ("install.py", "smoke.py", "README.txt"):
            shutil.copyfile(ROOT / "packaging/editor_offline" / name, stage / name)
        (stage / "examples").mkdir()
        shutil.copyfile(
            ROOT / "examples/template_authoring_demo.md",
            stage / "examples/template_authoring_demo.md",
        )
        shutil.copyfile(
            ROOT / "configs/templates/generic-record-v2.json",
            stage / "examples/generic-record-v2.json",
        )
        (stage / "启动编辑器.command").write_text(
            '#!/bin/bash\nset -euo pipefail\ncd "$(dirname "$0")"\nexec runtime/bin/python -I -m inkstruct.editor.app "$@"\n',
            encoding="utf-8",
        )
        (stage / "启动编辑器.command").chmod(0o755)
        (stage / "启动编辑器.cmd").write_bytes(
            b'@echo off\r\ncd /d "%~dp0"\r\n"runtime\\Scripts\\python.exe" -I -m inkstruct.editor.app %*\r\n'
        )
        files = {
            p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(stage.rglob("*"))
            if p.is_file()
        }
        manifest = {
            "schema_version": "inkstruct_editor_offline_v1",
            "target": target,
            "python": "3.13",
            "packages": packages,
            "files": files,
            "includes_python_runtime": False,
            "native_platform_verified": False,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # Publish to a newly claimed directory, never replace an existing kit.
        output.mkdir(exist_ok=False)
        for path in stage.iterdir():
            shutil.move(str(path), output / path.name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--project-wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", choices=("macos-arm64", "windows-x64"), required=True)
    args = parser.parse_args()
    manifest = assemble(args.wheelhouse, args.project_wheel, args.output, args.target)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "target": args.target,
                "packages": manifest["packages"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
