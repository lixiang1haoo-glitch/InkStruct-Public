"""N1 geometry and simulated transport checks. No serial device is opened."""

import math
import os
from collections import deque
from subprocess import run
import sys
from time import sleep

import pytest

from inkstruct.plotter.grbl import GrblLink, MachineError, MotionControl, Stopped, decode_status
from inkstruct.plotter.physical import PaperRegistration, WorkArea, position_page, registration_marks
from inkstruct.plotter.profiles import DeviceAxes
from inkstruct.plotter.schema import PlotPage, PlotStroke


class SimulatedGrbl:
    def __init__(self):
        self.responses = deque()
        self.commands = []
        self.packets = []
        self.position = [0., 0., 0.]
        self.held = False
        self.fail_next_motion = False
        self.on_write = lambda _data: None
        self.run_reports = 0
        self.closed = False
        self.trace = []
        self.unit_setting = "$13=0 (report inches, bool)"
        self.firmware = "[VER:1.1f / CX-Elite V2.1.003:]"
        self.hard_limits = "$21=0"
        self.report = lambda state, coords: f"<{state}|WPos:{coords}|WCO:0,0,0>"

    def write(self, data):
        self.packets.append(data)
        for line in data.splitlines(keepends=True):
            self.write_line(line)

    def write_line(self, data):
        assert not self.closed
        self.commands.append(data)
        self.trace.append(data)
        if data == b"?":
            if self.held:
                state = "Hold:0"
            elif self.run_reports:
                self.run_reports -= 1
                state = "Run"
            else:
                state = "Idle"
            coords = ",".join(map(str, self.position))
            self.responses.append(self.report(state, coords))
        elif data == b"!":
            self.held = True
        elif data == b"~":
            self.held = False
        elif data == b"\x18":
            self.held = False
            self.responses.clear()
        else:
            if data == b"$$\n":
                self.responses.extend((self.unit_setting, "$20=0", self.hard_limits))
            elif data == b"$I\n":
                self.responses.extend((self.firmware, "[OPT:VMPHL,15,1023]"))
            elif data.startswith(b"G1 "):
                if self.fail_next_motion:
                    raise OSError("USB disconnected")
                for word in data.decode().split()[1:]:
                    if word[0] in "XYZ":
                        self.position["XYZ".index(word[0])] = float(word[1:])
                self.run_reports = 2
            self.responses.append("ok")
        self.on_write(data)

    def readline(self, timeout):
        if self.responses:
            line = self.responses.popleft()
            self.trace.append(line)
            return line
        sleep(min(.003, timeout))
        return None

    def close(self):
        self.closed = True


def page_fixture():
    return PlotPage(0, 100, 80, (
        PlotStroke("one", ((2, 3), (3, 3), (3, 4))),
        PlotStroke("two", ((8, 8), (9, 9))),
    ))


def test_rigid_and_similarity_registration_share_frozen_geometry_and_test_marks():
    page = page_fixture()
    source = ((0, 0), (10, 0))
    target = ((40, 10), (40, 22))
    rigid = PaperRegistration.two_point(source, target)
    similarity = PaperRegistration.two_point(source, target, scale=True)
    assert rigid.place(source[0]) == target[0] and rigid.place(source[1]) == (40, 20)
    assert similarity.place(source[1]) == target[1]
    assert rigid.place((2, 3)) == (37, 12)
    assert similarity.place((2, 3)) == (36.4, 12.4)
    positioned = position_page(page, rigid)
    assert [stroke.name for stroke in positioned.strokes] == ["one", "two"]
    assert positioned.strokes[0].points == ((37, 12), (37, 13), (36, 13))
    assert page.strokes[0].points[0] == (2, 3)
    marks = registration_marks(page, similarity, ((5, 5), (10, 5), (5, 20)))
    for stroke, paper in zip(marks.strokes, ((5, 5), (10, 5), (5, 20)), strict=True):
        center = similarity.place(paper)
        assert stroke.points[0] == stroke.points[-1]
        assert all(math.isclose(math.dist(point, center), .5, abs_tol=.0001) for point in stroke.points)
    with pytest.raises(ValueError, match="独立核验"):
        registration_marks(page, rigid, ((5, 5), (10, 5), (15, 5)))


def test_axis_inversion_and_trial_use_the_same_logical_coordinates():
    axes = DeviceAxes(1.1, .9, mirror_x=True, swap=True)
    assert axes.map(5, 10) == (9, -5.5)
    assert axes.unmap(*axes.map(5, 10)) == (5, 10)
    registration = axes.register((6, 8), (30, 40), angle=math.pi / 2, scale=1.2)
    p, q = (6, 8), (16, 8)
    angle, scale = axes.measure((p, q), registration.place(p), registration.place(q))
    assert (angle, scale) == pytest.approx((math.pi / 2, 1.2))
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    serial.position[:] = [30., 40., 0.]
    with pytest.raises(ValueError, match="超出"):
        link.trial_axes(axes, WorkArea(0, 0, 80, 80), 2500, MotionControl())
    assert not any(command.startswith(b"G1 ") for command in serial.commands)
    link.trial_axes(axes, WorkArea(0, -20, 85, 100), 2500, MotionControl())
    assert (link.xy_command((30, -15), 2500) + "\n").encode("ascii") in serial.commands
    assert (link.xy_command((75, 40), 2500) + "\n").encode("ascii") in serial.commands


def test_unbounded_jog_uses_a_local_envelope_and_stops_on_axis_limit():
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    with pytest.raises(ValueError, match="超出"):
        link.jog((-1, 0), WorkArea(0, 0, 10, 10), MotionControl())
    link.jog((-1, 0), None, MotionControl())
    assert serial.position == [-1, 0, 0]
    serial.report = lambda state, coords: f"<{state}|WPos:{coords}|WCO:0,0,0>" if state != "Run" or coords.startswith("-1") else f"<{state}|WPos:{coords}|WCO:0,0,0|Pn:X>"
    with pytest.raises(MachineError, match="限位"):
        link.jog((-1, 0), None, MotionControl())


def test_template_and_local_placement_persist_separately(tmp_path):
    from inkstruct.document.flow_template import FlowTemplate, PageLayout
    from inkstruct.document.template_authoring import parse_template, template_json
    from inkstruct.document.template_revision import version_template
    from inkstruct.editor.machine_alignment import page_context
    from inkstruct.plotter.profiles import DeviceProfile, PageAlignment, PlotterProfiles

    first, second = (PageLayout(str(i), f"PDF {i}", source_page=i,
                               plotter_alignment=PageAlignment((5., i * 5.))) for i in range(1, 3))
    template = FlowTemplate(kind="custom", layouts=(first, second), loop_pages=("1", "2"))
    saved = parse_template(template_json(version_template(template)))
    key, _, mark, _ = page_context(saved, index=0)
    other, _, other_mark, _ = page_context(saved, index=1)
    assert mark.a == (5., 5.) and other_mark.a == (5., 10.) and key != other
    store = PlotterProfiles(tmp_path)
    a = DeviceProfile.create("N1", "COM3", "first")
    b = DeviceProfile.create("工作室", "COM4", "second")
    store.save(a)
    store.save(b)
    store.place(a, key, "纸夹左侧", mark, (25., 30.), (0., 0.))
    reopened = PlotterProfiles(tmp_path)
    assert reopened.devices() == [a, b]
    assert reopened.place(a, key, "纸夹左侧", mark)["point"] == [25., 30.]
    assert reopened.place(a, key, "纸夹右侧", mark) is None
    assert reopened.place(a, other, "纸夹左侧", other_mark) is None
    assert reopened.place(b, key, "纸夹左侧", mark) is None
    assert '"point"' not in template_json(saved)


def test_qt_device_profile_and_one_point_alignment(tmp_path):
    code = r"""
import sys
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
sys.path.insert(0, str(Path.cwd()/'tests'))
from test_plotter_machine import SimulatedGrbl
from PySide6 import QtCore, QtWidgets
from inkstruct.document.flow_template import FlowTemplate
from inkstruct.editor.machine_alignment import AlignmentDialog, page_context
from inkstruct.editor.machine_devices import DeviceDialog
from inkstruct.editor.machine_panel import MachinePanel
from inkstruct.plotter.profiles import DeviceProfile, PageAlignment
from inkstruct.plotter.qt_connection import N1Worker
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp

app = QtWidgets.QApplication([])
settings = QtCore.QSettings
settings.setDefaultFormat(settings.Format.IniFormat)
settings.setPath(settings.Format.IniFormat, settings.Scope.UserScope, sys.argv[1])
transport = SimulatedGrbl()
transport.position[:] = [35., 30., 0.]
port = SimpleNamespace(portName=lambda: "COM3", serialNumber=lambda: "first")
panel = MachinePanel(None, worker_factory=lambda parent: N1Worker(parent, serial_factory=lambda _: transport),
                     ports=lambda: [port])
panel.set_workspace(Path(sys.argv[1]))
def wait():
    deadline = monotonic() + 8
    while panel.busy is not None and monotonic() < deadline:
        app.processEvents()
        sleep(.01)
    assert panel.busy is None, panel.report.text()

try:
    panel.save_profile(DeviceProfile.create("测试 N1", "COM3", "first"))
    setup = DeviceDialog(panel)
    assert setup.devices.count() == 1
    setup.link.click()
    wait()
    assert panel.device is not None and not panel.confirmed_area
    setup.axes[0].setChecked(True)
    setup.axes[2].setChecked(True)
    setup.jog[2].click()
    assert isinstance(setup.stop.parentWidget(), QtWidgets.QDialogButtonBox)
    assert not setup.stop.isHidden()
    wait()
    assert transport.position == [35., 29., 0.] and not panel.profile.axes.swap
    assert not any(command.startswith(b"G1 Z-") for command in transport.commands)
    setup.record_buttons[0].click()
    wait()
    assert [spin.value() for spin in setup.bounds[:2]] == [35., 29.]
    for spin, value in zip(setup.bounds, (0, 0, 100, 100), strict=True):
        spin.setValue(value)
    setup.use_range.setChecked(True)
    setup.save_button.click()
    profile = panel.store.devices()[0]
    assert profile.axes.swap and profile.axes.mirror_x and panel.confirmed_area == profile.area
    setup.close()

    template = FlowTemplate(width_mm=70, height_mm=60, plotter_alignment=PageAlignment((5, 5)))
    page = Page(0, (), (PaintOp("字", ((6., 7.), (8., 9.)), .3),))
    snapshot = LayoutSnapshot("snapshot", "key", "doc", 0, template.page, (page,), (), "resource", "test")
    panel.set_document(snapshot, 0, True, template)
    panel.show()
    context = page_context(template, snapshot, 0)
    align = AlignmentDialog(panel, panel, *context, snapshot=snapshot)
    align.record_a.click()
    wait()
    assert align.measurement == (35., 29.)
    align.save.click()
    assert align.result() and align.position == align.measurement
    panel.use_alignment(align.alignment, align.position)
    assert panel.job.strokes[0].points == ((37., 28.), (39., 26.))
    assert panel.write_button.isEnabled() and panel.dry_job is None
    panel.confirm = lambda *_: True
    reuse = AlignmentDialog(panel, panel, *context, snapshot=snapshot)
    reuse.recall.click()
    assert reuse.result() and reuse.position == align.position
    panel.write_button.click()
    wait()
    assert "书写完成" in panel.report.text()

    measure = AlignmentDialog(panel, panel, *context, configure=True)
    transport.position[:] = [35., 29., 0.]
    measure.record_a.click()
    wait()
    measure.use_b.setChecked(True)
    measure.b[0].setValue(15)
    transport.position[:] = [35., 17., 0.]
    measure.record_b.click()
    wait()
    measure.save.click()
    assert measure.result() and measure.alignment.scale == 1.2 and measure.alignment.angle == 0.
finally:
    panel.shutdown()
    panel.close()
"""
    result = run([sys.executable, "-c", code, str(tmp_path)],
                 env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen")},
                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("setting", ["$13=0", "$13=0 (report inches, bool)"])
def test_grbl_work_coordinates_use_offset_and_do_not_move_on_connect(setting):
    status = decode_status("<Idle|MPos:10,20,30,40|WCO:2,4,6,0>")
    assert status.position == (8, 16, 24)
    assert decode_status("<Run|MPos:11,22,33>", status.offset).position == (9, 18, 27)
    assert decode_status("<Idle|MPos:10,20,30>").position is None
    with pytest.raises(MachineError):
        decode_status("<Idle|WPos:nan,0,0>")
    serial = SimulatedGrbl()
    serial.unit_setting = setting
    link = GrblLink(serial)
    assert link.connect().position == (0, 0, 0)
    assert serial.commands == [b"?", b"$$\n", b"$I\n", b"?"]


def test_grbl_reconnect_discards_the_startup_ack_before_querying_units():
    serial = SimulatedGrbl()
    serial.responses.extend(("Grbl 1.1f ['$' for help]", "ok"))
    link = GrblLink(serial)
    assert link.connect().position == (0, 0, 0)
    assert serial.commands == [b"?", b"$$\n", b"$I\n", b"?"]
    assert not link.responses


@pytest.mark.parametrize("setting", ["$13=1", "$13=1 (report inches, bool)", "$13=0.5", "$13=unknown"])
def test_grbl_connect_rejects_unknown_or_nonmetric_reporting(setting):
    serial = SimulatedGrbl()
    serial.unit_setting = setting
    with pytest.raises(MachineError, match="毫米"):
        GrblLink(serial).connect()
    assert serial.commands == [b"?", b"$$\n"]


@pytest.mark.parametrize("dry_run", [True, False])
def test_ack_is_not_completion_and_dry_run_traverses_the_exact_written_path(dry_run):
    placed = position_page(page_fixture(), PaperRegistration((10, 20)))
    progress = []
    serial = SimulatedGrbl()
    serial.position[:] = [10, 20, 0]
    link = GrblLink(serial, progress=lambda n, total: progress.append((n, total)))
    link.connect()
    state = link.run_page(placed, WorkArea(0, 0, 100, 100), MotionControl(), dry_run=dry_run, feed=900)
    xy = [command.decode().split()[1:3] for command in serial.commands if command.startswith(b"G1 X")]
    assert xy == [[f"X{x:.4f}", f"Y{y:.4f}"] for stroke in placed.strokes for x, y in stroke.points]
    assert serial.commands.count(b"G1 Z-1.6 F5000\n") == (0 if dry_run else 2)
    actual_motion = [command for command in serial.commands if command.startswith(b"G1 ")]
    assert actual_motion[0] == actual_motion[-1] == b"G1 Z0 F5000\n"
    assert progress == [(1, 2), (2, 2)]
    tail = serial.trace[serial.trace.index(actual_motion[-1], serial.trace.index(b"G1 X19.0000 Y29.0000 F900\n")):]
    assert any(str(value).startswith("<Run") for value in serial.trace[serial.trace.index(b"G1 X19.0000 Y29.0000 F900\n"):])
    assert tail[-1].startswith("<Idle") and any(value == "ok" for value in tail)
    assert state.state == "Idle" and state.position == (19, 29, 0)


def test_short_points_are_batched_to_six_and_preserve_pen_order():
    serial = SimulatedGrbl()
    serial.position[:] = [10, 10, 0]
    link = GrblLink(serial)
    link.connect()
    points = tuple((10 + i / 2, 10.0) for i in range(15))
    page = PlotPage(0, 50, 50, (PlotStroke("dense", points),))
    link.run_page(position_page(page, PaperRegistration((0, 0))), WorkArea(0, 0, 50, 50), MotionControl(), feed=2500)
    packets = [p.splitlines() for p in serial.packets if p.startswith(b"G1 X")]
    assert [len(p) for p in packets] == [6, 6, 2]
    assert [line for p in packets for line in p] == [link.xy_command(point, 2500).encode() for point in points[1:]]
    arm = serial.commands.index(b"G1 Z-1.6 F5000\n")
    assert b"G1 X10.5000 Y10.0000 F2500\n" in serial.commands[arm + 1:]


@pytest.mark.parametrize("pin", ["X", "Y"])
def test_qualified_interior_single_axis_report_is_verified_at_clear_endpoint(pin, caplog):
    serial = SimulatedGrbl()
    serial.position[:] = [10, 10, 0]
    link = GrblLink(serial)
    link.connect()
    def report(state, xyz):
        if xyz.startswith("12.") and state == "Run":
            return f"<Run|WPos:11,10,0|Pn:{pin}>"
        return f"<{state}|WPos:{xyz}>"
    serial.report = report
    status = link.move_to((12, 10), WorkArea(0, 0, 30, 30), MotionControl())
    assert status.position == (12, 10, 0) and status.limits == ""
    assert f"Pn:{pin}" in caplog.text
    assert b"!" not in serial.commands and b"\x18" not in serial.commands


@pytest.mark.parametrize("case", ["persist", "boundary", "unknown", "hard_limits", "Z", "XY", "deviation"])
def test_limit_review_fails_closed(case):
    serial = SimulatedGrbl()
    serial.position[:] = [10, 10, 0]
    if case == "unknown":
        serial.firmware = "[VER:1.1f.20170801:]"
    if case == "hard_limits":
        serial.hard_limits = "$21=1"
    link = GrblLink(serial)
    link.connect()
    target = 12.0
    limits = case if case in {"Z", "XY"} else "Y"
    def report(state, xyz):
        triggered = xyz.startswith("12.") and (state == "Run" or case == "persist")
        if triggered and case == "deviation":
            xyz = "12,15,0"
        return f"<{state}|WPos:{xyz}" + (f"|Pn:{limits}>" if triggered else ">")
    serial.report = report
    area = WorkArea(0, 0, 13 if case == "boundary" else 30, 30)
    with pytest.raises(MachineError):
        link.move_to((target, 10), area, MotionControl())


def test_pin_review_stops_sending_next_packet_until_verified_idle():
    serial = SimulatedGrbl()
    serial.position[:] = [10, 10, 0]
    link = GrblLink(serial)
    link.connect()
    link.motion_active = True
    def report(state, xyz):
        return f"<{state}|WPos:{xyz}" + ("|Pn:X>" if xyz.startswith("16.") and state == "Run" else ">")
    serial.report = report
    link.move_path(link.last_status, tuple((10 + i, 10.0) for i in range(1, 14)),
                   WorkArea(0, 0, 100, 100), 2500, 0, MotionControl())
    first = serial.trace.index(b"G1 X16.0000 Y10.0000 F2500\n")
    second = serial.trace.index(b"G1 X17.0000 Y10.0000 F2500\n")
    interval = serial.trace[first:second]
    assert any(isinstance(x, str) and x.endswith("|Pn:X>") for x in interval)
    assert sum(isinstance(x, str) and x.startswith("<Idle|WPos:16") for x in interval) == 2


def test_joint_xy_report_on_diagonal_can_clear_but_alarm_still_aborts():
    serial = SimulatedGrbl()
    serial.position[:] = [10, 10, 0]
    link = GrblLink(serial)
    link.connect()
    def diagonal_report(state, xyz):
        if xyz.startswith("12.") and state == "Run":
            return "<Run|WPos:11,11,0|Pn:XY>"
        return f"<{state}|WPos:{xyz}>"
    serial.report = diagonal_report
    area = WorkArea(0, 0, 30, 30)
    assert link.move_to((12, 12), area, MotionControl()).position == (12, 12, 0)
    link.motion_active = False
    serial.report = lambda state, xyz: "ALARM:1" if state == "Run" and xyz.startswith("14.") else f"<{state}|WPos:{xyz}>"
    with pytest.raises(MachineError, match="ALARM:1"):
        link.move_to((14, 14), area, MotionControl())


def test_preflight_rejects_out_of_bounds_before_any_motion():
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    placed = position_page(page_fixture(), PaperRegistration((9, 9)))
    with pytest.raises(ValueError, match="超出"):
        link.run_page(placed, WorkArea(0, 0, 15, 15), MotionControl())
    assert all(command in {b"?", b"$$\n", b"$I\n"} for command in serial.commands)
    with pytest.raises(ValueError, match="点动终点"):
        link.jog((-1, 0), WorkArea(0, 0, 15, 15), MotionControl())
    serial.position[2] = -5
    with pytest.raises(MachineError, match="升降笔范围"):
        link.touch(WorkArea(0, 0, 15, 15), MotionControl())
    assert all(command in {b"?", b"$$\n", b"$I\n"} for command in serial.commands)


def test_pause_consumes_the_hold_report_without_losing_the_pending_ack():
    serial, control, phases = SimulatedGrbl(), MotionControl(), []
    def phase(state):
        phases.append(state)
        if state == "paused":
            control.pause_requested.clear()
    link = GrblLink(serial, phase=phase)
    link.connect()
    at = b"G1 X13.0000 Y23.0000 F2500\n"
    serial.on_write = lambda data: control.pause_requested.set() if data == at else None
    placed = position_page(page_fixture(), PaperRegistration((10, 20)))
    link.run_page(placed, WorkArea(0, 0, 100, 100), control)
    first_xy = serial.commands.index(at)
    hold = serial.commands.index(b"!", first_xy)
    resume = serial.commands.index(b"~", hold)
    assert serial.commands[hold + 1:resume] == [b"?"]
    assert phases == ["running", "pausing", "paused", "running"]


def test_stop_clears_queued_motion():
    serial, control = SimulatedGrbl(), MotionControl()
    link = GrblLink(serial)
    link.connect()
    serial.on_write = lambda data: control.stop_requested.set() if data.startswith(b"G1 X") else None
    placed = position_page(page_fixture(), PaperRegistration((10, 20)))
    with pytest.raises(Stopped):
        link.run_page(placed, WorkArea(0, 0, 100, 100), control)
    link.abort()
    assert serial.commands[-3:] == [b"!", b"?", b"\x18"]
    assert serial.commands.count(b"G1 Z-1.6 F5000\n") == 0


def test_qt_panel_writes_without_dry_run_and_disconnect_invalidates_registration(tmp_path):
    code = r"""
import sys
from pathlib import Path
from types import SimpleNamespace
from time import monotonic, sleep
sys.path.insert(0, str(Path.cwd()/'tests'))
from test_plotter_machine import SimulatedGrbl
from PySide6 import QtWidgets
from inkstruct.document.schema import PageProfile
from inkstruct.editor.machine_panel import MachinePanel
from inkstruct.plotter.qt_connection import N1Worker
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp

app = QtWidgets.QApplication([])
transport = SimulatedGrbl()
page = Page(index=0, fragments=(), paint_ops=(PaintOp("one", ((3.,4.), (5.,6.)), .3),))
snapshot = LayoutSnapshot("snapshot", "key", "document", 0, PageProfile(70, 60, 5),
                          (page,), (), "resource", "test")
worker = lambda parent: N1Worker(parent, serial_factory=lambda _port: transport)
ports = lambda: [SimpleNamespace(portName=lambda: "COM-test")]
dialog = MachinePanel(None, worker_factory=worker, ports=ports)
dialog.set_workspace(Path(sys.argv[1]))
dialog.set_document(snapshot, 0, True)
dialog.show()
try:
    assert dialog.feed.value() == 2500 and dialog.feed.maximum() == 5000
    def wait_for(condition):
        end = monotonic() + 8
        while monotonic() < end:
            app.processEvents()
            if condition():
                return
            sleep(.01)
        raise AssertionError(dialog.report.text())
    assert not dialog.write_button.isEnabled() and not dialog.dry_button.isEnabled()
    dialog.link_button.click()
    wait_for(lambda: dialog.device is not None and dialog.busy is None)
    assert transport.commands == [b"?", b"$$\n", b"$I\n", b"?"]
    dialog.area_confirm.setChecked(True)
    dialog.origin[0].setValue(10)
    dialog.origin[1].setValue(15)
    dialog.confirm_alignment.click()
    placed = dialog.job
    dialog.preview_button.click()
    assert dialog.preview.job is placed and placed.strokes[0].points == ((13.,19.), (15.,21.))
    assert dialog.dry_button.isEnabled() and dialog.write_button.isEnabled()
    assert dialog.dry_job is None
    assert not any(command.startswith(b"G1 Z-") for command in transport.commands)
    dialog.confirm = lambda *_: True
    dialog.write_button.click()
    wait_for(lambda: "书写完成" in dialog.report.text() and dialog.busy is None)
    assert b"G1 Z-1.6 F5000\n" in transport.commands
    assert dialog.write_button.isEnabled()

    dialog.options.setChecked(True)
    dialog.mode.setCurrentIndex(dialog.mode.findData("preprinted"))
    for index, (x, y) in enumerate(((60, 30), (60, 70), (30, 31))):
        transport.position[:] = [x, y, 0]
        dialog.capture_buttons[index].click()
        wait_for(lambda: index in dialog.captured and dialog.busy is None)
    dialog.confirm_alignment.click()
    assert dialog.job.registration.scale == 1
    assert (dialog.job.registration.cosine, dialog.job.registration.sine) == (0, 1)
    assert "1.000 mm" in dialog.verify_label.text()
    registered = dialog.job
    dialog.point_fields[2][0].setValue(16)
    assert dialog.job is registered and "0.000 mm" in dialog.verify_label.text()
    before_marks = transport.commands.count(b"G1 Z-1.6 F5000\n")
    dialog.test_button.click()
    wait_for(lambda: "三个测试点已画完" in dialog.report.text() and dialog.busy is None)
    assert transport.commands.count(b"G1 Z-1.6 F5000\n") == before_marks + 3
    assert dialog.preview.job is dialog.job and dialog.write_button.isEnabled()

    transport.fail_next_motion = True
    dialog.dry_button.click()
    wait_for(lambda: dialog.device is None and dialog.busy is None)
    assert dialog.registration is None and dialog.confirmed_area is None and dialog.dry_job is None
    assert transport.closed and "重新连接" in dialog.report.text()
finally:
    dialog.shutdown()
    dialog.close()
"""
    result = run([sys.executable, "-c", code, str(tmp_path)],
                 env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen"),
                      "PYTHONUTF8": "1"},
                 capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

def test_qt_sidebar_preserves_views_and_waits_between_paper_pages(tmp_path):
    code = r"""
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from time import monotonic, sleep
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd()/'tests'))
from test_plotter_machine import SimulatedGrbl
from PySide6 import QtCore, QtWidgets
from inkstruct.document.schema import PageProfile
from inkstruct.editor import machine_panel, workspace
from inkstruct.editor.mixed import MixedWindow
from inkstruct.plotter.qt_connection import N1Worker
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp

app = QtWidgets.QApplication([])
settings = QtCore.QSettings
settings.setDefaultFormat(settings.Format.IniFormat)
settings.setPath(settings.Format.IniFormat, settings.Scope.UserScope, sys.argv[1])
transport = SimulatedGrbl()
factory = partial(N1Worker, serial_factory=lambda _port: transport)
ports = lambda: [SimpleNamespace(portName=lambda: "COM-test")]
panel = partial(machine_panel.MachinePanel, worker_factory=factory, ports=ports)
with patch.object(workspace, "sys", SimpleNamespace(platform="win32")), \
        patch.object(machine_panel, "MachinePanel", panel):
    w = MixedWindow(source="test source")
w.timer.stop()
w.resize(1350, 840)
w.show()
p = w.machine_panel
try:
    def wait_for(condition):
        end = monotonic() + 8
        while monotonic() < end:
            app.processEvents()
            if condition():
                return
            sleep(.005)
        raise AssertionError(p.report.text())
    assert set(w.tabifiedDockWidgets(w.machine_dock)) == {w.problems_dock, w.element_properties_dock}
    assert w.findChild(QtWidgets.QToolButton, "document_machine") is None
    assert not p.worker.isRunning()
    pages = tuple(Page(index, (), (PaintOp(str(index), ((3.,4.), (5.,6.)), .3),))
                  for index in range(2))
    snap = LayoutSnapshot("snapshot", "key", "document", 0, PageProfile(70, 60, 5),
                          pages, (), "resource", "test")
    w.snapshot = snap
    w.page_picker.setMaximum(2)
    p.set_document(snap, 0, True)
    w.workspace_views.set_mode("split", persist=False)
    app.processEvents()
    before = w.workspace_views.splitter.sizes()
    w.machine_dock.raise_()
    wait_for(lambda: p.page_list.count() == 2)
    p.page_list.setCurrentRow(1)
    assert w.page_picker.value() == 2 and p.paper_page.index == 1
    p.scope.setCurrentIndex(p.scope.findData("all"))
    assert p.paper_page.index == 0 and not p.page_list.isEnabled()
    p.link_button.click()
    wait_for(lambda: p.device is not None and p.busy is None)
    assert not p.jog_buttons[0].isEnabled()
    p.area_confirm.setChecked(True)
    p.confirm = lambda *_: True
    p.pen_button.click()
    wait_for(lambda: not p.pen_raised and p.busy is None)
    assert p.pen_button.text() == "抬笔" and not p.link_button.isEnabled()
    p.pen_button.click()
    wait_for(lambda: p.pen_raised and p.busy is None)
    p.origin_capture.click()
    wait_for(lambda: p.job is not None)
    p.dry_button.click()
    wait_for(lambda: p.dry_job is p.job and p.busy is None)

    p.write_button.click()
    assert p.is_moving and p.close_blocker()
    p.write_button.click()
    wait_for(lambda: b"!" in transport.commands)
    w.problems_dock.raise_()
    app.processEvents()
    w.element_properties_dock.raise_()
    app.processEvents()
    p.set_document(None, 0, False)
    assert p.snapshot is snap and p.batch_active
    w.machine_dock.raise_()
    app.processEvents()
    assert p.busy == "write" and p.write_button.text() == "继续" and p.snapshot is snap
    assert w.editor.toPlainText() == "test source"
    assert w.workspace_views.mode == "split" and w.workspace_views.splitter.sizes() == before
    p.set_document(snap, 0, True)
    p.write_button.click()
    wait_for(lambda: p.waiting_for_paper)
    assert p.page_list.currentRow() == 1 and p.completed_pages == {0}
    assert p.job is None and p.close_blocker() and p.write_button.text() == "换纸完成"
    count = len(transport.commands)
    p.write_button.click()
    app.processEvents()
    assert p.batch_active and not p.waiting_for_paper and len(transport.commands) == count
    assert not p.dry_button.isEnabled() and not p.write_button.isEnabled()
    p.origin_capture.click()
    wait_for(lambda: p.job is not None)
    p.dry_button.click()
    wait_for(lambda: p.dry_job is p.job and p.busy is None)
    p.write_button.click()
    wait_for(lambda: not p.batch_active and p.busy is None)
    assert p.completed_pages == {0, 1} and not p.close_blocker()

    p.scope.setCurrentIndex(p.scope.findData("single"))
    p.dry_button.click()
    wait_for(lambda: p.dry_job is p.job and p.busy is None)
    previous = len(transport.commands)
    transport.on_write = lambda data: sleep(.05) if data.startswith(b"G1 ") else None
    p.write_button.click()
    wait_for(lambda: any(command.startswith(b"G1 ") for command in transport.commands[previous:]))
    p.stop_button.click()
    wait_for(lambda: p.busy is None and p.device is None)
    assert b"\x18" in transport.commands and transport.closed
    assert not p.dry_button.isEnabled() and p.registration is None
    p.set_document(replace(snap, snapshot_id="new", revision=1), 0, True)
    assert p.snapshot.revision == 1 and p.completed_pages == set()
finally:
    p.shutdown()
    w.dirty = False
    w.close()
"""
    result = run([sys.executable, "-c", code, str(tmp_path)],
                 env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_TEST_QT_PLATFORM", "offscreen"),
                      "PYTHONUTF8": "1"},
                 capture_output=True, text=True, encoding="utf-8", timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
