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


def test_pointer_modes_own_only_their_active_stroke():
    program = r"""
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from handwriting_collector.canvas import TrajectoryCanvas

app = QtWidgets.QApplication([])
canvas = TrajectoryCanvas()
canvas.resize(400, 300)
canvas.show()
app.processEvents()
qt, event = QtCore.Qt, QtCore.QEvent.Type
p = QtCore.QPoint
left, right = qt.MouseButton.LeftButton, qt.MouseButton.RightButton
none = qt.KeyboardModifier.NoModifier
a, b, c = p(50, 50), p(90, 90), p(140, 100)
hints = []
canvas.input_mismatch.connect(hints.append)

def mouse_stroke():
    QTest.mousePress(canvas, left, none, a)
    QTest.mouseMove(canvas, b)
    QTest.mouseRelease(canvas, left, none, c)

mouse_stroke()
mouse_stroke()
assert not canvas.trajectory.strokes and hints == ["mouse"]
canvas.set_input_mode("mouse")
assert hints == ["mouse", ""]
QTest.mouseClick(canvas, left, none, a)
QTest.mouseClick(canvas, right, none, a)
assert not canvas.trajectory.strokes
mouse_stroke()
stroke, = canvas.trajectory.strokes
assert canvas.trajectory.input_type == "mouse" and not canvas.trajectory.pressure_available
assert [(point.x, point.y) for point in stroke.points] == [(50, 50), (90, 90), (140, 100)]
assert all(point.pressure == 0.5 for point in stroke.points)
QTest.mousePress(canvas, left, none, a)
QTest.mouseRelease(canvas, left, none, p(460, 100))
assert canvas.trajectory.strokes[-1].points[-1].x == 400
canvas.undo_last_stroke()
for cancel in (event.FocusOut, event.WindowDeactivate, event.UngrabMouse):
    QTest.mousePress(canvas, left, none, a)
    QTest.mouseMove(canvas, b)
    interrupted = QtGui.QFocusEvent(cancel) if cancel == event.FocusOut else QtCore.QEvent(cancel)
    app.sendEvent(canvas, interrupted)
    assert canvas.trajectory.strokes == [stroke] and not canvas.pen_down
    QTest.mouseRelease(canvas, left, none, c)
    assert canvas.trajectory.strokes == [stroke]
QTest.mousePress(canvas, left, none, a)
lost_button = QtGui.QMouseEvent(event.MouseMove, b, b, qt.MouseButton.NoButton,
                               qt.MouseButton.NoButton, none)
app.sendEvent(canvas, lost_button)
assert canvas.trajectory.strokes == [stroke] and not canvas.pen_down
QTest.mouseRelease(canvas, left, none, c)

canvas.clear()
device = QTest.createTouchDevice(QtGui.QInputDevice.DeviceType.TouchScreen)
def touches():
    return QTest.touchEvent(canvas, device)

touches().press(0, a, canvas).commit()
touches().release(0, c, canvas).commit()
assert not canvas.trajectory.strokes and hints[-1] == "finger"
canvas.set_input_mode("finger")
mouse_stroke()
assert not canvas.trajectory.strokes and hints[-2:] == ["", "mouse"]
touches().press(0, a, canvas).commit()
assert canvas.pen_down and hints[-1] == ""
touches().move(0, b, canvas).press(1, p(250, 90), canvas).commit()
touches().release(0, c, canvas).move(1, p(260, 190), canvas).commit()
assert not canvas.pen_down
touches().move(1, p(260, 195), canvas).commit()
touches().release(1, p(260, 210), canvas).commit()
stroke, = canvas.trajectory.strokes
assert [(point.x, point.y) for point in stroke.points] == [(50, 50), (90, 90), (140, 100)]
assert canvas.trajectory.input_type == "finger" and not canvas.trajectory.pressure_available
touches().press(0, a, canvas).commit()
app.sendEvent(canvas, QtGui.QTouchEvent(event.TouchCancel, device, none, []))
assert canvas.trajectory.strokes == [stroke] and not canvas.pen_down
touches().release(0, a, canvas).commit()
touches().press(0, a, canvas).commit()
touches().release(0, a, canvas).commit()
assert canvas.trajectory.strokes == [stroke]
canvas.allow_pointer_dot = True
touches().press(0, a, canvas).commit()
touches().release(0, a, canvas).commit()
assert len(canvas.trajectory.strokes[-1].points) == 1
"""
    result = subprocess.run(
        [sys.executable, "-c", program], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, encoding="utf-8", timeout=25, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
