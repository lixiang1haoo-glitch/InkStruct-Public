"""Prepare a small Windows source/build kit without profiles or user samples."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from inkstruct.collector import _collector_source
from inkstruct.stroke_reference import write_reference_bundle
from inkstruct.structures import StructureRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=False)
    for module in (
        "__init__.py",
        "schemas.py",
        "capture_boundary.py",
        "stroke_reference.py",
        "symbol_capture.py",
        "symbol_capture_ui.py",
    ):
        destination = target / "inkstruct" / module
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(root / "src/inkstruct" / module, destination)
    shutil.copytree(
        _collector_source() / "handwriting_collector",
        target / "handwriting_collector",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for source, name in [
        (root / "packaging/portable_collector.py", "portable_collector.py"),
        (root / "packaging/PORTABLE_README.txt", "使用说明.txt"),
        (root / "configs/collection/symbols_5.csv", "symbols_5.csv"),
        (root / "docs/SYMBOL_CAPTURE.md", "SYMBOL_CAPTURE.md"),
        (root / "LICENSE", "LICENSE"),
        (root / "THIRD_PARTY_DATA.md", "THIRD_PARTY_DATA.md"),
    ]:
        shutil.copy2(source, target / name)
    repository = StructureRepository(root / "artifacts/structures/characters.sqlite3")
    write_reference_bundle(
        target / "stroke_references.json.gz",
        {g.character: [s.median for s in g.strokes] for g in repository.iter_graphs()},
        source=repository.metadata(),
    )
    (target / "requirements.txt").write_text(
        "numpy>=2.1,<3\nPySide6==6.9.2\npyinstaller>=6,<7\n", encoding="utf-8"
    )
    # ASCII batch files avoid code-page dependent command parsing on Windows.
    setup = """@echo off
cd /d "%~dp0"
if exist .venv\\Scripts\\python.exe goto install
py -3.13 -m venv .venv
if errorlevel 1 py -3.12 -m venv .venv
if not exist .venv\\Scripts\\python.exe goto fail
:install
.venv\\Scripts\\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\\Scripts\\python.exe portable_collector.py --self-test=self-test.json
if errorlevel 1 goto fail
.venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name InkStructCollector --add-data "stroke_references.json.gz;." --collect-data handwriting_collector portable_collector.py
if errorlevel 1 goto fail
copy /y symbols_5.csv dist\\InkStructCollector\\symbols_5.csv >nul
echo Build ready: dist\\InkStructCollector\\InkStructCollector.exe
pause
exit /b 0
:fail
echo Build failed. Install Python 3.12 or 3.13 and check the error above.
pause
exit /b 1
"""
    (target / "build_windows.cmd").write_bytes(setup.replace("\n", "\r\n").encode("ascii"))
    (target / "run_windows.cmd").write_bytes(
        b'@echo off\r\ncd /d "%~dp0"\r\n.venv\\Scripts\\python.exe portable_collector.py\r\n'
    )
    (target / "开始使用.txt").write_text(
        "这是 Windows 源码构建包，不是已编译 exe。\n"
        "1. 在 Windows 安装 Python 3.12 或 3.13（需包含 py 启动器）。\n"
        "2. 解压到可写文件夹，联网双击 build_windows.cmd，首次下载依赖并构建。\n"
        "3. 构建完成后运行 dist/InkStructCollector/InkStructCollector.exe。\n"
        "   之后分享整个 InkStructCollector 文件夹即可，无需 Python。\n"
        "4. 选择“字母与符号 · 5 份”页，填写书写者 ID，选择分组并创建任务。\n"
        "本包不含个人样本、档案或生成器；本次未在 Windows 真机验证。\n",
        encoding="utf-8",
    )
    archive = shutil.make_archive(str(target), "zip", target.parent, target.name)
    print(json.dumps({"directory": str(target), "archive": archive}, ensure_ascii=False))


if __name__ == "__main__":
    main()
