"""Install a verified local wheelhouse into a new private environment, without an index."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path, PurePosixPath


def verify(root, *, check_host=True):
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    if manifest.get("schema_version") != "inkstruct_editor_offline_v1":
        raise ValueError("不支持的离线包版本")
    if check_host:
        if sys.version_info[:2] != (3, 13):
            raise ValueError("此依赖包需要 Python 3.13；不会修改已有 Python 环境")
        target = manifest["target"]
        machine = platform.machine().lower()
        if target == "macos-arm64":
            if (
                sys.platform != "darwin"
                or machine != "arm64"
                or int(platform.mac_ver()[0].split(".")[0]) < 14
            ):
                raise ValueError("此包需要 macOS 14 或更新版本及 Apple Silicon Python")
        elif target == "windows-x64":
            if sys.platform != "win32" or machine not in {"amd64", "x86_64"}:
                raise ValueError("此包需要 Windows x64 Python")
        else:
            raise ValueError("未知平台")
    for name, expected in manifest["files"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("校验清单包含不安全路径")
        path = root.joinpath(*relative.parts)
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError("离线包中不允许符号链接")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"文件缺失或校验失败：{name}")
    actual_wheels = {p.relative_to(root).as_posix() for p in (root / "wheels").iterdir()}
    listed_wheels = {name for name in manifest["files"] if name.startswith("wheels/")}
    if actual_wheels != listed_wheels:
        raise ValueError("依赖目录与校验清单不一致")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="InkStruct 离线安装；需要匹配平台的 Python 3.13")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        verify(root)
        if args.verify_only:
            print("离线包校验通过")
            return 0
        runtime = root / "runtime"
        if runtime.exists() or runtime.is_symlink():
            raise ValueError("runtime 已存在；请启动应用，或将离线包解压到新的目录重新安装")
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        subprocess.run([sys.executable, "-I", "-m", "venv", str(runtime)], check=True, env=env)
        python = runtime / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "--isolated",
                "install",
                "--no-cache-dir",
                "--disable-pip-version-check",
                "--no-index",
                "--only-binary=:all:",
                "--find-links",
                str(root / "wheels"),
                "--require-hashes",
                "-r",
                str(root / "requirements.lock"),
            ],
            check=True,
            env=env,
        )
        subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "check"], check=True, env=env)
        print("安装完成。使用本目录的启动脚本；验证可运行 runtime 中的 Python 执行 smoke.py。")
        return 0
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"安装未完成：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
