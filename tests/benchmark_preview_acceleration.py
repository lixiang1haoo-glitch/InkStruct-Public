"""Measure uncached mixed-page first paint through the real Qt preview process."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import monotonic, perf_counter, sleep

from PIL import Image, ImageDraw
from PySide6 import QtCore, QtWidgets

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.han_variation import HanVariation
from inkstruct.document.images import ImageStyle, RasterResource
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.editor.continuous_preview import ContinuousPageCanvas, PreviewScrollArea
from inkstruct.editor.mixed import build_markdown
from inkstruct.global_defaults import GlobalDefaultsStore
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan
from inkstruct.scene.schema import Page


def mixed_snapshot(font, text, work):
    picture = Image.new("RGB", (800, 240), "white")
    pen = ImageDraw.Draw(picture)
    pen.line((45, 18, 45, 200, 755, 200), fill="#53688f", width=4)
    pen.line([(65, 174), (220, 104), (420, 119), (545, 67), (741, 32)],
             fill="#184d87", width=5)
    image_path = work / "trend.png"
    picture.save(image_path)

    paragraphs = text.read_text(encoding="utf-8").strip().split("\n\n")
    combined = "".join(p.strip() for p in paragraphs)
    body = (combined * 2)[:235].rstrip("，。、；") + "。"
    source = (
        body + "\n\n|序号|长度|结果|\n|---|---:|---:|\n|1|3.14|2|\n|2|6.28|4|\n|3|9.42|8|"
        + "\n\n$\\frac{1}{2}+\\frac{3}{4}=\\frac{5}{4}$\n\n![](trend.png)"
    )
    flow = FlowStyle(
        paragraph_gap_mm=0, first_line_indent_mm=10, han_spacing="handwriting",
        latin_spacing="handwriting", punctuation_spacing="handwriting", digits_follow_latin=True,
        paragraph_align="justify", han_variation=HanVariation(
            enabled=True, seed=0, strength=.25, size_strength=.20,
            spacing_strength=.35, baseline_strength=.20,
        ),
        table=TableStyle(width_mm=136), math=MathStyle(fraction_source="geometric"),
        images=(RasterResource.from_file(image_path, "trend.png"),), image=ImageStyle(width_mm=118),
    )
    snapshot = build_markdown(
        SourceSession(source), 1, AssetResolver(seed=0), font, "", PageProfile(),
        StyleProfile(em_mm=5, line_height_mm=5.5), flow, None,
    )["snapshot"]
    if not snapshot.exportable or len(snapshot.pages) != 1 or not snapshot.pages[0].images:
        raise ValueError(f"Expected a single exportable mixed page: {snapshot.diagnostics[:5]}")
    return snapshot


def wait_for_paint(app, canvas, painted, expected):
    deadline = monotonic() + 30
    while not painted or painted[-1][0] is not expected:
        app.processEvents()
        if canvas._errors or monotonic() >= deadline:
            raise RuntimeError(f"Screen preview did not paint: {canvas._errors}")
        sleep(.001)
    return painted[-1][1]


def measure(app, snapshot, accelerate, output=None):
    view = PreviewScrollArea()
    canvas = ContinuousPageCanvas()
    view.setWidget(canvas)
    view.resize(1200, 800)
    canvas.set_render_acceleration(accelerate)
    painted = []
    canvas.first_page_painted.connect(lambda page: painted.append((page, perf_counter())))
    view.show()
    try:
        # Start the real raster process with blank paper; the mixed page has
        # no image or SVG cache entry when the timed request starts.
        warmup = replace(snapshot, pages=(Page(0, (), ()),))
        canvas.load_page(warmup, 0)
        wait_for_paint(app, canvas, painted, warmup)
        before = canvas.statistics()
        started = perf_counter()
        canvas.load_page(snapshot, 0)
        first_paint = wait_for_paint(app, canvas, painted, snapshot)
        after = canvas.statistics()
        if after["render_jobs"] - before["render_jobs"] != 1:
            raise AssertionError("Expected one uncached screen request")
        row = {
            "accelerated": accelerate,
            "screen_spec": canvas._spec(),
            "first_paint_ms": 1000 * (first_paint - started),
            "prepare_svg_with_sampling_ms": 1000 * (after["svg_seconds"] - before["svg_seconds"]),
            "raster_ms": 1000 * (after["raster_seconds"] - before["raster_seconds"]),
        }
        if output is not None:
            export = export_plan(plan_from_snapshot(snapshot, omit_reference_images=True), output)
            row["machine_svg_sha256"] = sha256((export / "page-001.svg").read_bytes()).hexdigest()
        return row
    finally:
        canvas.stop_rendering()
        view.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("font", type=Path)
    parser.add_argument("text", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="inkstruct-preview-bench-") as folder:
        work = Path(folder)
        settings = QtCore.QSettings
        settings.setDefaultFormat(settings.Format.IniFormat)
        settings.setPath(settings.Format.IniFormat, settings.Scope.UserScope, folder)
        app = QtWidgets.QApplication([])
        preferences = GlobalDefaultsStore.make_settings()
        preferences.setValue("preview_backend_v1", "cpu")
        preferences.sync()
        snapshot = mixed_snapshot(args.font, args.text, work)
        rows = []
        for trial in range(args.repeats):
            for accelerate in ((False, True) if trial % 2 == 0 else (True, False)):
                row = measure(app, snapshot, accelerate,
                              work / f"svg-{accelerate}" if trial == 0 else None)
                rows.append(row)
        hashes = {row["machine_svg_sha256"] for row in rows[:2]}
        if len(hashes) != 1:
            raise AssertionError("SVG paths or pen order changed")
        fields = ("first_paint_ms", "prepare_svg_with_sampling_ms", "raster_ms")
        results = {
            "qt": QtCore.qVersion(),
            "backend": "cpu",
            "page_points": sum(len(op.points) for p in snapshot.pages for op in (*p.paint_ops, *p.preview_ops)),
            "screen_spec": rows[0]["screen_spec"],
            "machine_svg_sha256": hashes.pop(),
            "medians_ms": {
                mode: {field: round(median(row[field] for row in rows if row["accelerated"] == value), 2)
                       for field in fields}
                for mode, value in (("original", False), ("accelerated", True))
            },
            "rows": rows,
        }
        report = json.dumps(results, ensure_ascii=False, indent=2)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(report)


if __name__ == "__main__":
    main()
