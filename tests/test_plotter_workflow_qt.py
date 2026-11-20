"""Use the normal Qt dialogs, worker and device queue with a simulated USB transport."""
import os
from pathlib import Path
from subprocess import run
import sys


def test_check_point_pen_and_reopened_page(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = run([sys.executable, __file__, str(tmp_path)], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def exercise(folder):
    from time import monotonic, sleep
    from types import SimpleNamespace
    from PySide6 import QtCore, QtTest, QtWidgets
    from inkstruct.editor.machine_alignment import AlignmentDialog
    from inkstruct.editor.machine_panel import MachinePanel
    from inkstruct.editor.pen_calibration import PenCalibration
    from inkstruct.plotter.qt_connection import N1Worker
    from inkstruct.plotter.profiles import DeviceProfile, PageAlignment
    from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp
    from inkstruct.document.schema import PageProfile
    from test_plotter_machine import SimulatedGrbl

    app = QtWidgets.QApplication([])
    mock = SimulatedGrbl()
    snap = LayoutSnapshot("s", "k", "d", 0, PageProfile(70, 60, 5),
        (Page(index=0, fragments=(), paint_ops=tuple(
         PaintOp(f"table:border:{i}", ((x,10.),(x+1,11.)), .25)
         for i,x in enumerate((8., 21., 11., 22., 13., 23., 14., 24.)))),), (), "r", "t")
    def opened():
        p = MachinePanel(None, worker_factory=lambda parent: N1Worker(parent, serial_factory=lambda _: mock),
                         ports=lambda: [SimpleNamespace(portName=lambda:"test")])
        p.set_workspace(folder)
        if not p.profile:
            p.save_profile(DeviceProfile("id","N1","test"))
        p.set_document(snap,0,True)
        p.show()
        p.refresh_ports()
        p.link_button.click()
        wait(p)
        return p
    def wait(p):
        end = monotonic()+20
        while p.busy and monotonic()<end:
            app.processEvents()
            sleep(.003)
        assert p.device and not p.busy, p.report.text()

    p = opened()
    try:
        align = AlignmentDialog(p, p, "pdf", (70.,60.), PageAlignment((5.,5.)), "PDF 第 1 页")
        align.show()
        align.record_a.click()
        wait(p)
        align.check_c.click()
        align.pick_point(30.,25.)
        align.c_move.click()
        wait(p)
        assert mock.position[:2] == [25.,20.]
        align.nudge.step.setCurrentIndex(align.nudge.step.findData(.5))
        align.canvas.setFocus()
        QtTest.QTest.keyClick(align.canvas, QtCore.Qt.Key.Key_Right)
        wait(p)
        align.c_read.click()
        wait(p)
        assert "+0.500" in align.c_result.text(), align.c_result.text()
        align.accept()
        assert align.alignment == PageAlignment((5.,5.))
        p.use_alignment(align.alignment,align.position)

        wizard = PenCalibration(p,p)
        wizard.show()
        wizard.name.setCurrentText("试验笔")
        wizard.height.setValue(-.8)
        wizard.touch.click()
        wait(p)
        assert mock.position[2] == -.8 and wizard.line.isEnabled()
        wizard.line.click()
        wait(p)
        assert mock.position[2] == 0 and wizard.save.isEnabled()
        wizard.save.click()
        assert p.profile.writing_height == -.8
        def accept_checked_region():
            box = app.activeModalWidget()
            assert isinstance(box, QtWidgets.QMessageBox)
            check = box.checkBox()
            assert check is not None and not check.isChecked()
            assert "相对当前笔尖" in box.text()
            check.setChecked(True)
            box.button(QtWidgets.QMessageBox.StandardButton.Yes).click()
        sent_areas = []
        submit = p.worker.submit
        def capture_area(kind, *args):
            if kind == "write":
                sent_areas.append(args[1])
            return submit(kind, *args)
        p.worker.submit = capture_area
        QtCore.QTimer.singleShot(0, accept_checked_region)
        def stop_mid(done,total):
            if done == total//2 - 1:
                p.finish_stroke.click()
        p.worker.progress.connect(stop_mid)
        p.write_button.click()
        wait(p)
        done, pending = p.journal.read()
        assert 3 <= done <= 4 and not pending
        assert p.preview.stroke_state == (done,False)
        assert len(sent_areas) == 1 and sent_areas[0] is not None
        assert p.confirmed_area is None and not p.store.devices()[0].limit_area_enabled
    finally:
        p.shutdown()
        p.close()

    mock = SimulatedGrbl()
    p = opened()
    try:
        assert p.profile.active_pen == "试验笔" and p.profile.writing_height == -.8
        assert p.done == done and "续写" in p.write_button.text()
        assert not p.write_button.isEnabled()
        p.use_alignment(PageAlignment((5.,5.)),(0.,0.))
        p.confirm=lambda *_:True
        p.write_button.click()
        wait(p)
        assert mock.commands.count(b"G1 Z-0.8 F5000\n") == 8-done
        assert not p.journal.path.exists() and p.timing_path.exists()
    finally:
        p.shutdown()
        p.close()


if __name__=="__main__":
    exercise(Path(sys.argv[1]))
