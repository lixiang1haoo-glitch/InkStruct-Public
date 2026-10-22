"""Parameter controls never consume a scrolling gesture to change their value."""

from PySide6 import QtCore, QtGui, QtWidgets


class ParameterWheelGuard(QtCore.QObject):
    def eventFilter(self, watched, event):
        if event.type() != QtCore.QEvent.Type.Wheel or not isinstance(watched, QtWidgets.QWidget):
            return False
        control = watched
        while control is not None:
            if isinstance(
                control, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox, QtWidgets.QSlider)
            ):
                break
            if isinstance(control, (QtWidgets.QAbstractScrollArea, QtWidgets.QAbstractItemView)):
                return False
            control = control.parentWidget()
        if control is None:
            return False
        parent = control.parentWidget()
        while parent is not None and not isinstance(parent, QtWidgets.QAbstractScrollArea):
            parent = parent.parentWidget()
        event.ignore()
        if parent is not None:
            viewport = parent.viewport()
            forwarded = QtGui.QWheelEvent(
                QtCore.QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                event.globalPosition(),
                event.pixelDelta(),
                event.angleDelta(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
                event.source(),
            )
            QtWidgets.QApplication.sendEvent(viewport, forwarded)
        return True


def protect_parameter_wheels(application):
    if not hasattr(application, "_parameter_wheel_guard"):
        guard = ParameterWheelGuard(application)
        application.installEventFilter(guard)
        application._parameter_wheel_guard = guard
