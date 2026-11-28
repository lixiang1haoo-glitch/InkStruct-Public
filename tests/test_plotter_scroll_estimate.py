"""Exercise page-follow, stale estimates and cache invalidation through the Qt sidebar."""
import os
from pathlib import Path
import subprocess
import sys


def test_scroll_estimates(tmp_path):
    result = subprocess.run([sys.executable, __file__, str(tmp_path)], capture_output=True,
                            text=True, timeout=45, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    assert result.returncode == 0, result.stdout + result.stderr


def exercise(folder):
    from dataclasses import replace
    from threading import Event, get_ident
    from time import monotonic, sleep
    from unittest.mock import patch

    from PySide6 import QtWidgets
    from inkstruct.document.schema import PageProfile
    from inkstruct.editor import machine_panel
    from inkstruct.plotter.physical import PaperRegistration, position_page
    from inkstruct.plotter.profiles import DeviceProfile
    from inkstruct.plotter.write_session import estimate_seconds
    from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp

    app = QtWidgets.QApplication([])
    panel = machine_panel.MachinePanel(None, ports=lambda: [])
    panel.set_workspace(folder)
    panel.save_profile(DeviceProfile("perf", "test", "test"))
    panel.show()
    gui = get_ident()
    started, release = Event(), Event()
    calls = []
    original = machine_panel.measure_page

    def measure(raw, *args):
        assert get_ident() != gui
        calls.append(raw.index)
        if raw.index == 0 and not started.is_set():
            started.set()
            assert release.wait(5)
        return original(raw, *args)

    def wait(check):
        end = monotonic() + 5
        while not check() and monotonic() < end:
            app.processEvents()
            sleep(.002)
        assert check(), panel.estimate_label.text()

    def displayed():
        return "分" in panel.estimate_label.text()

    def check_time():
        positioned = position_page(panel.paper_page, PaperRegistration((0, 0)))
        assert abs(panel.base_estimate - estimate_seconds(positioned.strokes, panel.profile.feed)) < 1e-8

    pages = tuple(Page(j, (), tuple(PaintOp(str(i), ((2., 2.), (4. + j, 3.)), .25)
                                    for i in range(30 + j))) for j in range(4))
    snapshot = LayoutSnapshot("s", "k", "d", 0, PageProfile(70, 60, 5), pages, (), "r", "t")
    try:
        with patch.object(machine_panel, "measure_page", measure):
            panel.set_document(snapshot, 0, True)
            wait(started.is_set)
            panel.follow_page(1)
            panel.follow_page(2)
            panel.follow_page(3)
            assert panel.page_list.currentRow() == 3 and not displayed()
            assert not panel.write_button.isEnabled()
            release.set()
            wait(displayed)
            check_time()
            assert calls == [0, 3]
            panel.change_feed(500)
            check_time()
            assert not panel.preview.paper
            panel.follow_page(1)
            wait(displayed)
            panel.follow_page(3)
            assert displayed() and calls == [0, 3, 1]
            check_time()
            # Same document and page number, new immutable snapshot and different strokes.
            changed = replace(snapshot, pages=(*pages[:3], replace(pages[3], paint_ops=pages[3].paint_ops[:2])))
            panel.set_document(changed, 3, True)
            wait(displayed)
            check_time()
            assert calls == [0, 3, 1, 3]
            assert "抬笔 2 次" in panel.route_stats.text()

        # Ordinary handwriting now uses the very same source indices and directions as SVG.
        import json
        from inkstruct.plotter.export import ROUTING_VERSION, route_page
        ops = tuple(PaintOp(str(i), ((x, 3.), (x-1, 3.)), .25)
                    for i, x in enumerate((26., 4., 24., 6.)))
        snap = replace(snapshot, pages=(replace(pages[0], paint_ops=ops),))
        panel.set_document(snap, 0, True)
        expected = route_page(panel.raw_page, optimize=True).page
        assert panel.paper_page.strokes == expected.strokes != panel.raw_page.strokes
        from test_plotter_machine import SimulatedGrbl
        from inkstruct.plotter.grbl import GrblLink, MotionControl
        from inkstruct.plotter.physical import WorkArea

        def dispatched_xy():
            serial = SimulatedGrbl()
            link = GrblLink(serial)
            link.connect()
            placed = position_page(panel.paper_page, PaperRegistration((0, 0)))
            link.run_page(placed, WorkArea(0, 0, 100, 100), MotionControl(), dry_run=False, feed=900)
            strokes = []
            down = False
            tip = (0., 0.)
            for line in serial.commands:
                if line.startswith(b"G1 Z"):
                    down = float(line.split()[1][1:]) < 0
                    if down:
                        strokes.append([tip])
                elif line.startswith(b"G1 X"):
                    tip = tuple(float(word[1:]) for word in line.split()[1:3])
                    if down:
                        strokes[-1].append(tip)
            return list(map(tuple, strokes))

        assert not panel.original_order.isChecked()
        actual = dispatched_xy()
        assert actual == [stroke.points for stroke in expected.strokes]
        panel.original_order.setChecked(True)
        assert panel.paper_page is panel.raw_page
        assert dispatched_xy() == [stroke.points for stroke in panel.raw_page.strokes]
        source = [stroke.points for stroke in panel.raw_page.strokes]
        assert any(stroke.points[::-1] in source for stroke in expected.strokes)
        assert [frozenset(s.points) for s in expected.strokes] != list(map(frozenset, source))
        panel.original_order.setChecked(False)
        journal = panel.journal
        journal.save(2, True)
        record = json.loads(journal.path.read_bytes())
        assert record.pop("route_version") == ROUTING_VERSION
        journal.path.write_text(json.dumps(record), encoding="utf-8")
        panel.change_page()
        assert panel.paper_page is panel.raw_page and not panel.original_order.isEnabled()
        assert panel.done == 2 and panel.uncertain
        panel.journal.save(3, False)
        assert json.loads(journal.path.read_bytes())["route_version"] != ROUTING_VERSION
        journal.path.unlink()
        panel.change_page()
        assert panel.paper_page.strokes == expected.strokes and panel.original_order.isEnabled()

        # A progress signal can arrive before the worker finishes measuring a dense page.
        from inkstruct.plotter.profiles import PageAlignment
        many = tuple(PaintOp(f"ink-{i}", ((2., 2.), (3. + i % 12, 4.)), .25) for i in range(1539))
        dense = replace(snapshot, pages=(replace(pages[0], paint_ops=many),))
        release.clear()
        started.clear()
        with patch.object(machine_panel, "measure_page", measure):
            panel.set_document(dense, 0, True)
            wait(lambda: panel.paper_page is not None)
            from dataclasses import replace as updated
            from inkstruct.plotter.grbl import Status
            from inkstruct.plotter.profiles import DeviceDatum
            panel.profile = updated(panel.profile, datum=updated(DeviceDatum.create(panel.profile, "停靠点"),
                                                                boot_mode="zero"))
            panel.device = Status("Idle", (4., 3., 0.), (0., 0., 0.), "")
            panel.connection_id, panel.frame = "estimate-test", (0., 0.)
            panel.measure_sheet(panel.sheet_context()[0], PageAlignment((0., 0.)), panel.device)
            release.set()
            wait(lambda: panel.job is not None)
            wait(started.is_set)
            panel.busy = "write"
            panel.run_start = 0
            panel.worker.progress.emit(1486, 1539)
            release.set()
            wait(displayed)
            expected_seconds = estimate_seconds(panel.job.strokes[1486:], panel.profile.feed,
                                                panel.job.strokes[1485].points[-1])
            assert abs(panel.base_estimate - expected_seconds) < 1e-8
            seconds = round(expected_seconds)
            assert panel.estimate_label.text() == f"本页预计剩余 {seconds // 60} 分 {seconds % 60} 秒"
            assert "剩余抬笔 53 次" in panel.route_stats.text()
            assert "剩余空走" in panel.route_stats.text() and not panel.route_stats.isHidden()
            calls_before = len(calls)
            with patch.object(machine_panel, "timing_factor", side_effect=AssertionError("progress read disk")):
                held = panel.estimate_label.text()
                panel.on_phase("paused")
                app.processEvents()
                assert panel.estimate_label.text() == held
                panel.on_phase("running")
                for done in range(1487, 1540):
                    panel.worker.progress.emit(done, 1539)
                assert panel.estimate_label.text() == "本页预计剩余 0 分 0 秒"
                assert len(calls) == calls_before
            panel.busy = None
    finally:
        release.set()
        panel.shutdown()
        panel.close()


if __name__ == "__main__":
    exercise(Path(sys.argv[1]))
