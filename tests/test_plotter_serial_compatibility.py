"""Replay the same controller reports with different firmware identities."""
from dataclasses import replace
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from inkstruct.plotter import grbl
from inkstruct.plotter.docking import idle_checkpoint, idle_xy, restored_frame
from inkstruct.plotter.grbl import GrblLink, MachineError, MotionControl
from inkstruct.plotter.physical import PaperRegistration, WorkArea, position_page
from inkstruct.plotter.profiles import DeviceDatum, DeviceProfile
from test_plotter_machine import SimulatedGrbl, page_fixture


FIRMWARE = ("[VER:1.1f / CX-Elite V2.1.003:]", "[VER:1.1h.20190825:]", "[VER:unknown:]")


def test_open_selected_port_reports_access_failure(monkeypatch):
    from inkstruct.plotter import qt_connection as qt

    available = [SimpleNamespace(portName=lambda: "COM8", serialNumber=lambda: "")]
    monkeypatch.setattr(qt.QtSerialPort.QSerialPortInfo, "availablePorts", lambda: available)
    opened = []
    class BusyPort(qt.QtSerialPort.QSerialPort):
        def __init__(self, info):
            super().__init__()
            opened.append(info.portName())

        def open(self, mode):
            return False

        def error(self):
            return self.SerialPortError.PermissionError

    monkeypatch.setattr(qt.QtSerialPort, "QSerialPort", BusyPort)
    with pytest.raises(OSError, match="找不到所选串口 COM7"):
        qt.N1Serial("COM7")
    with pytest.raises(OSError, match="COM8 被占用或无访问权限"):
        qt.N1Serial("COM8")
    assert opened == ["COM8"]


def test_no_grbl_and_incompatible_pen_have_distinct_diagnostics():
    serial = SimulatedGrbl()
    serial.report = lambda *_: ""
    with pytest.raises(grbl.StatusTimeout, match="未返回 Grbl 状态"):
        GrblLink(serial).connect()
    assert set(serial.commands) == {b"?"}
    serial.report = lambda *_: "<Idle|MPos:1,2>"
    with pytest.raises(MachineError, match="笔控需要支持 Z 轴"):
        GrblLink(serial).connect()
    serial.report = lambda state, xyz: f"<{state}|WPos:{xyz}|WCO:0,0,0>"
    link = GrblLink(serial)
    link.connect()
    def reject_pen(line):
        if line.startswith(b"G1 Z"):
            serial.responses.clear()
            serial.responses.append("error:20")
    serial.on_write = reject_pen
    with pytest.raises(MachineError, match="设备拒绝 Z 轴升降笔指令.*error:20"):
        link.set_pen(True, None, MotionControl())
    assert not any(line.startswith(b"G1 X") for line in serial.commands)


@pytest.mark.parametrize("alarm", [False, True])
def test_same_motion_commands_across_firmware(alarm):
    traces = []
    for firmware in FIRMWARE:
        serial = SimulatedGrbl()
        serial.firmware = firmware
        def report(state, xyz):
            if alarm and state == "Run":
                return "ALARM:1"
            return f"<{state}|WPos:{xyz}|WCO:0,0,0|Pn:XYZPDHRS>"
        serial.report = report
        link, control = GrblLink(serial), MotionControl()
        idle_xy(link.connect())
        area = WorkArea(0, 0, 40, 40)
        page = position_page(page_fixture(), PaperRegistration((0, 0)))
        if alarm:
            with pytest.raises(MachineError, match="ALARM:1"):
                link.run_page(page, area, control)
            assert not any(line.startswith(b"G1 Z-") for line in serial.commands)
        else:
            link.jog((1, 0), area, control)
            link.run_page(page, area, control, dry_run=True)
            link.run_page(page, area, control)
            end = link.move_to((0, 0), area, control)
            assert idle_xy(link.verify_rest(control, end)) == (0, 0)
            assert any(line.startswith(b"G1 Z-") for line in serial.commands)
        traces.append([line for line in serial.commands if line != b"?"])
    assert traces[0] == traces[1] == traces[2]


@pytest.mark.parametrize("limit,area_verified,segment_travel,count", [
    ("$21=0", False, True, 4), ("$21=1", False, True, 1),
    ("$21=0", True, True, 1), ("$21=0", False, False, 1), ("", False, True, 4),
])
def test_raised_travel_depends_on_settings_and_operation(limit, area_verified, segment_travel, count):
    traces = []
    for firmware in FIRMWARE:
        serial = SimulatedGrbl()
        serial.firmware, serial.hard_limits = firmware, limit
        link = GrblLink(serial)
        end = link.move_path(link.connect(), [(3, 0)], WorkArea(0, 0, 10, 10) if area_verified else None,
                             2500, 0, MotionControl(), segment_travel=segment_travel)
        assert idle_xy(end) == (3, 0)
        traces.append([line for line in serial.commands if line.startswith(b"G1 X")])
    assert len(traces[0]) == count
    assert traces[0] == traces[1] == traces[2]


@pytest.mark.parametrize("offset", ["0,0,0", None, "0,1,0"])
def test_connection_waits_for_offset_and_checks_saved_identity(monkeypatch, offset):
    monkeypatch.setattr(grbl, "WCO_WAIT_SECONDS", .25)
    profile = DeviceProfile.create("Plotter", "COM9", "serial")
    profile = replace(profile, datum=replace(DeviceDatum.create(profile, "停靠点"), boot_mode="retained"))
    proof = idle_checkpoint(profile, (-60, -60), grbl.decode_status("<Idle|WPos:20,35,0|WCO:0,0,0>"))
    for firmware in FIRMWARE:
        serial = SimulatedGrbl()
        serial.firmware = firmware
        serial.position[:] = (20, 35, 0)
        def report(state, xyz):
            wco = f"|WCO:{offset}" if offset and serial.commands.count(b"?") == 4 else ""
            return f"<{state}|WPos:{xyz}|Pn:XY{wco}>"
        serial.report = report
        link = GrblLink(serial)
        first = link.connect()
        fresh = link.require_idle()
        assert fresh.position == first.position and fresh.offset == first.offset
        assert restored_frame(profile, proof, fresh) == ((-60, -60) if offset == "0,0,0" else None)
        assert restored_frame(replace(profile, serial="another"), proof, fresh) is None
        assert not any(cmd.startswith(b"G1") for cmd in serial.commands)


def test_add_and_refresh_unidentified_port_only_opens_explicit_selection(tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from inkstruct.editor.machine_devices import DeviceDialog
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.plotter import qt_connection

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    available, opened, confirmed = [], [], []
    monkeypatch.setattr(qt_connection.QtSerialPort.QSerialPortInfo, "availablePorts", lambda: list(available))
    def open_serial(name):
        opened.append(name)
        return SimulatedGrbl()
    panel = MachinePanel(None, worker_factory=lambda p: qt_connection.N1Worker(p, serial_factory=open_serial))
    panel.set_workspace(tmp_path)
    settings = DeviceDialog(panel)
    def choose(dialog):
        ok = dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        assert not ok.isEnabled()
        available.append(SimpleNamespace(portName=lambda: "COM9", description=lambda: "Legacy UART", serialNumber=lambda: ""))
        next(b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == "刷新").click()
        assert not ok.isEnabled()
        entry = dialog.ports.topLevelItem(1).child(0)
        assert entry.text(0) == "COM9 · Legacy UART"
        dialog.ports.setCurrentItem(entry)
        assert ok.isEnabled() and ok.text() == "添加待识别设备"
        ok.click()
        return dialog.result()
    try:
        monkeypatch.setattr(QtWidgets.QDialog, "exec", choose)
        settings.add_button.click()
        assert panel.profile.port == "COM9" and not opened
        panel.confirm = lambda title, *_: confirmed.append(title) or True
        settings.link.click()
        deadline = monotonic() + 5
        while not panel.device and monotonic() < deadline:
            app.processEvents()
            sleep(.005)
        assert panel.device and opened == ["COM9"] and "核对设备" in confirmed
        available[0].serialNumber = lambda: "new-device"
        panel.refresh_ports()
        assert panel.available_port() is None
    finally:
        panel.shutdown()
        settings.close()
        panel.close()


def test_serial_port_groups_and_refresh_preserve_explicit_choice(tmp_path):
    from PySide6 import QtCore, QtWidgets
    from inkstruct.editor.machine_devices import AddDeviceDialog
    from inkstruct.editor.machine_panel import MachinePanel

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def port(name, description, vid=0, pid=0):
        return SimpleNamespace(portName=lambda: name, description=lambda: description,
                               vendorIdentifier=lambda: vid, productIdentifier=lambda: pid,
                               serialNumber=lambda: "")
    ports = [port("COM1", "通信端口"), port("COM9", "USB UART", 1, 2),
             port("COM3", "USB 串行设备", 0x28E9, 0x018A)]
    panel = MachinePanel(None, ports=lambda: list(ports))
    panel.set_workspace(tmp_path)
    dialog = AddDeviceDialog(panel, panel)
    try:
        groups = [dialog.ports.topLevelItem(i) for i in range(3)]
        assert [g.text(0) for g in groups] == ["已识别的写字机", "待识别设备", "其他串口"]
        assert dialog.profile().name == "炽写 N1" and dialog.profile().port == "COM3"
        assert not groups[2].child(0).flags() & QtCore.Qt.ItemFlag.ItemIsEnabled
        dialog.ports.setCurrentItem(groups[1].child(0))
        dialog.name.setText("备用机")
        dialog.refresh_ports()
        assert dialog.profile().port == "COM9" and dialog.profile().name == "备用机"
        ports[:] = ports[:1]
        dialog.refresh_ports()
        assert not dialog.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled()
    finally:
        dialog.close()
        panel.shutdown()


def test_manage_selected_profile_without_changing_other_bindings(tmp_path, monkeypatch):
    from PySide6 import QtWidgets
    from inkstruct.editor.machine_devices import DeviceDialog
    from inkstruct.editor.machine_panel import MachinePanel

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = MachinePanel(None, ports=lambda: [])
    panel.set_workspace(tmp_path)
    first = DeviceProfile.create("炽写 N1", "COM3", "unit")
    extra = DeviceProfile.create("写字机", "COM1")
    for profile in (first, extra):
        panel.save_profile(profile)
        panel.store.import_marks(profile, {"page": (2., 3.)})
        panel.store.exchange_checkpoint(profile, {"xy": [4., 5.]})
    dialog = DeviceDialog(panel)
    try:
        initial = panel.store.read()
        monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("误加端口", True))
        dialog.rename_button.click()
        renamed = panel.store.read()
        assert renamed["devices"][extra.id].pop("name") == "误加端口"
        initial["devices"][extra.id].pop("name")
        assert renamed == initial
        panel.confirm = lambda *_: False
        dialog.remove_button.click()
        assert panel.profile.name == "误加端口" and len(panel.profiles) == 2
        panel.confirm = lambda *_: True
        dialog.remove_button.click()
        remaining = panel.store.read()
        assert panel.profile == first and dialog.devices.count() == 1
        for section in ("devices", "paper_marks", "reconnect_positions"):
            assert remaining[section] == {first.id: initial[section][first.id]}
        assert remaining["selected"] == first.id
        dialog.remove_button.click()
        assert not panel.store.devices() and panel.profile is None
        assert not dialog.remove_button.isEnabled() and not dialog.rename_button.isEnabled()
    finally:
        dialog.close()
        panel.shutdown()
