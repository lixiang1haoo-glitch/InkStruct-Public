"""Exercise commissioning through the modal Windows/Qt device-management controls."""
import os
from time import monotonic, sleep
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("mode,unstable", [("zero", False), ("retained", False), ("", False), ("", True)])
def test_guided_initialization_and_exclusive_axis_trial(tmp_path, mode, unstable):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtWidgets
    from inkstruct.editor.machine_devices import DeviceDialog
    from inkstruct.editor.machine_initialization import InitializationDialog
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.plotter.profiles import DeviceProfile
    from inkstruct.plotter.qt_connection import N1Worker
    from test_plotter_machine import SimulatedGrbl

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    port = SimpleNamespace(portName=lambda: "SIM", serialNumber=lambda: "wizard")
    controller = SimulatedGrbl()
    origin = (12., 18.) if mode else (0., 0.)
    controller.position[:2] = origin
    def connect(_port):
        controller.closed = False
        return controller

    panel = MachinePanel(None, worker_factory=lambda parent: N1Worker(parent, serial_factory=connect),
                         ports=lambda: [port])
    panel.set_workspace(tmp_path)
    panel.save_profile(DeviceProfile.create("模拟 N1", "SIM", "wizard"))
    panel.confirm = lambda *_: True
    operations = []
    panel.worker.succeeded.connect(lambda kind, _state: operations.append(kind))
    manager = DeviceDialog(panel)
    manager.show()

    def wait():
        end = monotonic() + 12
        while panel.busy and monotonic() < end:
            app.processEvents()
            sleep(.002)
        assert panel.busy is None, panel.report.text()
        app.processEvents()

    def visit(interact, *, detect=False):
        errors = []
        def drive():
            wizard = app.activeModalWidget()
            try:
                assert isinstance(wizard, InitializationDialog)
                interact(wizard)
            except Exception as error:
                errors.append(error)
                if wizard:
                    wait()
                    wizard.reject()
        QtCore.QTimer.singleShot(0, drive)
        (manager.redetect if detect else manager.datum_register).click()
        if errors:
            raise errors[0]

    def no_trial():
        before = list(controller.commands)
        assert not panel.submit("axis-trial", panel.profile.axes, None, panel.profile.feed, None)
        assert controller.commands == before
        assert all(b.text() != "试画 X/Y" for b in manager.findChildren(QtWidgets.QPushButton)
                   if b.isVisible())

    def commission(w):
        assert w.nudge.isVisible() and not w.trial_button.isVisible()
        w.modes[mode].click()
        operations.clear()
        w.advance.click()
        assert "正在读取" in w.heading.text()
        wait()
        if mode:
            assert operations == ["position-datum"]
            assert panel.dock_trial.mode == mode and panel.dock_trial.origin == origin
            assert "停靠点已确认" in w.heading.text()
        else:
            assert operations == ["position-datum", "disconnect"]
            for n in (1, 2, 3):
                assert f"第 {n} / 3 轮" in w.heading.text()
                assert "保持笔尖不动。请关闭写字机电源，再重新通电。" in w.instructions.text()
                assert w.advance.text() == ("连接、读取并继续校准" if n == 3 else "连接、读取并断开")
                assert w.advance.isEnabled() and not w.nudge.isVisible()
                assert panel.device is None and controller.closed
                operations.clear()
                if unstable and n == 2:
                    original = controller.report
                    reads = 0
                    def drift(state, xyz):
                        nonlocal reads
                        if panel.busy == "position-datum":
                            reads += 1
                            if reads == 2:
                                return original(state, "1,0,0")
                        return original(state, xyz)
                    controller.report = drift
                    w.advance.click()
                    wait()
                    controller.report = original
                    assert operations == ["connect"] and panel.device and not controller.closed
                    assert len(panel.dock_trial.readings) == 1 and w.advance.text() == "重新读取并断开"
                    assert "读取失败" in w.heading.text() and "第 2 / 3 轮" in w.heading.text()
                    assert "尚未稳定" in w.instructions.text()
                w.advance.click()
                wait()
                assert operations == ["connect", "position-datum"] + (["disconnect"] if n < 3 else [])
            assert "检测完成" in w.heading.text() and not controller.closed
        assert w.trial_button.isVisible()
        assert not w.advance.isEnabled()
        w.axes[0].setChecked(True)
        w.axes[2].setChecked(True)
        w.nudge.buttons[(1, 0)].click()
        wait()
        assert controller.position[:2] == [origin[0], origin[1] - 1]
        before = len(controller.commands)
        panel.confirm = lambda *_: False
        w.trial_button.click()
        assert len(controller.commands) == before and not w.advance.isEnabled()
        panel.confirm = lambda *_: True
        w.trial_button.click()
        assert w.stop.isVisible()
        assert not w.close()
        wait()
        assert w.advance.isEnabled() and any(cmd.startswith(b"G1 Z-") for cmd in controller.commands[before:])
        w.advance.click()
        wait()
        assert w.result() == QtWidgets.QDialog.DialogCode.Accepted

    try:
        manager.link.click()
        wait()
        no_trial()
        visit(commission)
        no_trial()
        assert panel.datum_located and panel.profile.axes.swap and panel.profile.axes.mirror_x
        datum = panel.profile.datum
        assert datum.restart_positions == (() if mode else ((0, 0),) * 4)
        assert datum.boot_mode == (mode or "zero") and manager.redetect.isVisible()
        assert panel.frame == origin
        visit(lambda w: w.cancel.click())
        assert panel.datum_located and panel.profile.datum == datum
        def cancel_restart(w):
            assert w.modes[""].isChecked()
            w.advance.click()
            wait()
            assert panel.dock_trial is not None
            w.close()
        visit(cancel_restart, detect=True)
        assert panel.dock_trial is None and not panel.datum_located
        assert panel.store.devices()[0].datum == datum
        no_trial()
    finally:
        manager.close()
        panel.shutdown()
        panel.close()
