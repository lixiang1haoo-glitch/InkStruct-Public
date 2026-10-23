"""Measure control dispatch to Qt paint completion, separately from compositor presentation."""

import argparse
import json
import math
import platform
import statistics
import time
from hashlib import sha256
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from inkstruct.editor.app import PageCanvas
from inkstruct.editor.mixed import MixedWindow
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 3:
        parser.error("Choose a new output directory and at least three observations")
    args.output.mkdir(parents=True)
    source_files = [Path(__file__), Path("src/inkstruct/cache.py")]
    for name in ("editor", "document", "layout", "assets", "math", "scene", "renderers", "plotter"):
        source_files.extend(sorted(Path(f"src/inkstruct/{name}").rglob("*.py")))
    source_hashes = {str(p): sha256(p.read_bytes()).hexdigest() for p in source_files}
    project_hash = sha256(args.project.read_bytes()).hexdigest()
    app = QtWidgets.QApplication([])
    # Match the current editor entry point; its source hash is part of this record.
    app.setStyle("Fusion")
    palette = app.palette()
    for role, color in (
        (QtGui.QPalette.ColorRole.Window, "#f6f8fa"),
        (QtGui.QPalette.ColorRole.Base, "white"),
        (QtGui.QPalette.ColorRole.Text, "#1f2937"),
        (QtGui.QPalette.ColorRole.WindowText, "#1f2937"),
    ):
        palette.setColor(role, QtGui.QColor(color))
    app.setPalette(palette)
    pending = {}
    original_paint = PageCanvas.paintEvent

    def paint(canvas, event):
        start = time.perf_counter()
        original_paint(canvas, event)
        end = time.perf_counter()
        if (
            pending
            and "paint_end" not in pending
            and canvas.page_index == pending["page"]
            and canvas.scale == pending["scale"]
        ):
            pending.update(paint_start=start, paint_end=end, visible=canvas.isVisible())

    class Window(MixedWindow):
        def write_recovery(self):
            pass

    def wait(predicate, start=None):
        loop = QtCore.QEventLoop()
        poll = QtCore.QTimer()
        poll.setInterval(1)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QtCore.QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        if start is not None:
            QtCore.QTimer.singleShot(0, start)
        poll.start()
        deadline.start(30000)
        loop.exec()
        poll.stop()
        deadline.stop()
        if not predicate():
            raise RuntimeError("Timed out awaiting visible Qt paint")

    PageCanvas.paintEvent = paint
    window = Window()
    window.resize(1000, 700)
    window.show()
    window.raise_()
    window.activateWindow()
    samples = []
    try:
        window.load_project_path(args.project)
        wait(
            lambda: (
                window.snapshot
                and window.canvas.isEnabled()
                and not window.worker
                and not window.timer.isActive()
                and window.windowHandle().isExposed()
            )
        )
        snapshot, revision, raw = window.snapshot, window.revision, window.buffer.raw
        assert [window.width(), window.height()] == [1000, 700]
        selections = window.resolver.selection_records()
        if len(snapshot.pages) < 3:
            raise ValueError("Use a project with at least three pages")

        def geometry():
            return [
                sha256(page_svg(page).encode()).hexdigest()
                for page in plan_from_snapshot(window.snapshot).pages
            ]

        original_geometry = geometry()

        def measure(kind, page, zoom):
            pending.clear()
            cache_before = window.canvas.preview_cache.statistics()

            def action():
                pending.update(page=page - 1, scale=window.zoom.itemData(zoom))
                pending["start"] = time.perf_counter()
                window.page_picker.setValue(page)
                window.zoom.setCurrentIndex(zoom)
                pending["dispatch_end"] = time.perf_counter()

            wait(lambda: "paint_end" in pending, start=action)
            assert pending["visible"] and window.windowHandle().isExposed()
            assert window.snapshot is snapshot and window.revision == revision
            assert window.buffer.raw == raw and window.resolver.selection_records() == selections
            assert not window.worker and not window.timer.isActive()
            cache_after = window.canvas.preview_cache.statistics()
            record = {
                "kind": kind,
                "page": page,
                "zoom": window.zoom.currentText(),
                "dispatch_ms": (pending["dispatch_end"] - pending["start"]) * 1000,
                "paint_ms": (pending["paint_end"] - pending["paint_start"]) * 1000,
                "dispatch_to_paint_end_ms": (pending["paint_end"] - pending["start"]) * 1000,
                "cache_hits": cache_after["hits"] - cache_before["hits"],
                "cache_misses": cache_after["misses"] - cache_before["misses"],
            }
            pending.clear()
            if kind != "warmup":
                samples.append(record)
            return record

        # Each of these pages is visited for the first time; do not label them warm hits.
        initial_zoom = window.zoom.currentIndex()
        for page in range(2, len(snapshot.pages) + 1):
            record = measure("cold_page", page, initial_zoom)
            assert record["cache_misses"] == 1 and record["cache_hits"] == 0
        measure("warmup", 1, initial_zoom)
        measure("warmup", 2, initial_zoom)
        for index in range(args.repeats):
            record = measure("warm_page", 1 + index % 2, initial_zoom)
            assert record["cache_hits"] == 1 and record["cache_misses"] == 0
        for _ in range(args.repeats):
            record = measure(
                "zoom",
                window.page_picker.value(),
                (window.zoom.currentIndex() + 1) % window.zoom.count(),
            )
            assert record["cache_hits"] == record["cache_misses"] == 0
        assert geometry() == original_geometry
        assert sha256(args.project.read_bytes()).hexdigest() == project_hash
        assert all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in source_hashes.items())
        if not window.grab().save(str(args.output / "widget-capture.png")):
            raise RuntimeError("Could not save the final widget capture")
        summary = {}
        for kind in ("cold_page", "warm_page", "zoom"):
            rows = [row for row in samples if row["kind"] == kind]
            summary[kind] = {"count": len(rows)}
            for key in ("dispatch_ms", "paint_ms", "dispatch_to_paint_end_ms"):
                values = sorted(row[key] for row in rows)
                summary[kind][key] = {
                    "p50": statistics.median(values),
                    "p95_nearest_rank": values[math.ceil(len(values) * 0.95) - 1],
                    "max": max(values),
                }
        report = {
            "scope": "Controls changed in an exposed MixedWindow after layout completes; "
            "first matching PageCanvas.paintEvent return is the endpoint. Includes synchronous "
            "page serialization/cache lookup, Qt scheduling and paint, excludes OS input dispatch, "
            "compositor presentation, physical display latency and concurrent document rebuilds. "
            "Widget capture is not an OS screenshot. No hardware-visible-frame claim.",
            "platform": platform.platform(),
            "qt": QtCore.qVersion(),
            "qt_platform": app.platformName(),
            "qt_widget_style": app.style().objectName(),
            "device_pixel_ratio": window.devicePixelRatioF(),
            "window_size": [window.width(), window.height()],
            "project": str(args.project.resolve()),
            "project_sha256": project_hash,
            "source_hashes": source_hashes,
            "pages": len(snapshot.pages),
            "samples": samples,
            "summary": summary,
            "snapshot_identity_revision_source_selections_preserved": True,
            "unoptimized_machine_svg_hashes_before_and_after": original_geometry,
        }
        (args.output / "timing.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
    finally:
        pending.clear()
        window.timer.stop()
        if window.cancelled:
            window.cancelled.set()
        window.pool.waitForDone()
        window.dirty = False
        window.close()
        PageCanvas.paintEvent = original_paint


if __name__ == "__main__":
    main()
