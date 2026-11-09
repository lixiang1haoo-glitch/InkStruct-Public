"""Verify a Windows bundle using only programmatically generated glyph samples."""
from __future__ import annotations

import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

from inkstruct.fonts import APP_VERSION
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font


def synthetic_font(output):
    samples = output / "synthetic-symbols"
    samples.mkdir()
    for index, char in enumerate("0123456789+-=()[]"):
        record = {
            "schema_version": "inkstruct_symbol_sample_v1",
            "character": char,
            "sample_id": f"synthetic-{ord(char):04x}",
            "writer_id": "fixture",
            "capture": {"coordinate_space": "logical_px"},
            "guides": {"em_px": 100, "origin_x_px": 10, "baseline_y_px": 80},
            "strokes": [{"points": [
                {"x": 20, "y": 20 + index, "t_ms": 0, "pressure": 0.5},
                {"x": 40 + index, "y": 55, "t_ms": 40, "pressure": 0.5},
                {"x": 35, "y": 78, "t_ms": 80, "pressure": 0.5},
            ]}],
        }
        (samples / f"{ord(char):04x}.json").write_text(json.dumps(record), encoding="utf-8")
    target = output / "synthetic-font.inkfont"
    build_font(target, writer="fixture", name="Synthetic verification font", symbols=samples)
    FontPackage(target).verify()
    return target


def verify(executable, name, flag, font, output):
    directory = output / name
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    env["QT_QPA_PLATFORM"] = "windows" if flag == "--windows-style-check" else "offscreen"
    with (output / f"{name}.log").open("wb") as log:
        subprocess.run([str(executable), "--inkstruct-check", flag, "--font", str(font),
                        "--output", str(directory)], cwd=executable.parent, env=env,
                       stdout=log, stderr=subprocess.STDOUT, timeout=120,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    report = json.loads((directory / "verification.json").read_bytes())
    if report.get("app_version") != APP_VERSION or not report.get("frozen"):
        raise ValueError(f"Version or packaged runtime mismatch: {name}")
    return {key: value for key, value in report.items() if key != "executable"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    archive_path = output / f"InkStruct-{APP_VERSION}-Windows-x64.zip"
    with ZipFile(archive_path, "x", ZIP_DEFLATED, compresslevel=4) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.write(path, f"InkStruct/{path.relative_to(bundle).as_posix()}")
    extracted = output / "extracted"
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        retired = {"line_tasks.py", "exporter.py", "builtin_diffink_220.json"}
        if any(Path(member).name in retired for member in archive.namelist()):
            raise ValueError("ZIP contains a retired line-capture component")
        for member in archive.namelist():
            name = member.lower()
            if "virtualkeyboard" in name or "/matplotlib/mpl-data/sample_data/" in name:
                raise ValueError(f"ZIP contains an unused dependency resource: {member}")
            filename = Path(name).name
            if name.endswith(".dll") and (
                filename == "ucrtbase.dll" or filename.startswith("api-ms-win-")
                or (filename.startswith(("vcruntime", "msvcp", "concrt")) and "-" not in filename)
            ):
                raise ValueError(f"ZIP contains an app-local Windows runtime: {member}")
        archive.extractall(extracted)
    font = synthetic_font(output)
    reports = {}
    for app in ("InkStruct", "InkStructTool"):
        executable = extracted / "InkStruct" / f"{app}.exe"
        math = verify(executable, f"{app}-math", "--math-settings-check", font, output)
        native = verify(executable, f"{app}-native", "--windows-style-check", font, output)
        if (math["formula_categories"], math["measured_dimensions"]) != (11, 26):
            raise ValueError(f"Formula smoke did not cover all dimensions: {app}")
        if native["style"] != "windows11" or not native["formula_geometry_unchanged"] or not native["handwritten_glyphs"]:
            raise ValueError(f"Native smoke did not cover both themed previews: {app}")
        reports[app] = {"math": math, "native": native}
    with archive_path.open("rb") as stream:
        sha256 = file_digest(stream, "sha256").hexdigest()
    report = {"app_version": APP_VERSION, "archive": archive_path.name,
              "archive_sha256": sha256, "archive_bytes": archive_path.stat().st_size, "checks": reports}
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
