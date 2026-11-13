"""Exercise the pen-event path and the pressure-sensitive canvas cache."""

import os
import subprocess
import sys


def test_motion_preserves_ink_without_refreshing_task_state():
    program = r"""
from PySide6 import QtCore, QtGui, QtWidgets
from handwriting_collector.canvas import TrajectoryCanvas

app = QtWidgets.QApplication([])
canvas = TrajectoryCanvas(show_grid=True)
canvas.resize(440, 300)
canvas.show()
app.processEvents()
qt = QtCore.Qt
event = QtCore.QEvent.Type
device = QtGui.QPointingDevice.primaryPointingDevice()
notices = []
canvas.trajectory_changed.connect(lambda: notices.append(canvas.trajectory.point_count))

def tablet(kind, x, y, pressure):
    position = QtCore.QPointF(x, y)
    button = qt.MouseButton.NoButton if kind == event.TabletMove else qt.MouseButton.LeftButton
    down = qt.MouseButton.NoButton if kind == event.TabletRelease else qt.MouseButton.LeftButton
    sample = QtGui.QTabletEvent(kind, device, position, position, pressure, 0, 0, 0, 0, 0,
                                qt.KeyboardModifier.NoModifier, button, down)
    QtWidgets.QApplication.sendEvent(canvas, sample)
    assert sample.isAccepted()
    app.processEvents()

def render():
    return canvas.grab().toImage()

def pixel(image, x, y):
    dpr = image.devicePixelRatio()
    return image.pixelColor(round(x * dpr), round(y * dpr))

blank = render()
tablet(event.TabletPress, 65, 55, .4)
tablet(event.TabletMove, 135, 55, .6)
assert pixel(render(), 100, 55) != pixel(blank, 100, 55)
tablet(event.TabletMove, 160, 90, .8)
assert notices == [1] and canvas.pen_down
tablet(event.TabletRelease, 180, 110, 0)
stroke, = canvas.trajectory.strokes
assert notices == [1, 4] and not canvas.pen_down
assert [(p.x, p.y, p.pressure) for p in stroke.points] == [
    (65, 55, .4), (135, 55, .6), (160, 90, .8), (180, 110, 0)
]
assert [p.t_ms for p in stroke.points] == sorted(p.t_ms for p in stroke.points)
ink = render()
assert pixel(ink, 175, 105) != pixel(blank, 175, 105)

# A fresh paint from the same source data matches the incremental result.
copy = TrajectoryCanvas(show_grid=True)
copy.resize(canvas.size())
copy.trajectory = canvas.trajectory
assert copy.grab().toImage() == ink

tablet(event.TabletPress, 70, 145, .4)
assert render() != ink
canvas.undo_last_stroke()
assert render() == ink

canvas.set_render_settings(4.0, .72)
thick = render()
assert pixel(thick, 100, 60) != pixel(ink, 100, 60)
palette = canvas.palette()
palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#222222"))
palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor("#eeeeee"))
canvas.setPalette(palette)
assert pixel(render(), 100, 55).lightness() > 200
canvas.resize(460, 320)
assert pixel(render(), 100, 55).lightness() > 200
canvas.clear()
assert pixel(render(), 100, 55).lightness() < 60
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "1.5"},
        capture_output=True, text=True, encoding="utf-8", timeout=25, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
