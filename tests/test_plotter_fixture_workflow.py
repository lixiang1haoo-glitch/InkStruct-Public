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
    from inkstruct.editor.machine_alignment import AlignmentDialog, page_context
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
    # Four distinct layouts in a nine-sheet document, using only a continuous USB session.
    from inkstruct.document.flow_template import PageLayout
    layouts = tuple(PageLayout(str(i), f"版式 {i}", source_page=i)
                    for i in range(1,5))
    cycle = FlowTemplate(kind="custom", layouts=layouts, loop_pages=("1","2","3","4"))
    nine = replace(snapshot, snapshot_id="group", pages=tuple(replace(pages[0], index=i) for i in range(9)))
    session = open_panel(serial)
    try:
        session.save_profile(DeviceProfile("group-test","测试机","COM-test"))
        click(session, session.link_button)
        session.set_document(nine, 0, True, cycle)
        def record_one(index, xy):
            session.follow_page(index)
            serial.position[:] = [*xy,0.]
            def record(dialog):
                assert not dialog.fixture.isChecked()
                if index == 0:
                    dialog.a[0].setValue(12.639)
                    dialog.a[1].setValue(61.605)
                click(session, dialog.record_a)
                dialog.save.click()
                assert dialog.result(), dialog.status.text()
                return dialog.result()
            with patch.object(AlignmentDialog, "exec", record):
                click(session, session.align_button)
        record_one(0, (10., 20.))
        from inkstruct.document.template_authoring import parse_template, template_json
        source = cycle.layout(0)
        page_key, size, origin, title = page_context(cycle, layout=source)
        assert origin is None
        editor = AlignmentDialog(session, session, page_key, size, origin, title, source=source, configure=True)
        editor.save.click()
        assert editor.result() and editor.position is None and editor.alignment.a == (12.639, 61.605)
        updated = replace(cycle, layouts=(replace(source, plotter_alignment=editor.alignment), *cycle.layouts[1:]))
        assert parse_template(template_json(updated)).layout(4).plotter_alignment == editor.alignment
        count = len(serial.commands)
        for i in (4, 1, 8, 0):
            session.page_list.setCurrentRow(i)
            if i == 1:
                assert session.registration is None and not session.write_button.isEnabled()
            else:
                assert session.registration and session.registration.origin == (10., 20.), i
                assert session.job.index == i and session.write_button.isEnabled()
                assert "第 1 页实测" in session.alignment_status.text()
        assert len(serial.commands) == count
        for i in range(1, 4):
            record_one(i, (10.+i, 20.+2*i))
        record_one(4, (16.,17.))
        count = len(serial.commands)
        for i in (5,6,7,8):
            session.follow_page(i)
            expected = (10.+i%4,20.+2*(i%4)) if i%4 else (16.,17.)
            assert session.registration.origin == expected
            assert session.job.index == i and session.write_button.isEnabled()
            if i%4:
                assert f"第 {i%4+1} 页实测" in session.alignment_status.text()
        assert len(serial.commands) == count
        record_one(6, (15.,25.))
        session.follow_page(0)
        assert session.registration.origin == (16.,17.)
        session.follow_page(3)
        assert session.registration.origin == (13.,26.)
        click(session, session.link_button)
        click(session, session.link_button)
        session.follow_page(5)
        assert session.registration is None and not session.write_button.isEnabled()

        marks = ((4., 16.), (4.330, 16.588), (4.316, 16.524), (5.316, 17.524))
        marked = replace(cycle, layouts=tuple(replace(layout, plotter_alignment=PageAlignment(mark))
                                              for layout, mark in zip(layouts, marks, strict=True)))
        session.set_document(nine, 5, True, marked)
        record_one(6, (11.640, .910))
        session.page_list.setCurrentRow(5)
        assert "待对位" in session.alignment_status.text()
        assert session.job is None and session.registration is None
        assert not session.return_button.isEnabled() and not session.write_button.isEnabled()
        before = len(serial.commands)
        session.return_to_origin()
        session.start_writing()
        assert len(serial.commands) == before
        record_one(5, (3.650, .970))
        session.page_list.setCurrentRow(6)
        assert session.registration.origin == (11.640, .910)
        assert "第 7 页实测" in session.alignment_status.text()
        click(session, session.return_button)
        assert serial.position[:2] == [11.640, .910]
        assert session.job.strokes[0].points == ((13.324, -8.614), (15.324, -6.614))
        click(session, session.write_button)
        assert session.completed_pages == {6}
        assert any(b"X15.3240 Y-6.6140" in line for line in serial.commands)
        session.page_list.setCurrentRow(5)
        assert session.registration.origin == (3.650, .970), session.alignment_status.text()
        assert "第 6 页实测" in session.alignment_status.text()
        click(session, session.return_button)
        assert serial.position[:2] == [3.650, .970]
        assert session.job.strokes[0].points == ((5.320, -8.618), (7.320, -6.618))
        click(session, session.write_button)
        assert session.completed_pages == {5, 6}
        assert any(b"X7.3200 Y-6.6180" in line for line in serial.commands)
        session.page_list.setCurrentRow(7)
        assert session.registration is None and "待对位" in session.alignment_status.text()
        record_one(6, (13.640, 3.910))
        session.page_list.setCurrentRow(5)
        assert session.registration.origin == (3.650, .970)
        assert "第 6 页实测" in session.alignment_status.text()
        click(session, session.return_button)
        assert serial.position[:2] == [3.650, .970]
        session.page_list.setCurrentRow(7)
        assert session.registration is None
        session.page_list.setCurrentRow(1)
        assert session.registration.origin == (3.650, .970)
        assert "第 6 页实测" in session.alignment_status.text()
        record_one(5, (5.750, 4.070))
        session.page_list.setCurrentRow(6)
        assert session.registration.origin == (13.640, 3.910)
        other = replace(nine, document_id="second-document", snapshot_id="second")
        session.set_document(other, 6, True, marked)
        assert session.registration is None
        session.set_document(nine, 6, True, marked)
        assert session.registration.origin == (13.640, 3.910)
        assert "默认摆放" not in session.alignment_status.text()
        session.follow_page(2)
        assert "第 7 页实测" in session.alignment_status.text()
        assert session.registration.origin == (13.640, 3.910)
        click(session, session.link_button)
        click(session, session.link_button)
        assert session.registration is None and not session.return_button.isEnabled()
        assert not session.write_button.isEnabled()
    finally:
        session.shutdown()
        session.close()
    # Same physical USB device and coordinate frame after a serial reconnect.
    port.serialNumber = lambda: "N1-regression"
    serial = SimulatedGrbl()
    session = open_panel(serial)
    try:
        session.save_profile(DeviceProfile.create("重连机", "COM-test", port.serialNumber()))
        click(session, session.link_button)
        session.set_document(nine, 6, True, marked)
        record_one(6, (11.650, .970))
        record_one(7, (3.650, .970))
        serial.position[:] = [97.500, 59.460, 0.]
        click(session, session.link_button)
        before = len(serial.commands)
        click(session, session.link_button)
        assert "已沿用上次对位" in session.report.text()
        for index, expected in ((7, (3.650, .970)), (6, (11.650, .970)), (2, (11.650, .970))):
            session.page_list.setCurrentRow(index)
            assert session.registration.origin == expected
        session.page_list.setCurrentRow(5)
        assert session.registration is None
        assert all(line in {b"?", b"$$\n", b"$I\n"} for line in serial.commands[before:])
        for xy in ([98., 60.], [0., 0.]):
            record_one(6, (11.650, .970))
            click(session, session.link_button)
            serial.position[:2] = xy
            click(session, session.link_button)
            assert session.registration is None and not session.write_button.isEnabled()
    finally:
        session.shutdown()
        session.close()
    port.serialNumber = lambda: ""
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
        layouts = tuple(PageLayout(str(i), f"版式 {i}", source_page=i,
                                   plotter_alignment=PageAlignment((4+i, 3+2*i)) if i != 3 else None)
                        for i in range(1,5))
        cycle = FlowTemplate(kind="custom", layouts=layouts, loop_pages=("1","2","3","4"))
        nine = replace(snapshot, snapshot_id="nine", pages=tuple(replace(pages[0], index=i) for i in range(9)))
        panel.set_document(nine, 0, True, cycle)
        with patch.object(AlignmentDialog, "exec", capture_page):
            click(panel, panel.align_button)
        count = len(serial.commands)
        for i in (4, 3, 2, 8):
            panel.follow_page(i)
            assert panel.progress.isHidden()
            if i == 2:
                assert panel.registration is None and not panel.write_button.isEnabled()
                assert "PDF 第 3 页" in panel.alignment_status.text() and "缺少纸面原点" in panel.alignment_status.text()
                assert "模板缺纸面原点" in panel.page_list.item(i).text()
            elif i == 3:
                assert panel.job is None and not panel.write_button.isEnabled()
                assert "待对位" in panel.alignment_status.text()
            else:
                assert panel.job.index == i and panel.registration.origin == (40., 38.)
                assert panel.job.strokes[0].points == ((41., 40.), (43., 42.))
                assert all(text in panel.alignment_status.text() for text in
                           (f"第 {i+1} 页已沿用", "PDF 第 1 页", "本稿第 1 页登记"))
        assert panel.batch_pages() == [0, 1, 3, 4, 5, 7, 8]
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
        assert panel.job.index == 4 and "本次连接" in panel.alignment_status.text()
        # Save the third source layout from the writing panel and re-layout the document.
        from inkstruct.editor.machine_alignment import TemplateOriginDialog
        from inkstruct.resource_catalog import TemplateStore
        revisions = []
        def apply_revision(revision):
            revisions.append(revision)
            panel.set_document(nine, 2, True, revision)
        panel.template_origin_saved.connect(apply_revision)
        panel.follow_page(2)
        assert panel.add_origin_button.isVisible() and not panel.write_button.isEnabled()
        with patch.object(TemplateOriginDialog, "exec", lambda _dialog: 0):
            click(panel, panel.add_origin_button)
        assert not revisions
        def choose_mark(dialog):
            assert not dialog.save.isEnabled()
            dialog.canvas.picked.emit(8., 12.)
            dialog.save.click()
            return dialog.result()
        count = len(serial.commands)
        with patch.object(TemplateOriginDialog, "exec", choose_mark):
            click(panel, panel.add_origin_button)
        store = TemplateStore(workspace / "templates")
        assert len(store.entries()) == 1
        revised = store.read(store.entries()[0])
        assert revised == revisions[-1] and revised.layout(6).plotter_alignment.a == (8., 12.)
        assert store.save_paper_origins(cycle, revised) == revised and len(store.entries()) == 1
        for index in (2, 6, 0):
            panel.follow_page(index)
            assert not panel.add_origin_button.isVisible()
            if index == 0:
                assert panel.write_button.isEnabled() and panel.registration.origin == (40., 38.)
            else:
                assert panel.job is None and not panel.write_button.isEnabled()
                assert "待对位" in panel.alignment_status.text()
        assert len(serial.commands) == count
        # A partial loop starting at a missing layout must begin on the first configured sheet.
        partial = replace(cycle, loop_pages=("3", "2", "1", "4"))
        panel.set_document(nine, 1, True, partial)
        with patch.object(AlignmentDialog, "exec", ordinary_alignment):
            click(panel, panel.align_button)
        panel.scope.setCurrentIndex(1)
        assert panel.page_list.currentRow() == 1
        confirmations = []
        panel.confirm = lambda title, text, *args: confirmations.append(text) or True
        click(panel, panel.write_button)
        assert "跳过缺少纸面原点的第 1、5、9 页" in confirmations[-1]
        assert panel.completed_pages == {1} and panel.raw_page.index == 2
        assert panel.waiting_for_paper and panel.registration.origin == (40., 38.)
        assert panel.pending_pages == [3, 5, 6, 7]
        panel.stop()
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
