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


def test_referenced_long_jog_rechecks_bounds_from_fresh_start():
    serial = SimulatedGrbl()
    serial.position[:] = (1., 2., 0.)
    link, control = GrblLink(serial), MotionControl()
    link.connect()
    link.confirm_datum_position(control)
    # The UI admitted an 8 mm jog to the edge. The next status differs by
    # 0.04 mm, within the continuity tolerance but now outside the bounds.
    serial.position[1] += .04
    with pytest.raises(ValueError, match="点动终点"):
        link.jog((0., 8.), WorkArea(0, 0, 10, 10), control, commissioning=True, require_bounds=True)
    assert not any(line.startswith(b"G1 ") for line in serial.commands)


def page_fixture():
    return PlotPage(0, 100, 80, (
        PlotStroke("one", ((2, 3), (3, 3), (3, 4))),
        PlotStroke("two", ((8, 8), (9, 9))),
    ))


def xy_feeds_by_pen(commands):
    feeds = {False: [], True: []}
    down = False
    for line in commands:
        if line.startswith(b"G1 Z"):
            down = float(line.split()[1][1:]) < 0
        elif line.startswith(b"G1 X"):
            feeds[down].append(int(line.split()[-1][1:]))
    return feeds


def test_registered_datum_rejects_idle_position_jump_before_sending_motion():
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    control = MotionControl()
    serial.position[:] = [21., 18., -1.6]
    with pytest.raises(ValueError, match="抬笔"):
        link.confirm_datum_position(control)
    serial.position[2] = 0.
    assert link.confirm_datum_position(control).position == (21., 18., 0.)
    serial.position[:] = [0., 0., 0.]  # Same WCO and still inside the software bounds.
    with pytest.raises(MachineError, match="待机期间"):
        link.move_to((30., 25.), WorkArea(-5, -5, 50, 50), control)
    assert not any(cmd.startswith(b"G1") for cmd in serial.commands)


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
    area = WorkArea(0, -20, 85, 100)

    def report(state, xyz):
        pin = "|Pn:Y" if state == "Run" and xyz == "30.0,-15.0,-1.6" else ""
        return f"<{state}|WPos:{xyz}{pin}>"

    serial.report = report
    link.trial_axes(axes, area, 2500, MotionControl(), confirmed_area=area)
    assert any(isinstance(event, str) and "Pn:Y" in event for event in serial.trace)
    assert (link.xy_command((30, -15), 2500) + "\n").encode("ascii") in serial.commands
    assert (link.xy_command((75, 40), 2500) + "\n").encode("ascii") in serial.commands
    serial.report = lambda state, xyz: f"<{state}|WPos:{xyz}>"
    previous = len(serial.commands)
    link.trial_axes(axes, None, 3150, MotionControl())
    feeds = xy_feeds_by_pen(serial.commands[previous:])
    assert set(feeds[False]) == set(feeds[True]) == {3150}


def test_optional_jog_bounds_and_repeated_pin_without_a_range():
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    with pytest.raises(ValueError, match="超出"):
        link.jog((-1, 0), WorkArea(0, 0, 10, 10), MotionControl())
    area = WorkArea(0, 0, 10, 10)
    with pytest.raises(ValueError, match="超出"):
        link.jog((-1, 0), area, MotionControl(), commissioning=True)
    assert not any(line.startswith(b"G1") for line in serial.commands)
    link.jog((-1, 0), None, MotionControl(), commissioning=True, feed=4250)
    assert serial.position == [-1, 0, 0]
    assert b"G1 X-1.0000 Y0.0000 F4250\n" in serial.commands
    serial.report = lambda state, coords: f"<{state}|WPos:{coords}|WCO:0,0,0>" if state != "Run" or coords.startswith("-1") else f"<{state}|WPos:{coords}|WCO:0,0,0|Pn:X>"
    with pytest.raises(MachineError, match="限位"):
        link.jog((-1, 0), None, MotionControl())


@pytest.mark.parametrize("commissioning", [True, False])
def test_range_off_manual_jog_checks_single_pulse_before_sending_more(commissioning):
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    sent_pin = False
    def report(state, xyz):
        nonlocal sent_pin
        if state == "Run" and float(xyz.split(",")[1]) != 0 and not sent_pin:
            sent_pin = True
            return f"<Run|WPos:{xyz}|Pn:Y>"
        return f"<{state}|WPos:{xyz}>"
    serial.report = report
    end = link.jog((0, 10), None, MotionControl(), commissioning=commissioning, feed=2000, range_disabled=True)
    assert sent_pin and end.position == (0, 10, 0)
    commands = [line for line in serial.commands if line.startswith(b"G1 X")]
    assert all(line.endswith(b"F2000\n") for line in commands)
    pulse = next(i for i, event in enumerate(serial.trace) if isinstance(event, str) and "Pn:Y" in event)
    next_move = serial.trace.index(commands[1], pulse)
    assert sum(isinstance(event, str) and event.startswith("<Idle|") for event in serial.trace[pulse:next_move]) == 2
    assert all(len(packet.splitlines()) == 1 for packet in serial.packets if packet.startswith(b"G1 X"))


@pytest.mark.parametrize("signal", ["persistent", "idle", "alarm", "combined", "stalled", "adjacent"])
def test_range_off_manual_jog_stops_on_unverified_signal(signal):
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    seen = set()
    def report(state, xyz):
        if float(xyz.split(",")[1]) != 0:
            if signal == "alarm":
                return "ALARM:1"
            if signal == "stalled":
                return "<Run|WPos:0,0,0|Pn:Y>"
            if signal == "combined":
                return f"<{state}|WPos:{xyz}|Pn:XY>"
            if signal == "persistent" or (signal == "idle" and state == "Idle"):
                return f"<{state}|WPos:{xyz}|Pn:Y>"
            if signal == "adjacent" and state == "Run" and xyz not in seen:
                seen.add(xyz)
                return f"<Run|WPos:{xyz}|Pn:Y>"
        return f"<{state}|WPos:{xyz}>"
    serial.report = report
    with pytest.raises(MachineError):
        link.jog((0, 10), None, MotionControl(), feed=2000, range_disabled=True)
    assert sum(cmd.startswith(b"G1 X") for cmd in serial.commands) == (2 if signal == "adjacent" else 1)


@pytest.mark.parametrize("entry", ["return", "page", "dry"])
def test_range_off_automatic_raised_motion_reviews_only_a_verified_short_segment(entry):
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    page = position_page(page_fixture(), PaperRegistration((0., 0.)))
    seen = []
    def report(state, xyz):
        if state == "Run" and xyz != "0.0,0.0,0.0" and not seen:
            seen.append(xyz)
            return f"<Run|WPos:{xyz}|Pn:X>"
        return f"<{state}|WPos:{xyz}>"
    serial.report = report
    if entry == "return":
        link.move_to((-3.9,-3.9), None, MotionControl(), feed=2000)
    else:
        link.run_page(page, None, MotionControl(), feed=2000, dry_run=entry == "dry")
    assert seen
    pulse = next(i for i, s in enumerate(serial.trace) if isinstance(s,str) and "Pn:X" in s)
    following = next(i for i,s in enumerate(serial.trace[pulse+1:],pulse+1) if isinstance(s,bytes) and s.startswith(b"G1"))
    assert sum(isinstance(s,str) and s.startswith("<Idle|") for s in serial.trace[pulse:following]) >= 2


def test_range_off_ink_contact_remains_strict():
    serial = SimulatedGrbl()
    link = GrblLink(serial)
    link.connect()
    page = position_page(page_fixture(), PaperRegistration((0., 0.)))
    serial.report = lambda state, xyz: (f"<{state}|WPos:{xyz}|Pn:Y>" if state=="Run" and xyz.endswith(",-1.6")
                                        else f"<{state}|WPos:{xyz}>")
    with pytest.raises(MachineError, match="限位"):
        link.run_page(page, None, MotionControl())


@pytest.mark.parametrize("case", ["persist", "boundary", "unknown", "alarm"])
def test_device_jog_does_not_resume_after_unsafe_pin(case):
    serial = SimulatedGrbl()
    if case == "unknown":
        serial.firmware = "[VER:1.1f.20170801:]"
    serial.position[:] = [10., 10., 0.]
    link = GrblLink(serial)
    link.connect()

    def report(state, xyz):
        triggered = xyz == "10.0,13.0,0.0" and (state == "Run" or case == "persist")
        if triggered and case == "alarm":
            return "ALARM:1"
        return f"<{state}|WPos:{xyz}" + ("|Pn:Y>" if triggered else ">")

    serial.report = report
    area = WorkArea(0, 0, 30, 14 if case == "boundary" else 30)
    with pytest.raises(MachineError, match="限位|ALARM|复核"):
        link.jog((0, 3), area, MotionControl(), commissioning=True)
    xy = [line for line in serial.commands if line.startswith(b"G1 X")]
    assert xy == [(link.xy_command((10, 13), 2500) + "\n").encode("ascii")]


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
from test_plotter_machine import SimulatedGrbl, xy_feeds_by_pen
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
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

def reopen(_port):
    transport.closed = False
    return transport

panel = MachinePanel(None, worker_factory=lambda parent: N1Worker(parent, serial_factory=reopen),
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
    assert not setup.use_range.isChecked() and panel.nudge.isEnabled()
    def values(combo):
        return [combo.itemData(i) for i in range(combo.count())]
    def choose(combo, value):
        index = combo.findData(value)
        assert index >= 0
        combo.setCurrentIndex(index)
    assert values(setup.nudge.feed) == [200,500,1000,2000,2500,3500,5000]
    assert values(panel.nudge.step) == [.1,.5,1,2,5,10,20,50,100]
    assert setup.nudge.feed.currentData() == panel.profile.feed == 2500
    assert panel.nudge.step.currentData() == 1
    assert [c for c in setup.findChildren(QtWidgets.QComboBox) if c.accessibleName()=="运动速度"] == [setup.nudge.feed]
    from dataclasses import replace
    before = list(transport.commands)
    panel.save_profile(replace(panel.profile, feed=1800))
    assert panel.nudge.feed.currentText() == setup.nudge.feed.currentText() == "1800 mm/min（当前值）"
    assert panel.store.devices()[0].feed == 1800
    choose(panel.nudge.feed, 2500)
    assert setup.nudge.feed.currentData() == 2500 and setup.nudge.feed.findData(1800) == -1
    assert transport.commands == before
    ordinary_report = transport.report
    pulses = []
    def one_pulse(state, xyz):
        if not pulses and state == "Run" and float(xyz.split(",")[1]) > 30:
            pulses.append(xyz)
            return f"<Run|WPos:{xyz}|WCO:0,0,0|Pn:Y>"
        return ordinary_report(state, xyz)
    transport.report = one_pulse
    choose(panel.nudge.step, 10)
    panel.nudge.buttons[(0, 1)].click()
    wait()
    assert pulses and panel.device is not None and panel.nudge.isEnabled()
    assert transport.position == [35., 40., 0.] and "点动完成" in panel.report.text()
    transport.report = ordinary_report
    panel.nudge.buttons[(0, -1)].click()
    wait()
    assert transport.position == [35., 30., 0.]
    choose(panel.nudge.step, 50)
    panel.nudge.buttons[(1, 0)].click()
    wait()
    assert transport.position == [85., 30., 0.]
    panel.nudge.buttons[(-1, 0)].click()
    wait()
    assert transport.position == [35., 30., 0.]
    assert set(xy_feeds_by_pen(transport.commands)[False]) == {2500}
    choose(setup.nudge.feed, 200)
    setup.axes[0].setChecked(True)
    setup.axes[2].setChecked(True)
    choose(setup.nudge.step, 50)
    before = len(transport.commands)
    setup.nudge.buttons[(1, 0)].click()
    assert isinstance(setup.stop.parentWidget(), QtWidgets.QDialogButtonBox)
    assert not setup.stop.isHidden()
    wait()
    assert transport.position == [35., -20., 0.] and not panel.profile.axes.swap
    assert b"G1 X35.0000 Y-20.0000 F200\n" in transport.commands
    assert set(xy_feeds_by_pen(transport.commands[before:])[False]) == {200}
    assert panel.store.devices()[0].feed == panel.nudge.feed.currentData() == 200
    choose(setup.nudge.step, 50)
    setup.nudge.buttons[(-1, 0)].click()
    wait()
    choose(setup.nudge.step, 1)
    setup.nudge.buttons[(1, 0)].click()
    wait()
    assert transport.position == [35., 29., 0.]
    assert not any(command.startswith(b"G1 Z-") for command in transport.commands)
    setup.use_range.setChecked(True)
    setup.record_buttons[0].click()
    wait()
    assert [spin.value() for spin in setup.bounds[:2]] == [35., 29.]
    for spin, value in zip(setup.bounds, (0, 0, 100, 100), strict=True):
        spin.setValue(value)
    setup.save_button.click()
    profile = panel.store.devices()[0]
    assert profile.axes.swap and profile.axes.mirror_x and panel.confirmed_area == profile.area
    assert profile.limit_area_enabled and profile.feed == 200
    normal_report = transport.report
    transport.report = lambda state, xyz: (
        "<Run|WPos:35,28.0,0|Pn:Y>" if state == "Run" and xyz == "35.0,27.0,0.0"
        else normal_report(state, xyz)
    )
    choose(setup.nudge.step, 2)
    setup.nudge.buttons[(1, 0)].click()
    wait()
    assert transport.position == [35., 27., 0.] and panel.device is not None
    assert "点动完成" in panel.report.text()
    assert b"G1 X35.0000 Y27.0000 F200\n" in transport.commands
    assert not transport.closed and b"\x18" not in transport.commands
    transport.report = normal_report
    setup.nudge.buttons[(-1, 0)].click()
    wait()
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
    assert panel.write_button.isEnabled()
    panel.confirm = lambda *_: True
    reuse = AlignmentDialog(panel, panel, *context, snapshot=snapshot)
    reuse.recall.click()
    assert reuse.result() and reuse.position == align.position
    panel.write_button.click()
    wait()
    assert "书写完成" in panel.report.text()

    preview = AlignmentDialog(panel, panel, *context, configure=True)
    preview.show()
    app.processEvents()
    canvas = preview.canvas
    qt = QtCore.Qt
    initial = canvas.drawing_transform()
    anchor = initial.map(QtCore.QPointF(22, 19)).toPoint()
    def wheel(modifier):
        event = QtGui.QWheelEvent(QtCore.QPointF(anchor), QtCore.QPointF(canvas.mapToGlobal(anchor)),
            QtCore.QPoint(), QtCore.QPoint(0, 240), qt.NoButton, modifier, qt.NoScrollPhase, False)
        app.sendEvent(canvas, event)
    wheel(qt.NoModifier)
    assert canvas.drawing_transform() == initial
    wheel(qt.ControlModifier)
    assert preview.zoom_reset.text() == "144%"
    point = initial.inverted()[0].map(QtCore.QPointF(anchor))
    assert (canvas.drawing_transform().map(point) - anchor).manhattanLength() < 1e-6
    QtTest.QTest.mouseClick(canvas, qt.LeftButton, pos=anchor)
    assert abs(preview.a[0].value() - point.x()) < .001 and abs(preview.a[1].value() - point.y()) < .001
    preview.pick.setCurrentIndex(1)
    dest = anchor + QtCore.QPoint(30, 20)
    QtTest.QTest.mousePress(canvas, qt.LeftButton, pos=anchor)
    QtTest.QTest.mouseMove(canvas, dest)
    QtTest.QTest.mouseRelease(canvas, qt.LeftButton, pos=dest)
    assert not preview.use_b.isChecked()
    assert (canvas.drawing_transform().map(point) - dest).manhattanLength() < 1e-6
    b_pixel = dest + QtCore.QPoint(12, 18)
    b_mm = canvas.drawing_transform().inverted()[0].map(QtCore.QPointF(b_pixel))
    QtTest.QTest.mouseClick(canvas, qt.LeftButton, pos=b_pixel)
    assert preview.use_b.isChecked()
    assert abs(preview.b[0].value() - b_mm.x()) < .001 and abs(preview.b[1].value() - b_mm.y()) < .001
    preview.zoom_reset.click()
    assert canvas.drawing_transform() == initial and preview.zoom_reset.text() == "100%"
    preview.close()

    measure = AlignmentDialog(panel, panel, *context, configure=True)
    transport.position[:] = [35., 29., 0.]
    measure.record_a.click()
    wait()
    measure.use_b.setChecked(True)
    measure.b[0].setValue(15)
    measure.show()
    app.processEvents()
    assert measure.nudge.isVisible() and measure.nudge.isEnabled()
    before = len(transport.commands)
    choose(measure.nudge.step, 100)
    measure.nudge.buttons[(1, 0)].click()
    assert "超出" in measure.motion_error.text() and len(transport.commands) == before
    before_speed = list(transport.commands)
    choose(measure.nudge.feed, 500)
    assert panel.nudge.feed.currentData() == 500 and measure.measurement == (35.,29.)
    assert transport.commands == before_speed
    choose(measure.nudge.feed, 200)
    choose(measure.nudge.step, 10)
    measure.nudge.buttons[(1, 0)].click()
    wait()
    choose(measure.nudge.step, 2)
    measure.nudge.buttons[(1, 0)].click()
    assert panel.busy == "jog" and not measure.nudge.isEnabled() and not measure.record_b.isEnabled()
    assert measure.stop.isVisible() and measure.stop.isEnabled()
    measure.reject()
    assert measure.isVisible()
    wait()
    assert measure.measurement == (35., 29.) and transport.position == [35., 17., 0.]
    assert "Y 17.000" in measure.pen_position.text() and measure.stop.isHidden()
    assert set(xy_feeds_by_pen(transport.commands[before:])[False]) == {200}
    assert not any(cmd.startswith(b"G1 Z-") for cmd in transport.commands[before:])
    measure.record_b.click()
    wait()
    measure.save.click()
    assert measure.result() and measure.alignment.scale == 1.2 and measure.alignment.angle == 0.

    # Rebooting at the current pen position can reset WPos without changing WCO.
    old_connection, old_offset = panel.connection_id, panel.offset
    reopened = DeviceDialog(panel)
    assert reopened.use_range.isChecked() and panel.confirmed_area == profile.area
    reopened.link.click()
    wait()
    assert panel.device is None and panel.connection_id is None
    transport.position[:] = [0., 0., 0.]
    reopened.link.click()
    wait()
    assert panel.device.position[:2] == (0., 0.) and panel.offset == old_offset
    assert panel.connection_id != old_connection
    assert reopened.use_range.isChecked() and panel.confirmed_area is None
    choose(reopened.nudge.feed, 3500)
    reopened.save_button.click()
    assert panel.profile.area == profile.area and panel.confirmed_area is None
    assert panel.profile.feed == 3500 and panel.profile.limit_area_enabled
    reopened.use_range.setChecked(False)
    reopened.save_button.click()
    assert not panel.profile.limit_area_enabled and panel.profile.area == profile.area
    reopened.close()

    page_key, size, _, title = context
    restore = AlignmentDialog(panel, panel, page_key, size, measure.alignment, title, snapshot=snapshot)
    restore.recall.click()
    assert not restore.result() and restore.position is None and not restore.save.isEnabled()
    assert "重新记录实地 A 点" in restore.status.text()
    assert restore.markings().scale == 1.2
    restore.record_a.click()
    wait()
    restore.save.click()
    assert restore.result() and restore.position == (0., 0.) and restore.alignment.scale == 1.2
    panel.use_alignment(restore.alignment, restore.position)
    assert panel.registration and panel.confirmed_area is None and panel.write_button.isEnabled()
    # This transformed character crosses the old rectangle's y=0 boundary.
    assert panel.job.strokes[0].points[-1][1] < 0
    start = len(transport.commands)
    panel.dry_button.click()
    wait()
    assert set(xy_feeds_by_pen(transport.commands[start:])[False]) == {3500}
    assert not xy_feeds_by_pen(transport.commands[start:])[True]
    start = len(transport.commands)
    panel.return_button.click()
    wait()
    assert b"G1 X0.0000 Y0.0000 F3500\n" in transport.commands[start:]
    start = len(transport.commands)
    panel.write_button.click()
    wait()
    feeds = xy_feeds_by_pen(transport.commands[start:])
    assert set(feeds[False]) == set(feeds[True]) == {3500}
    trial = DeviceDialog(panel)
    choose(trial.nudge.feed, 500)
    start = len(transport.commands)
    trial.trial.click()
    wait()
    trial_feeds = xy_feeds_by_pen(transport.commands[start:])
    assert set(trial_feeds[False]) == set(trial_feeds[True]) == {500}
    trial.close()
    panel.link_button.click()
    wait()
    panel.set_workspace(Path(sys.argv[1]))
    saved = DeviceDialog(panel)
    assert saved.nudge.feed.currentData() == 500 and saved.nudge.feed.isEnabled() and not saved.nudge.step.isEnabled() and not saved.trial.isEnabled()
    assert not saved.use_range.isChecked()
    saved.close()
    panel.link_button.click()
    wait()
    transport.report = lambda state, xyz: f"<{state}|WPos:{xyz}|Pn:Y>"
    panel.nudge.buttons[(0, 1)].click()
    wait()
    assert panel.device is None and "plotter-last-jog-fault.json" in panel.report.text()
    import json
    fault = json.loads((Path(sys.argv[1]) / "plotter-last-jog-fault.json").read_bytes())
    assert fault["operation"] == "jog" and "|Pn:Y>" in fault["reports_before_stop"][-1]
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


@pytest.mark.parametrize("area", [None, WorkArea(0, 0, 100, 100)])
@pytest.mark.parametrize("dry_run", [True, False])
def test_ack_is_not_completion_and_dry_run_traverses_the_exact_written_path(dry_run, area):
    placed = position_page(page_fixture(), PaperRegistration((10, 20)))
    progress = []
    serial = SimulatedGrbl()
    serial.position[:] = [10, 20, 0]
    link = GrblLink(serial, progress=lambda n, total: progress.append((n, total)))
    link.connect()
    state = link.run_page(placed, area, MotionControl(), dry_run=dry_run, feed=900)
    xy = [command.decode().split()[1:3] for command in serial.commands if command.startswith(b"G1 X")]
    expected = [point for stroke in placed.strokes for point in stroke.points]
    if area is not None:
        assert xy == [[f"X{x:.4f}", f"Y{y:.4f}"] for x, y in expected]
    else:
        previous = (10.,20.)
        for words in xy:
            target = expected[0]
            current = tuple(float(word[1:]) for word in words)
            assert math.dist(previous,current)+math.dist(current,target) == pytest.approx(math.dist(previous,target),abs=.001)
            if current == target:
                expected.pop(0)
            previous = current
        assert not expected
    assert serial.commands.count(b"G1 Z-1.6 F5000\n") == (0 if dry_run else 2)
    feeds = xy_feeds_by_pen(serial.commands)
    assert set(feeds[False]) == {900} and set(feeds[True]) == (set() if dry_run else {900})
    actual_motion = [command for command in serial.commands if command.startswith(b"G1 ")]
    assert actual_motion[0] == actual_motion[-1] == b"G1 Z0 F5000\n"
    assert progress == [(1, 2), (2, 2)]
    final_xy = (link.xy_command((19, 29), 900) + "\n").encode("ascii")
    after_xy = serial.trace[serial.trace.index(final_xy):]
    tail = after_xy[after_xy.index(actual_motion[-1]):]
    assert any(str(value).startswith("<Run") for value in after_xy)
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
from inkstruct.editor.machine_devices import DeviceDialog
from inkstruct.editor.machine_panel import MachinePanel
from inkstruct.plotter.physical import WorkArea
from inkstruct.plotter.profiles import DeviceAxes, DeviceProfile, PageAlignment
from inkstruct.plotter.qt_connection import N1Worker
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp

app = QtWidgets.QApplication([])
transport = SimulatedGrbl()
transport.position[:] = [20., 20., 0.]
page = Page(index=0, fragments=(), paint_ops=(PaintOp("one", ((3.,4.), (5.,6.)), .3),))
snapshot = LayoutSnapshot("snapshot", "key", "document", 0, PageProfile(70, 60, 5),
                          (page,), (), "resource", "test")
worker = lambda parent: N1Worker(parent, serial_factory=lambda _port: transport)
ports = lambda: [SimpleNamespace(portName=lambda: "COM-test")]
dialog = MachinePanel(None, worker_factory=worker, ports=ports)
dialog.set_workspace(Path(sys.argv[1]))
profile = DeviceProfile("device", "N1", "COM-test", axes=DeviceAxes(mirror_x=True, swap=True),
                        area=WorkArea(0, 0, 100, 100), limit_area_enabled=True)
dialog.save_profile(profile)
dialog.set_document(snapshot, 0, True)
dialog.show()
try:
    assert not any("手动对位" in button.text() for button in dialog.findChildren(QtWidgets.QAbstractButton))
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
    assert dialog.nudge.isEnabled() and dialog.confirmed_area is None
    assert dialog.confirm_range_button.isVisible()
    dialog.use_alignment(PageAlignment((2, 3)), (20., 20.))
    assert dialog.job and not dialog.dry_button.isEnabled() and not dialog.write_button.isEnabled()
    assert not dialog.return_button.isEnabled()
    settings = DeviceDialog(dialog)
    assert settings.use_range.isChecked()
    settings.range_confirm.click()
    assert dialog.nudge.isEnabled() and dialog.confirmed_area == profile.area
    settings.close()
    dialog.nudge.step.setCurrentIndex(dialog.nudge.step.findData(2))
    dialog.nudge.buttons[(1, 0)].click()
    assert not dialog.nudge.isEnabled() and dialog.stop_button.isVisible()
    wait_for(lambda: dialog.busy is None)
    assert transport.position == [20., 18., 0.]
    dialog.use_alignment(PageAlignment((2, 3)), (20, 18))
    placed = dialog.job
    dialog.preview_button.click()
    assert dialog.preview.job is placed and placed.strokes[0].points == ((21., 17.), (23., 15.))
    assert dialog.dry_button.isEnabled() and dialog.write_button.isEnabled()
    assert not any(command.startswith(b"G1 Z-") for command in transport.commands)
    dialog.confirm = lambda *_: True
    dialog.write_button.click()
    wait_for(lambda: "书写完成" in dialog.report.text() and dialog.busy is None)
    assert b"G1 Z-1.6 F5000\n" in transport.commands
    assert dialog.write_button.isEnabled()

    dialog.return_button.click()
    wait_for(lambda: dialog.busy is None)
    assert transport.position == [20., 18., 0.]

    transport.fail_next_motion = True
    dialog.dry_button.click()
    wait_for(lambda: dialog.device is None and dialog.busy is None)
    assert dialog.registration is None and dialog.confirmed_area is None
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
from inkstruct.plotter.physical import WorkArea
from inkstruct.plotter.profiles import DeviceProfile, PageAlignment
from inkstruct.plotter.qt_connection import N1Worker
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp

app = QtWidgets.QApplication([])
settings = QtCore.QSettings
settings.setDefaultFormat(settings.Format.IniFormat)
settings.setPath(settings.Format.IniFormat, settings.Scope.UserScope, sys.argv[1])
transport = SimulatedGrbl()
transport.position[2] = -1.6
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
p.set_workspace(Path(sys.argv[1]))
profile = DeviceProfile("device", "N1", "COM-test", area=WorkArea(0, 0, 100, 100),
                        limit_area_enabled=True)
p.save_profile(profile)
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
    w.machine_dock.raise_()
    wait_for(lambda: p.page_list.count() == 2)
    # The dock resizes its scroll contents to fill the viewport. Its spare
    # height must never change the spacing between the directional buttons.
    for height in (620, 1080):
        w.resize(1350, height)
        app.processEvents()
        up, left, right, down = (p.nudge.buttons[direction].geometry()
                                 for direction in ((0, -1), (-1, 0), (1, 0), (0, 1)))
        horizontal_step = up.x() - left.x()
        assert horizontal_step == right.x() - up.x()
        assert left.y() - up.y() == horizontal_step, (height, up, left, down)
        assert down.y() - left.y() == horizontal_step
        assert p.nudge.rect().contains(down)
    w.resize(1350, 840)
    app.processEvents()
    before = w.workspace_views.splitter.sizes()
    p.page_list.setCurrentRow(1)
    assert w.page_picker.value() == 2 and p.paper_page.index == 1
    p.scope.setCurrentIndex(p.scope.findData("all"))
    assert p.paper_page.index == 0 and not p.page_list.isEnabled()
    p.link_button.click()
    wait_for(lambda: p.device is not None and p.busy is None)
    assert p.nudge.isEnabled() and p.confirmed_area is None and not p.write_button.isEnabled()
    p.save_profile(profile, confirm_range=True)
    p.confirm = lambda *_: True
    assert p.pen_button.isVisible() and not p.pen_raised and not p.link_button.isEnabled()
    p.pen_button.click()
    wait_for(lambda: p.pen_raised and p.busy is None)
    assert p.pen_button.isVisible() and p.pen_button.text() == "落笔"
    p.use_alignment(PageAlignment((0, 0)), transport.position[:2])
    p.dry_button.click()
    wait_for(lambda: "抬笔试走完成" in p.report.text() and p.busy is None)

    p.write_button.click()
    assert p.is_moving and p.close_blocker()
    p.write_button.click()
    wait_for(lambda: b"!" in transport.commands)
    assert not w.close() and app.activeModalWidget() is None
    assert p.busy == "write" and p.stop_button.isEnabled()
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
    p.use_alignment(PageAlignment((0, 0)), transport.position[:2])
    p.dry_button.click()
    wait_for(lambda: "抬笔试走完成" in p.report.text() and p.busy is None)
    p.write_button.click()
    wait_for(lambda: not p.batch_active and p.busy is None)
    assert p.completed_pages == {0, 1} and not p.close_blocker()

    p.scope.setCurrentIndex(p.scope.findData("single"))
    p.dry_button.click()
    wait_for(lambda: "抬笔试走完成" in p.report.text() and p.busy is None)
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

def test_confirmed_page_region_reviews_recorded_writing_signal():
    from inkstruct.plotter.grbl import XYWindow
    from inkstruct.plotter.physical import MachinePage, MachineStroke

    points = ((8.35, 2.94), (8.58, 3.29), (8.52, 4.87), (8.56, 5.03))
    page = MachinePage(3, (MachineStroke("6", points, .25),), PaperRegistration((0, 0)))
    start = (9.32, 3.93)
    area = page.clearance_box(start, 2.)
    assert all(area.contains(p, inset=2.) for p in (*points, start))
    reports = ["<Run|WPos:8.580,3.290,-1.590,0.000|Bf:0,1023|FS:3451,0>",
               "<Run|WPos:8.520,4.870,-1.590,0.000|Bf:6,1023|FS:1191,0|Pn:Y|Ov:100,100,100>"]
    for confirmed in (False, True):
        window = XYWindow(area if confirmed else None, -1.59, [points[0]])
        window.arm(points[1:])
        window.observe(decode_status(reports[0]), True)
        if confirmed:
            window.observe(decode_status(reports[1]), True)
            assert window.pin == "Y"
        else:
            with pytest.raises(MachineError, match="Pn:Y"):
                window.observe(decode_status(reports[1]), True)
