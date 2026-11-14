"""Verify a Windows bundle using only programmatically generated glyph samples."""
from __future__ import annotations

import argparse
from base64 import b64decode
from hashlib import file_digest
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from inkstruct.fonts import APP_VERSION
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font
from windows_bundle import excluded_binary


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


def system_environment():
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    return env


def verify(executable, name, flag, font, output):
    directory = output / name
    env = system_environment()
    env["QT_QPA_PLATFORM"] = "windows" if flag == "--windows-style-check" else "offscreen"
    with (output / f"{name}.log").open("wb") as log:
        arguments = [str(executable), "--inkstruct-check", flag, "--output", str(directory)]
        if font is not None:
            arguments.extend(("--font", str(font)))
        subprocess.run(arguments, cwd=executable.parent, env=env,
                       stdout=log, stderr=subprocess.STDOUT, timeout=120,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    report = json.loads((directory / "verification.json").read_bytes())
    if report.get("app_version") != APP_VERSION or not report.get("frozen"):
        raise ValueError(f"Version or packaged runtime mismatch: {name}")
    return {key: value for key, value in report.items() if key != "executable"}


def verify_pdf_worker(executable, output):
    pdf = output / "synthetic-reference.pdf"
    broken = output / "invalid-reference.pdf"
    broken.write_bytes(b"Not a PDF\n")
    first = Image.new("RGB", (600, 800), (210, 20, 30))
    second = Image.new("RGB", (800, 600), (10, 30, 210))
    first.save(pdf, save_all=True, append_images=[second], resolution=144)
    requests = [
        {"action": "open", "path": str(broken)},
        {"action": "open", "path": str(pdf)},
        {"action": "render", "index": 1},
        {"action": "render", "index": 2},
    ]
    completed = subprocess.run(
        [str(executable), "--inkstruct-pdf-worker"],
        input=b"".join(json.dumps(row).encode("utf-8") + b"\n" for row in requests),
        capture_output=True, cwd=executable.parent, env=system_environment(),
        timeout=45, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    (output / "pdf-worker.log").write_bytes(completed.stderr)
    completed.check_returncode()
    invalid, opened, rendered, out_of_bounds = map(json.loads, completed.stdout.splitlines())
    assert not invalid["ok"] and not out_of_bounds["ok"]
    assert opened["ok"] and opened["result"]["page_count"] == 2
    assert rendered["ok"], rendered
    page = rendered["result"]
    assert all(abs(a - b) < .01 for a, b in zip(page["size_mm"], (800 * 25.4 / 144, 600 * 25.4 / 144)))
    png = b64decode(page["background"]["png_base64"], validate=True)
    (output / "pdf-rendered.png").write_bytes(png)
    with Image.open(BytesIO(png)) as image:
        assert image.size == (1600, 1200)
        pixel = image.convert("RGB").getpixel((800, 600))
        assert pixel[2] > 150 and pixel[0] < 60
    return {"pages": 2, "rendered_page": 2, "size_mm": page["size_mm"],
            "pixels": [1600, 1200], "invalid_pdf_and_page_rejected": True}


def verify_cpu_preview(executable, output):
    directory = output / "raster"
    directory.mkdir()
    # The full page fits the CPU budget but exceeds the GPU buffer budget.
    width, height = 6144, 1024
    (directory / "1.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="red"/></svg>', encoding="ascii",
    )
    env = system_environment()
    env["INKSTRUCT_PREVIEW_BACKEND"] = "gpu"
    request = {"token": 1, "spec": [width, height, 1], "tiles": [[-1, -1]]}
    completed = subprocess.run(
        [str(executable), "--inkstruct-preview-worker", str(directory)],
        input=json.dumps(request).encode("ascii") + b"\n",
        capture_output=True, cwd=executable.parent, env=env,
        timeout=45, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    (output / "raster-worker.log").write_bytes(completed.stderr)
    completed.check_returncode()
    result = json.loads(completed.stdout)
    assert result["backend"] == "cpu" and result["gpu_fallback"], result
    pixels = (directory / "1--1--1.argb").read_bytes()
    assert len(pixels) == width * height * 4 and pixels[:4] == b"\x00\x00\xff\xff"
    return result


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
            if excluded_binary(name):
                raise ValueError(f"ZIP contains an excluded Windows dependency: {member}")
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
        if not native["sample_library_handoff"]:
            raise ValueError(f"Native smoke did not verify sample library handoff: {app}")
        reports[app] = {"math": math, "native": native}
    tool = extracted / "InkStruct/InkStructTool.exe"
    generation = verify(tool, "v631-generation", "--v631-check", None, output)
    pdf = verify_pdf_worker(tool, output)
    raster = verify_cpu_preview(tool, output)
    with archive_path.open("rb") as stream:
        sha256 = file_digest(stream, "sha256").hexdigest()
    report = {"app_version": APP_VERSION, "archive": archive_path.name,
              "archive_sha256": sha256, "archive_bytes": archive_path.stat().st_size,
              "checks": reports, "pdf": pdf, "gpu_fallback": raster, "v631_generation": generation}
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
