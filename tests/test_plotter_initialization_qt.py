"""Exercise commissioning through the modal Windows/Qt device-management controls."""
import os
from time import monotonic, sleep
from types import SimpleNamespace


def test_guided_initialization_and_exclusive_axis_trial(tmp_path):
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
    def connect(_port):
        controller.closed = False
        return controller

    panel = MachinePanel(None, worker_factory=lambda parent: N1Worker(parent, serial_factory=connect),
                         ports=lambda: [port])
    panel.set_workspace(tmp_path)
    panel.save_profile(DeviceProfile.create("模拟 N1", "SIM", "wizard"))
    panel.confirm = lambda *_: True
    manager = DeviceDialog(panel)
    manager.show()

    def wait():
        end = monotonic() + 12
        while panel.busy and monotonic() < end:
            app.processEvents()
            sleep(.002)
        assert panel.busy is None, panel.report.text()
        app.processEvents()

    def visit(interact):
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
        manager.datum_register.click()
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
        w.advance.click()
        wait()
        assert "第 2 步" in w.heading.text() and not w.nudge.isVisible()
        for n in (1, 2, 3):
            assert f"{n} / 3" in w.instructions.text()
            assert not w.advance.isEnabled() and not w.trial_button.isVisible()
            no_trial()
            w.link.click()
            wait()
            assert panel.device is None and not w.advance.isEnabled()
            w.link.click()
            wait()
            assert w.advance.isEnabled()
            w.advance.click()
            wait()
        assert "第 3 步" in w.heading.text() and w.trial_button.isVisible()
        assert not w.advance.isEnabled()
        w.axes[0].setChecked(True)
        w.axes[2].setChecked(True)
        w.nudge.buttons[(1, 0)].click()
        wait()
        assert controller.position[:2] == [0, -1]
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
        assert datum.restart_positions == ((0, 0),) * 4 and "重新初始化" in manager.datum_register.text()
        visit(lambda w: w.cancel.click())
        assert panel.datum_located and panel.profile.datum == datum
        def cancel_restart(w):
            w.advance.click()
            wait()
            assert panel.dock_trial is not None
            w.close()
        visit(cancel_restart)
        assert panel.dock_trial is None and not panel.datum_located
        assert panel.store.devices()[0].datum == datum
        no_trial()
    finally:
        manager.close()
        panel.shutdown()
        panel.close()
