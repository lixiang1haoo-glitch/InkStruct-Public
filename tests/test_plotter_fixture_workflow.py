"""Exercise per-layout paper marks and docking recovery with a simulated N1."""

import os
from pathlib import Path
from subprocess import run
import sys
from time import monotonic, sleep
from types import SimpleNamespace


def test_independent_printed_layouts_and_reconnect_at_same_stops(tmp_path):
    result = run(
        [sys.executable, str(Path(__file__).resolve()), str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen"),
             "PYTHONUTF8": "1"},
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def exercise(workspace):
    from dataclasses import replace
    from PySide6 import QtWidgets
    from inkstruct.document.flow_template import FlowTemplate, PageLayout
    from inkstruct.editor.machine_alignment import AlignmentDialog
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.plotter.profiles import DeviceProfile, DeviceDatum
    from inkstruct.plotter.qt_connection import N1Worker
    from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp
    from test_plotter_machine import SimulatedGrbl

    app = QtWidgets.QApplication([])
    profile = DeviceProfile.create("N1", "COM-test", "sim")
    profile = replace(profile, datum=replace(DeviceDatum.create(profile, "停靠点"), boot_mode="zero"))
    layouts = tuple(PageLayout(str(i), f"PDF {i}", source_page=i) for i in range(1, 5))
    template = FlowTemplate(kind="custom", layouts=layouts, loop_pages=("1", "2", "3", "4"))
    pages = tuple(Page(i, (), (PaintOp(f"p{i}", ((10., 21.), (12., 22.)), .3),)) for i in range(9))
    snapshot = LayoutSnapshot("s", "k", "doc", 0, template.page, pages, (), "r", "t")
    mock = SimulatedGrbl()
    def opened(_):
        mock.closed = False
        return mock
    p = MachinePanel(None, worker_factory=lambda w: N1Worker(w, serial_factory=opened),
                     ports=lambda: [SimpleNamespace(portName=lambda: profile.port, serialNumber=lambda: "sim")])
    p.set_workspace(workspace)
    p.save_profile(profile)
    p.show()
    p.set_document(snapshot, 6, True, template)
    p.confirm = lambda *_: True
    def wait():
        end = monotonic() + 8
        while monotonic() < end:
            app.processEvents()
            if not p.busy:
                app.processEvents()
                if not p.busy:
                    return
            sleep(.003)
        raise AssertionError(p.report.text())
    def measure(index, mark, target):
        p.follow_page(index)
        delta = tuple(a - b for a, b in zip(target, p.device.position))
        p.submit("jog", delta, p.confirmed_area, p.profile.feed)
        wait()
        key, size, _, title = p.sheet_context()
        dialog = AlignmentDialog(p, key, size, None, title)
        dialog.show()
        dialog.pick(*mark)
        dialog.record.click()
        wait()
        assert dialog.result() == QtWidgets.QDialog.Accepted
        assert p.job.registration.origin == target
        dialog.deleteLater()
    try:
        p.toggle_connection()
        wait()
        assert p.datum_located
        measure(6, (4.316, 16.524), (11.640, .910))
        p.follow_page(5)
        assert p.job is None and "待对位" in p.alignment_status.text()
        measure(5, (4.330, 16.588), (3.650, .970))
        p.follow_page(6)
        assert p.job.registration.origin == (11.640, .910)
        measure(6, (4.316, 16.524), (12.5, 1.5))
        for index in (5, 1):
            p.follow_page(index)
            assert p.job.registration.origin == (3.650, .970)
            assert p.job.registration.place((4.330, 16.588)) == (3.650, .970)
        p.follow_page(6)
        key, size, _, title = p.sheet_context()
        mark = p.fixture_placement.alignment
        before = p.store.sheet(profile, key)
        temp = AlignmentDialog(p, key, size, mark, title, temporary=True)
        temp.show()
        temp.reject()
        assert p.store.sheet(profile, key) == before
        p.toggle_connection()
        wait()
        p.toggle_connection()
        wait()
        assert p.datum_located and p.job.registration.origin == (12.5, 1.5)
        # Moving a printed frame invalidates this geometry, but renaming does not.
        p.set_document(snapshot, 6, True, replace(template, name="报告"))
        assert p.job.registration.origin == (12.5, 1.5)
        p.set_document(snapshot, 6, True, replace(template, offset_x_mm=1))
        assert not p.job and not p.write_button.isEnabled()
    finally:
        p.shutdown()
        p.close()


if __name__ == "__main__":
    exercise(Path(sys.argv[1]))
