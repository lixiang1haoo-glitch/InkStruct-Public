"""N1 journal failures at raised-pen barriers, using the real serial worker."""
import json
import os
from pathlib import Path
from queue import Queue

import pytest
from PySide6 import QtCore

from inkstruct.plotter.docking import idle_checkpoint, restored_frame
from inkstruct.plotter.physical import PaperRegistration, WorkArea, position_page
from inkstruct.plotter.qt_connection import N1Worker
from inkstruct.plotter.schema import PlotPage, PlotStroke
from inkstruct.plotter.write_session import ProgressFile
from test_dock_registration import device
from test_plotter_machine import SimulatedGrbl


@pytest.mark.parametrize(("before_pen", "failure"), [
    (before, mode) for before in (True, False)
    for mode in ("once", "persistent", "stop", "no-area", "outside", "disk-full", "reset")
])
def test_progress_replace_failure(tmp_path, monkeypatch, before_pen, failure):
    start = 3849
    page = PlotPage(1, 200, 270, tuple(
        PlotStroke(str(i), ((124.98, 214.91), (125.98, 214.91))) for i in range(4396)
    ))
    machine = position_page(page, PaperRegistration((0, 0)))
    journal = ProgressFile.for_page(tmp_path, "doc", page, "layout", "device")
    journal.save(start, False)
    transport = SimulatedGrbl()
    origin = (120., 210.)
    transport.position[:2] = origin
    worker = N1Worker(serial_factory=lambda _: transport)
    results = Queue()
    direct = QtCore.Qt.ConnectionType.DirectConnection
    worker.succeeded.connect(lambda kind, state: results.put((kind, state, False)), direct)
    worker.failed.connect(lambda kind, detail, lost: results.put((kind, detail, lost)), direct)
    replace_file = os.replace
    refused = []
    def replace_progress(source, destination):
        if Path(destination) == journal.path:
            record = json.loads(Path(source).read_bytes())
            if (record["check_stroke"] == before_pen and record["completed"] == start + int(not before_pen)
                    and (failure != "once" or not refused)):
                refused.append(len(transport.commands))
                if failure == "stop":
                    worker.control.stop_requested.set()
                if failure == "reset" and len(refused) == 1:
                    transport.responses.append("Grbl 1.1f")
                if failure == "disk-full":
                    raise OSError(28, "disk full")
                error = PermissionError(13, "replace denied")
                error.winerror = 5
                raise error
        return replace_file(source, destination)
    monkeypatch.setattr(os, "replace", replace_progress)
    def reported(command):
        transport.run_reports = 0
        if failure == "once" and command.startswith(b"G1 Z-"):
            worker.control.finish_stroke.set()
    transport.on_write = reported
    worker.start()
    try:
        worker.submit("connect", "test")
        assert results.get(timeout=5)[0] == "connect"
        area = None if failure == "no-area" else WorkArea(0, 0, 200, 270)
        dock = (-1., 210.) if failure == "outside" else origin
        worker.submit("write", machine, area, 2500, dict(journal=journal, start=start, failure_dock=dock))
        kind, result, lost = results.get(timeout=10)
        assert kind == "write" and refused
        if failure in {"stop", "reset"}:
            assert lost and b"\x18" in transport.commands
            assert not any(c.startswith(b"G1 ") for c in transport.commands[refused[0]:])
            return
        assert not lost and not transport.closed and b"\x18" not in transport.commands
        downs = transport.commands.count(b"G1 Z-1.6 F5000\n")
        if failure == "once":
            assert len(refused) == downs == 1 and worker.page_failure is None
            assert journal.read() == (start + 1, False)
            return
        assert len(refused) == (1 if failure == "disk-full" else 4)
        assert len(set(refused)) == 1
        assert str(start + 1) in worker.page_failure
        assert downs == int(not before_pen) and journal.read() == (start, not before_pen)
        moves = [c for c in transport.commands[refused[-1]:] if c.startswith(b"G1 ")]
        assert moves[0] == b"G1 Z0 F5000\n"
        if failure == "outside":
            assert moves == [b"G1 Z0 F5000\n"] and "原地抬笔" in worker.page_failure
        else:
            assert result.position == (*origin, 0.) and "确认抬笔回停靠点" in worker.page_failure
            worker.submit("disconnect")
            assert results.get(timeout=5)[0] == "disconnect"
            p = device()
            proof = idle_checkpoint(p, origin, worker.stopped_at)
            transport.closed = False
            worker.submit("connect", "test")
            _, fresh, _ = results.get(timeout=5)
            assert worker.stable_on_connect and restored_frame(p, proof, fresh) == origin
    finally:
        worker.shutdown()
        assert worker.wait(5000)


@pytest.mark.parametrize("recovery", ["works", "pen-stuck", "stop", "xy-changed", "disconnect"])
def test_pen_still_down_after_stroke(recovery, tmp_path):
    page = PlotPage(0, 50, 50, (PlotStroke("first", ((2., 3.), (4., 5.))),
                                PlotStroke("next", ((8., 8.), (9., 9.)))))
    job = position_page(page, PaperRegistration((0, 0)))
    journal = ProgressFile.for_page(tmp_path, "doc", page, "layout", "device")
    serial = SimulatedGrbl()
    worker = N1Worker(serial_factory=lambda _: serial)
    results = Queue()
    direct = QtCore.Qt.ConnectionType.DirectConnection
    worker.succeeded.connect(lambda kind, state: results.put((state, False)), direct)
    worker.failed.connect(lambda kind, detail, lost: results.put((detail, lost)), direct)
    failed_at = []

    def simulate(command):
        serial.run_reports = 0
        if serial.position[:2] == [4., 5.] and command.startswith(b"G1 Z0"):
            if not failed_at or recovery == "pen-stuck":
                serial.position[2] = -1.6
                failed_at.append(len(serial.commands))
        if failed_at and len(serial.commands) == failed_at[0] + 1 and command == b"?":
            if recovery == "stop":
                worker.control.stop_requested.set()
            elif recovery == "xy-changed":
                serial.position[0] += 1.
            elif recovery == "disconnect":
                raise OSError("USB disconnected")

    serial.on_write = simulate
    worker.start()
    try:
        worker.submit("connect", "test")
        assert results.get(timeout=5)[1] is False
        worker.submit("write", job, None, 2500, dict(journal=journal, failure_dock=(0., 0.)))
        result, lost = results.get(timeout=10)
        assert failed_at and journal.read() == (0, True)
        moves = [c for c in serial.commands[failed_at[0]:] if c.startswith(b"G1 ")]
        if recovery == "works":
            assert not lost and result.position == (0., 0., 0.) and "确认抬笔回停靠点" in worker.page_failure
            assert moves[0] == b"G1 Z0 F5000\n" and all(c.startswith(b"G1 X") for c in moves[1:])
        else:
            assert lost and not any(c.startswith(b"G1 X") for c in moves)
    finally:
        worker.shutdown()
        assert worker.wait(5000)


def test_unaligned_sidebar_and_recovery_pen_during_jog(tmp_path):
    from threading import Event
    from time import monotonic, sleep
    from types import SimpleNamespace
    from PySide6 import QtWidgets
    from inkstruct.editor.machine_alignment import AlignmentDialog
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.plotter.profiles import PageAlignment

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    serial = SimulatedGrbl()
    serial.position[:] = [20., 35., 0.]
    def opened(_):
        serial.closed = False
        return serial
    panel = MachinePanel(None, worker_factory=lambda w: N1Worker(w, serial_factory=opened),
                         ports=lambda: [SimpleNamespace(portName=lambda: "sim", serialNumber=lambda: "usb-id")])
    panel.set_workspace(tmp_path)
    panel.save_profile(device())
    panel.confirm = lambda *_: True
    def wait(until):
        deadline = monotonic() + 10
        while not until() and monotonic() < deadline:
            app.processEvents()
            sleep(.002)
        assert until(), panel.report.text()
    panel.show()
    moving, release = Event(), Event()
    def block_motion(command):
        if command.startswith(b"G1 X") and not moving.is_set():
            moving.set()
            assert release.wait(5)
    try:
        panel.toggle_connection()
        wait(lambda: panel.device is not None and panel.busy is None)
        assert not panel.datum_located and not panel.current_page_ready()
        dialog = AlignmentDialog(panel, "fixture", (100, 100), PageAlignment((5, 5)),
                                 "恢复版式", recovery=True, archived=True)
        dialog.show()
        for button in (panel.pen_button, dialog.pen):
            begin = len(serial.commands)
            for height in (-1.6, 0):
                assert button.isEnabled()
                button.click()
                wait(lambda: panel.busy is None)
                assert panel.device.position == (20, 35, height)
            assert [c for c in serial.commands[begin:] if c.startswith(b"G1")] == [
                b"G1 Z-1.6 F5000\n", b"G1 Z0 F5000\n"]
        dialog.close()
        serial.on_write = block_motion
        assert panel.submit("device-jog", (12, 0), None, 1200)
        wait(moving.is_set)
        panel.moving_down.click()
        release.set()
        wait(lambda: panel.device.position[2] == -1.6)
        parked = panel.device.position[:2]
        begin = len(serial.commands)
        panel.pen_button.click()
        wait(lambda: panel.device.position[2] == 0)
        assert panel.busy == "device-jog" and panel.device.position[:2] == parked
        assert not any(c.startswith(b"G1 X") for c in serial.commands[begin:])
        panel.write_button.click()
        wait(lambda: panel.busy is None)
        assert panel.device.position == (32, 35, 0)
        moving.clear()
        release.clear()
        assert panel.submit("device-jog", (-12, 0), None, 1200)
        wait(moving.is_set)
        panel.moving_down.click()
        serial.responses.appendleft("ALARM:1")
        release.set()
        wait(lambda: panel.busy is None)
        assert panel.device is None and b"\x18" in serial.commands
        serial.run_reports = 0  # Controller has finished resetting before manual reconnect.
        serial.on_write = lambda _: None
        begin = len(serial.commands)
        panel.toggle_connection()
        wait(lambda: panel.busy is None)
        assert panel.device and not panel.datum_located
        assert not any(c.startswith(b"G1 ") for c in serial.commands[begin:])
    finally:
        release.set()
        panel.shutdown()
        panel.close()



def test_small_increments_of_xy_drift_do_not_rebase_the_paused_position():
    from inkstruct.plotter.grbl import GrblLink, MachineError, MotionControl

    serial = SimulatedGrbl()
    controller = GrblLink(serial)
    state = controller.connect()
    control = MotionControl()
    control.request_idle_pause()
    def drifting(state_name, _coords):
        serial.position[0] += .004
        return f"<{state_name}|WPos:{serial.position[0]},0,0|WCO:0,0,0>"
    serial.report = drifting
    with pytest.raises(MachineError, match="暂停期间 XY"):
        controller.manual_at_rest(state, control)
    assert not any(command.startswith(b"G1 ") for command in serial.commands)
