"""Parameter controls never consume a scrolling gesture to change their value."""

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


def compact_field(control, *, maximum=None):
    """Keep a short field near its label while preserving the native size hint."""
    if maximum is not None:
        control.setMaximumWidth(maximum)
    else:
        if isinstance(control, QtWidgets.QComboBox):
            control.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
            control.setMinimumWidth(max(160, control.minimumWidth()))
        elif isinstance(control, QtWidgets.QAbstractSpinBox):
            control.setMinimumWidth(max(96, control.minimumWidth()))
        policy = control.sizePolicy()
        policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Fixed)
        control.setSizePolicy(policy)
    return control


class AdaptiveActions(QtWidgets.QWidget):
    """Keep the first command visible and place remaining commands in a narrow-window menu."""

    def __init__(self, buttons, parent=None):
        super().__init__(parent)
        self.buttons = tuple(buttons)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for button in self.buttons:
            row.addWidget(button)
        self.more = QtWidgets.QPushButton("更多来源…", self)
        self.more.setAccessibleName("更多生成内容来源")
        self.menu = QtWidgets.QMenu(self.more)
        self.more.setMenu(self.menu)
        for button in self.buttons[1:]:
            self.menu.addAction(button.text(), button.click)
        self.menu.aboutToShow.connect(self.sync_menu)
        row.addWidget(self.more)
        row.addStretch()
        self.compact = False
        self.more.hide()
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)

    def sync_menu(self):
        for action, button in zip(self.menu.actions(), self.buttons[1:]):
            action.setEnabled(button.isEnabled())

    def resizeEvent(self, event):
        count = len(self.buttons)
        full_width = sum(button.sizeHint().width() for button in self.buttons) + self.layout().spacing() * (count - 1)
        compact = event.size().width() < full_width
        if compact != self.compact:
            self.compact = compact
            self.more.setVisible(compact)
            for button in self.buttons[1:]:
                button.setVisible(not compact)
        super().resizeEvent(event)


def open_containing_folder(path):
    folder = Path(path).resolve().parent
    if not folder.is_dir() or not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder))):
        raise OSError(f"无法打开文件夹：{folder}")


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
