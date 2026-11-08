"""Time the actual Qt import handler using a fresh, isolated library directory."""

import argparse
import hashlib
import itertools
import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from inkstruct.fonts import APP_VERSION, core, ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = args.font.resolve()
    app = QtWidgets.QApplication([])
    events, totals, checks, verification = [], defaultdict(lambda: [0, 0.0]), [], []

    def instrument(owner, name, label):
        original = getattr(owner, name)

        def measured(*a, **kw):
            start, cpu = time.perf_counter(), time.thread_time()
            try:
                value = original(*a, **kw)
                if label == "verify":
                    verification.append(value)
                return value
            finally:
                wall, used = time.perf_counter() - start, time.thread_time() - cpu
                if label in {"constructor", "verify"}:
                    events.append(
                        {
                            "stage": label,
                            "seconds": wall,
                            "thread_cpu_seconds": used,
                            "main_thread": threading.current_thread() is threading.main_thread(),
                        }
                    )
                else:
                    totals[label][0] += 1
                    totals[label][1] += wall

        setattr(owner, name, measured)

    for owner, name, label in [
        (core.FontPackage, "__init__", "constructor"),
        (core.FontPackage, "verify", "verify"),
        (core.FontPackage, "_checked", "member_read_and_hash"),
        (core, "trajectory_hashes", "trajectory_hashes"),
        (core, "decode", "decode"),
        (core, "resolved_candidate", "resolved_candidate"),
    ]:
        instrument(owner, name, label)
    w = ui.FontLibrary(out / "fonts")
    results = []
    original_completed = w.completed

    def completed(result):
        results.append(result)
        original_completed(result)

    w.completed = completed
    if args.workers is not None:
        original_import = ui.import_font
        ui.import_font = lambda source, root, progress: original_import(
            source, root, progress, workers=args.workers
        )
    w.resize(900, 600)
    w.show()
    app.processEvents()
    progress = []
    original_progress = w.set_progress
    origin = time.perf_counter()

    def updated(message):
        progress.append({"seconds": time.perf_counter() - origin, "message": message})
        original_progress(message)

    w.set_progress = updated
    QtWidgets.QFileDialog.getOpenFileName = lambda *a, **k: (str(source), "")
    QtWidgets.QMessageBox.warning = lambda *a: checks.append(str(a[-1]))
    ticks = []
    timer = QtCore.QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start()
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    w.import_font()
    while w.job is not None:
        app.processEvents()
        if time.perf_counter() - wall_start > 900:
            raise TimeoutError(w.progress.text())
        time.sleep(0.002)
    app.processEvents()
    wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
    runtime = results[0].get("verification_runtime", {})
    child_cpu = runtime.get("worker_cpu_seconds", 0)
    if not verification:
        verification.append(results[0]["verification"])
    timer.stop()
    assert not checks, checks
    assert w.list.count() == 1, w.progress.text()
    destination = w.selected()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(source) == sha(destination)
    report = {
        "app_version": APP_VERSION,
        "source": str(source),
        "bytes": source.stat().st_size,
        "logical_cpus": os.cpu_count(),
        "wall_seconds": wall,
        "process_cpu_seconds": cpu,
        "worker_cpu_seconds": child_cpu,
        "verification_runtime": runtime,
        "one_core_utilization_percent": (cpu + child_cpu) / wall * 100,
        "total_cpu_utilization_percent": (cpu + child_cpu) / wall / os.cpu_count() * 100,
        "max_ui_tick_gap_seconds": max([b - a for a, b in itertools.pairwise(ticks)] or [0]),
        "stages": events,
        "inclusive_function_totals": dict(totals),
        "verification": verification,
        "progress": progress,
        "imported_font_sha256": sha(destination),
        "output": str(destination),
    }
    (out / "measurement.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    w.close()
    QtCore.QThreadPool.globalInstance().waitForDone()


if __name__ == "__main__":
    main()
