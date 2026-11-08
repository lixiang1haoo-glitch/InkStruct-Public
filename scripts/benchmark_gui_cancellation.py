"""Measure edit-triggered cancellation through the real Qt worker and publish slot."""

import argparse
import json
import math
import platform
import statistics
import threading
import time
from hashlib import sha256
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.layout.inline import LayoutCancelled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 3:
        parser.error("Use a new output file and at least three observations")
    original_hash = sha256(args.project.read_bytes()).hexdigest()
    app = QtWidgets.QApplication([])
    traces = {}
    original_build = mixed.build_markdown

    class TimedEvent(threading.Event):
        def __init__(self, trace):
            super().__init__()
            self.trace = trace

        def set(self):
            if not self.is_set():
                self.trace["event_set"] = time.perf_counter()
            super().set()

    def observed_build(**kw):
        trace = traces.get(kw["revision"])
        if trace is not None:
            trace["worker_start"] = time.perf_counter()
            trace["worker_thread"] = threading.get_ident()
        try:
            return original_build(**kw)
        except LayoutCancelled:
            if trace is not None:
                trace["worker_cancelled"] = time.perf_counter()
            raise
        finally:
            if trace is not None:
                trace["worker_end"] = time.perf_counter()

    class Window(mixed.MixedWindow):
        def source_contents_changed(self, *args):
            trace = getattr(self, "edit_trace", None)
            start = time.perf_counter()
            super().source_contents_changed(*args)
            if trace is not None:
                trace["source_transaction_ms"] = (time.perf_counter() - start) * 1000

        def write_recovery(self):
            # This benchmark edits only a transient fixture; never write user recovery data.
            pass

        def build_arguments(self):
            kw = super().build_arguments()
            if self.revision in traces:
                kw["cancelled"] = TimedEvent(traces[self.revision])
            return kw

        def publish(self, result):
            trace = traces.get(result["revision"])
            if trace is not None:
                trace["gui_received"] = time.perf_counter()
                trace["gui_thread"] = threading.get_ident()
                trace["result_has_snapshot"] = "snapshot" in result
                trace["result_error"] = result.get("error")
                previous = self.snapshot
            super().publish(result)
            if trace is not None:
                trace["old_snapshot_retained"] = self.snapshot is previous

    def wait_until(predicate, *, start=None):
        loop = QtCore.QEventLoop()
        poll = QtCore.QTimer()
        poll.setInterval(1)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QtCore.QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        if start is not None:
            # Start only after every measurement QObject/connection is ready.
            # Constructing Qt callbacks while a Python worker is already running
            # introduces GIL handoffs unrelated to an existing editor event loop.
            QtCore.QTimer.singleShot(0, start)
        poll.start()
        deadline.start(30000)
        loop.exec()
        poll.stop()
        deadline.stop()
        if not predicate():
            raise RuntimeError("Timed out waiting for the real editor")

    window = Window()
    errors = []
    window.message_error = lambda error: errors.append(str(error))
    window.recovery_timer.stop()
    window.show()
    mixed.build_markdown = observed_build
    observations = []
    try:
        window.load_project_path(args.project)

        def ready():
            return (
                window.snapshot is not None
                and window.canvas.isEnabled()
                and not window.worker
                and not window.timer.isActive()
            )

        wait_until(ready)
        original_source = window.buffer.raw
        pages = len(window.snapshot.pages)
        for _ in range(args.repeats):
            # Cold rebuild ensures this probes active computation, not a full-cache hit.
            window.build_cache = MarkdownBuildCache()
            window.schedule_layout()
            window.timer.stop()
            trace = {}
            traces[window.revision] = trace

            def edit(trace=trace):
                trace["edit_start"] = time.perf_counter()
                trace["edit_thread"] = threading.get_ident()
                window.edit_trace = trace
                cursor = window.editor.textCursor()
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
                window.editor.setTextCursor(cursor)
                trace["cursor_ready"] = time.perf_counter()
                window.editor.insertPlainText("1")
                trace["edit_end"] = time.perf_counter()
                window.edit_trace = None

            edit_timer = QtCore.QTimer(window)
            edit_timer.setSingleShot(True)
            edit_timer.timeout.connect(edit)

            def launch(trace=trace, edit_timer=edit_timer):
                trace["launch_start"] = time.perf_counter()
                window.launch_layout()
                trace["launch_return"] = time.perf_counter()
                trace["timer_armed"] = time.perf_counter()
                edit_timer.start(10)
                trace["timer_registered"] = time.perf_counter()

            wait_until(
                lambda trace=trace: "gui_received" in trace and "edit_end" in trace,
                start=launch,
            )
            edit_timer.deleteLater()
            launch_time = trace["launch_start"]
            if "worker_cancelled" not in trace:
                raise RuntimeError(f"Work completed before cancellation; not a sample: {trace}")
            assert not trace["result_has_snapshot"] and not trace["result_error"]
            assert trace["old_snapshot_retained"]
            assert trace["worker_thread"] != trace["gui_thread"]
            assert trace["edit_thread"] == trace["gui_thread"] == threading.get_ident()
            assert trace["worker_start"] < trace["event_set"] <= trace["worker_cancelled"]
            observations.append(
                {
                    "synchronous_launch_ms": (trace["launch_return"] - launch_time) * 1000,
                    "timer_registration_ms": (trace["timer_registered"] - trace["timer_armed"])
                    * 1000,
                    "armed_timer_to_edit_ms": (trace["edit_start"] - trace["timer_armed"]) * 1000,
                    "cursor_setup_ms": (trace["cursor_ready"] - trace["edit_start"]) * 1000,
                    "source_transaction_ms": trace["source_transaction_ms"],
                    "insert_call_ms": (trace["edit_end"] - trace["cursor_ready"]) * 1000,
                    "edit_after_launch_ms": (trace["edit_start"] - launch_time) * 1000,
                    "edit_to_event_set_ms": (trace["event_set"] - trace["edit_start"]) * 1000,
                    "event_to_worker_cancel_ms": (trace["worker_cancelled"] - trace["event_set"])
                    * 1000,
                    "event_to_gui_receipt_ms": (trace["gui_received"] - trace["event_set"]) * 1000,
                    "edit_to_gui_receipt_ms": (trace["gui_received"] - trace["edit_start"]) * 1000,
                    "stale_snapshot_rejected": True,
                    "distinct_worker_and_gui_threads": True,
                }
            )
            wait_until(ready)
            assert window.snapshot.revision == window.revision
            assert window.buffer.raw == original_source + "1"
            kw = window.build_arguments()
            kw["cache"] = None
            fresh = original_build(**kw)
            assert fresh["snapshot"] == window.snapshot
            assert fresh["resolver"].selection_records() == window.resolver.selection_records()
            window.editor.undo()
            wait_until(ready)
            assert window.buffer.raw == original_source
            assert not errors, errors
            print(json.dumps(observations[-1]), flush=True)
        assert sha256(args.project.read_bytes()).hexdigest() == original_hash
        summary = {}
        for key in observations[0]:
            if key.endswith("_ms"):
                values = sorted(row[key] for row in observations)
                summary[key] = {
                    "p50": statistics.median(values),
                    "p95_nearest_rank": values[math.ceil(0.95 * len(values)) - 1],
                    "max": max(values),
                }
        report = {
            "scope": "Actual MixedWindow edit, QThreadPool worker, queued publish slot. "
            "10 ms timer requests an edit during a cold rebuild with loaded embedded assets. "
            "No artificial worker blocking. Measures GUI receipt, not screen presentation. "
            "Replacement snapshot and selections equal uncached build; undo restores source.",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "qt": QtCore.qVersion(),
            "qt_platform": app.platformName(),
            "project": str(args.project.resolve()),
            "project_sha256": original_hash,
            "pages": pages,
            "source_hashes": {
                str(path): sha256(path.read_bytes()).hexdigest()
                for path in [Path(__file__), *sorted(Path("src/inkstruct").rglob("*.py"))]
            },
            "samples": observations,
            "summary": summary,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        window.timer.stop()
        if window.cancelled:
            window.cancelled.set()
        window.pool.waitForDone()
        mixed.build_markdown = original_build
        window.dirty = False
        window.close()


if __name__ == "__main__":
    main()
