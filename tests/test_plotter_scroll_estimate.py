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
    finally:
        release.set()
        panel.shutdown()
        panel.close()


if __name__ == "__main__":
    exercise(Path(sys.argv[1]))
