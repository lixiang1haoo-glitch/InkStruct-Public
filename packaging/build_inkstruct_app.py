"""Build a native editor bundle in a new directory with private build caches."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import plistlib
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_macos_bundle(bundle: Path) -> dict:
    """Reject bundles that show windows but cannot acquire normal macOS focus."""
    with (bundle / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleExecutable") != "InkStruct":
        raise ValueError("macOS 应用入口必须是 InkStruct")
    if info.get("CFBundlePackageType") != "APPL":
        raise ValueError("macOS 包必须声明为 APPL 应用")
    for key in ("LSBackgroundOnly", "LSUIElement"):
        if info.get(key, False) is not False:
            raise ValueError(f"macOS 编辑器不能声明为后台或代理应用：{key}")
    for name in ("InkStruct", "InkStructTool"):
        executable = bundle / "Contents/MacOS" / name
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"macOS 包内可执行文件缺失：{name}")
    return {"foreground_application_metadata_verified": True, "info_plist": info}


def source_snapshot():
    files = [
        *sorted((ROOT / "artifacts/external/data_collection/handwriting_collector").rglob("*.py")),
        ROOT / "artifacts/structures/characters.sqlite3",
        *sorted((ROOT / "src/inkstruct").rglob("*.py")),
        *sorted((ROOT / "src/inkstruct/editor/resources").glob("*.*")),
        ROOT / "pyproject.toml",
        ROOT / "third_party/makemeahanzi/graphics.txt",
        ROOT / "third_party/makemeahanzi/dictionary.txt",
        ROOT / "third_party/makemeahanzi/COPYING",
        ROOT / "third_party/makemeahanzi/LGPL",
        *sorted((ROOT / "third_party/makemeahanzi/APL").rglob("*.TXT")),
        *sorted((ROOT / "third_party/runtime-licenses").glob("*.txt")),
        ROOT / "LICENSE",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "packaging/public-resources.lock.json",
        ROOT / "packaging/windows-x64-py313.lock",
        ROOT / "packaging/prepare_public_resources.py",
        ROOT / "packaging/verify_public_windows.py",
        ROOT / "packaging/nsis-win.lock.json",
        ROOT / "packaging/InkStruct.nsi",
        ROOT / "packaging/build_windows_installer.py",
        ROOT / "packaging/verify_windows_installer.py",
        *sorted((ROOT / "configs").rglob("*.json")),
        *sorted((ROOT / "configs/character_sets").glob("*.txt")),
        ROOT / "packaging/inkstruct_app.spec",
        ROOT / "packaging/inkstruct_launcher.py",
        ROOT / "packaging/inkstruct_layout_launcher.py",
        ROOT / "packaging/inkstruct_layout_smoke.py",
        ROOT / "packaging/inkstruct_smoke.py",
        Path(__file__).resolve(),
    ]
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layout-preview", action="store_true")
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        raise ValueError("请在目标 macOS 或 Windows 上构建，不提供交叉编译")
    output = args.output.resolve()
    if output.exists() or args.output.is_symlink():
        raise ValueError("构建目录已存在，请指定新的目录")
    versions = {
        name: importlib.metadata.version(name)
        for name in (
            "PyInstaller",
            "pyinstaller-hooks-contrib",
            "numpy",
            "Pillow",
            "PySide6",
            "markdown-it-py",
            "matplotlib",
        )
    }
    before = source_snapshot()
    output.mkdir(parents=True, exist_ok=False)
    (output / "source-before.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
    env = {**os.environ, "PYINSTALLER_CONFIG_DIR": str(output / "cache"),
           "INKSTRUCT_BUILD_LAYOUT_PREVIEW": "1" if args.layout_preview else "0"}
    if sys.platform == "win32":
        windows = Path(os.environ["SystemRoot"])
        env["PATH"] = os.pathsep.join(str(path) for path in (
            Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows
        ))
    with (output / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--clean",
                "--distpath",
                str(output / "dist"),
                "--workpath",
                str(output / "work"),
                str(ROOT / "packaging/inkstruct_app.spec"),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    if before != source_snapshot():
        raise ValueError("构建期间源码发生变化，当前包不可作为冻结版本验收；请检查后重建")
    bundle_validation = (
        validate_macos_bundle(output / "dist/InkStruct.app") if sys.platform == "darwin" else {}
    )
    (output / "build-provenance.json").write_text(
        json.dumps(
            {
                "application_version": runpy.run_path(str(ROOT / "src/inkstruct/fonts/__init__.py"))["APP_VERSION"],
                "layout_preview": args.layout_preview,
                "python": sys.version,
                "platform": sys.platform,
                "versions": versions,
                "source_hashes": before,
                "source_unchanged_during_build": True,
                "runtime_verified": False,
                "bundle_validation": bundle_validation,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output / "dist")


if __name__ == "__main__":
    main()
