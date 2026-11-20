"""Exercise the paper stops, physical corner and actual writing worker with a simulated N1."""

import os
from pathlib import Path
from subprocess import run
import sys
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch


def test_recover_paper_corner_and_write_against_same_stops(tmp_path):
    result = run(
        [sys.executable, str(Path(__file__).resolve()), str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen"),
             "PYTHONUTF8": "1"},
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def exercise(workspace):
    from dataclasses import replace

    from PySide6 import QtCore, QtWidgets
    from inkstruct.document.flow_template import FlowTemplate
    from inkstruct.editor.machine_alignment import AlignmentDialog
    from inkstruct.editor.machine_devices import DeviceDialog
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.plotter.physical import WorkArea
    from inkstruct.plotter.profiles import DeviceProfile, PageAlignment
    from inkstruct.plotter.qt_connection import N1Worker
    from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp
    from test_plotter_machine import SimulatedGrbl

    app = QtWidgets.QApplication([])
    settings = QtCore.QSettings
    settings.setDefaultFormat(settings.Format.IniFormat)
    settings.setPath(settings.Format.IniFormat, settings.Scope.UserScope, str(workspace))
    port = SimpleNamespace(portName=lambda: "COM-test", serialNumber=lambda: "")
    template = FlowTemplate(width_mm=210, height_mm=297, plotter_alignment=PageAlignment((5, 5)))
    pages = tuple(Page(i, (), (PaintOp(f"stroke-{i}", ((6., 7.), (8., 9.)), .3),))
                  for i in range(2))
    snapshot = LayoutSnapshot("snapshot", "key", "doc", 0, template.page, pages, (), "resource", "test")

    def open_panel(transport):
        def reopen(_port):
            transport.closed = False
            return transport
        worker = lambda parent: N1Worker(parent, serial_factory=reopen)
        panel = MachinePanel(None, worker_factory=worker, ports=lambda: [port])
        panel.set_workspace(workspace)
        panel.confirm = lambda *_: True
        panel.show()
        panel.set_document(snapshot, 0, True, template)
        return panel

    def wait(panel):
        deadline = monotonic() + 8
        while panel.busy is not None and monotonic() < deadline:
            app.processEvents()
            sleep(.003)
        assert panel.busy is None, panel.report.text()
        app.processEvents()

    def click(panel, button):
        assert button.isEnabled(), f"{button.text()} unavailable: {panel.report.text()}"
        button.click()
        wait(panel)

    def move(panel, dialog, direction, distance):
        dialog.nudge.step.setCurrentIndex(dialog.nudge.step.findData(distance))
        click(panel, dialog.nudge.buttons[direction])

    def record_corner(panel, dialog):
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("A4 竖向左上角", True)):
            click(panel, dialog.datum_register)

    def capture_page(dialog):
        assert dialog.fixture.isChecked()
        dialog.setup.setText("A4 竖向书写摆放")
        click(dialog.panel, dialog.record_a)
        dialog.save.click()
        assert dialog.result() and dialog.position == (40., 38.), dialog.status.text()
        return dialog.result()

    serial = SimulatedGrbl()
    serial.position[:] = [35., 30., 0.]
    panel = open_panel(serial)
    try:
        panel.save_profile(DeviceProfile.create("实验室 N1", "COM-test"))
        setup = DeviceDialog(panel)
        click(panel, setup.link)
        record_corner(panel, setup)
        assert panel.frame == (35., 30.)
        assert not any(line.startswith(b"G1 ") for line in serial.commands)
        setup.use_range.setChecked(True)
        for control, value in zip(setup.bounds, (25, 10, 70, 90), strict=True):
            control.setValue(value)
        click(panel, setup.save_button)
        assert panel.confirmed_area == WorkArea(25, 10, 70, 90)
        move(panel, setup, (1, 0), 5)
        for distance in (5, 2, 1):
            move(panel, setup, (0, 1), distance)
        assert serial.position == [40., 38., 0.]
        setup.close()
        with patch.object(AlignmentDialog, "exec", capture_page):
            click(panel, panel.align_button)
        assert panel.job.strokes[0].points == ((41., 40.), (43., 42.))
        assert panel.write_button.isEnabled()
        from inkstruct.document.flow_template import PageLayout
        layouts = tuple(PageLayout(str(i), f"版式 {i}", source_page=i, plotter_alignment=PageAlignment((5,5)))
                        for i in range(1,5))
        cycle = FlowTemplate(kind="custom", layouts=layouts, loop_pages=("1","2","3","4"))
        nine = replace(snapshot, snapshot_id="nine", pages=tuple(replace(pages[0], index=i) for i in range(9)))
        panel.set_document(nine, 0, True, cycle)
        with patch.object(AlignmentDialog, "exec", capture_page):
            click(panel, panel.align_button)
        count = len(serial.commands)
        for i in (4,3,8):
            if i == 4:
                panel.page_list.setCurrentRow(i)
            else:
                panel.follow_page(i)
            assert panel.progress.isHidden()
            if i == 3:
                assert panel.registration is None and not panel.write_button.isEnabled()
                assert "第 4 页未对位" == panel.alignment_status.text()
                assert "已对位" not in panel.report.text()
            else:
                assert panel.job.index == i and panel.registration.origin == (40.,38.)
                assert all(text in panel.alignment_status.text() for text in
                           (f"第 {i+1} 页已沿用", "PDF 第 1 页", "本稿第 1 页登记"))
        assert len(serial.commands) == count
        def ordinary_alignment(dialog):
            dialog.fixture.setChecked(False)
            click(panel, dialog.record_a)
            dialog.save.click()
            return dialog.result()
        with patch.object(AlignmentDialog, "exec", ordinary_alignment):
            click(panel, panel.align_button)
        assert panel.job is not None and panel.inherited_placement is None
        panel.follow_page(4)
        assert panel.job is None and "未对位" in panel.alignment_status.text()
        panel.set_document(snapshot, 0, True, template)
        first_datum = panel.profile.datum.id
    finally:
        panel.shutdown()
        panel.close()

    # The motor was powered off and is now physically at the registered corner.
    # The new controller assigns (0,0) here; its reported WCO is unchanged.
    serial = SimulatedGrbl()
    panel = open_panel(serial)
    try:
        setup = DeviceDialog(panel)
        click(panel, setup.link)
        assert panel.frame is None and panel.confirmed_area is None and panel.job is None
        assert not panel.write_button.isEnabled()
        questions = []
        def decline(_title, question):
            questions.append(question)
            return False
        panel.confirm = decline
        count = len(serial.commands)
        click(panel, setup.datum_recover)
        assert "实验室 N1" in questions[-1] and "COM-test" in questions[-1]
        assert panel.frame is None and len(serial.commands) == count
        panel.confirm = lambda *_: True
        click(panel, setup.datum_recover)
        assert panel.frame == (0., 0.) and panel.profile.datum.id == first_datum
        assert panel.confirmed_area == WorkArea(-10, -20, 35, 60)
        assert panel.setup == "A4 竖向书写摆放"
        assert panel.job is not None and panel.inherited_placement is not None
        assert "本稿第 1 页登记" in panel.alignment_status.text()
        assert not any(line.startswith(b"G1 ") for line in serial.commands)
        setup.close()

        panel.scope.setCurrentIndex(panel.scope.findData("all"))
        assert panel.inherited_placement is not None
        assert panel.registration.origin == (5., 8.)
        assert panel.job.strokes[0].points == ((6., 10.), (8., 12.))
        assert not any(line.startswith(b"G1 ") for line in serial.commands)
        click(panel, panel.write_button)
        assert panel.waiting_for_paper and panel.completed_pages == {0}
        assert panel.registration is not None and panel.job.index == 1
        assert panel.progress.isHidden()
        assert b"G1 Z-1.6 F5000\n" in serial.commands
        replacement = replace(template, name="另外的纸张摆放")
        panel.set_document(replace(snapshot, snapshot_id="other-doc"), 0, True, replacement)
        assert panel.snapshot is snapshot and panel.batch_active
        count = len(serial.commands)
        assert "确认换纸" in panel.write_button.text()
        click(panel, panel.write_button)
        assert len(serial.commands) == count
        assert panel.job.index == 1 and panel.registration.origin == (5., 8.)
        panel.set_document(snapshot, 0, True, template)
        click(panel, panel.write_button)
        assert panel.completed_pages == {0, 1} and not panel.batch_active

        setup = DeviceDialog(panel)
        assert serial.position[:2] == [8., 12.]
        click(panel, setup.datum_alternate)
        click(panel, setup.link)
        serial.position[:] = [0., 0., 0.]  # Reboot at the visible alternate marker.
        click(panel, setup.link)
        assert panel.frame is None and panel.confirmed_area is None
        click(panel, setup.datum_use_alternate)
        assert panel.frame == (-8., -12.) and panel.confirmed_area == WorkArea(-18, -32, 27, 48)
        setup.close()
        assert panel.inherited_placement is not None
        assert panel.registration.origin == (-3., -4.)

        outside = Page(0, (), (PaintOp("outside", ((100., 100.), (101., 101.)), .3),))
        panel.set_document(replace(snapshot, snapshot_id="outside", pages=(outside,)), 0, True, template)
        count = len(serial.commands)
        assert panel.inherited_placement is not None
        if panel.write_button.isEnabled():
            click(panel, panel.write_button)
            assert "超出" in panel.report.text()
        assert not any(line.startswith(b"G1 ") for line in serial.commands[count:])

        # Replacing a physical corner invalidates even a placement with the old label.
        setup = DeviceDialog(panel)
        record_corner(panel, setup)
        assert panel.profile.datum.id != first_datum
        assert panel.confirmed_area is None and panel.registration is None
        assert not panel.reuse_alignment_button.isEnabled() and not panel.write_button.isEnabled()
        assert setup.use_range.isChecked()
        for control, value in zip(setup.bounds, (-5, -5, 10, 10), strict=True):
            control.setValue(value)
        click(panel, setup.range_confirm)
        assert setup.use_range.isChecked() and panel.confirmed_area == WorkArea(-5, -5, 10, 10)
        setup.axes[0].setChecked(True)
        click(panel, setup.save_button)
        assert panel.frame is None and panel.confirmed_area is None and setup.use_range.isChecked()
        assert not panel.reuse_alignment_button.isEnabled() and not panel.write_button.isEnabled()
        setup.close()
    finally:
        panel.shutdown()
        panel.close()


if __name__ == "__main__":
    exercise(Path(sys.argv[1]))
