"""Common canvas controls for both handwriting capture tabs."""

from PySide6 import QtCore, QtWidgets

from .ui_behavior import compact_field


class InputMismatchHint(QtWidgets.QFrame):
    def __init__(self, picker):
        super().__init__()
        self.setObjectName("captureInputHint")
        self.picker = picker
        self.target = None
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(8, 2, 6, 2)
        row.addWidget(QtWidgets.QLabel("ⓘ"))
        self.message = QtWidgets.QLabel()
        row.addWidget(self.message)
        self.action = QtWidgets.QPushButton()
        self.action.setObjectName("captureInputHintAction")
        self.action.clicked.connect(self.switch)
        row.addWidget(self.action)
        self.hide()

    @QtCore.Slot(str)
    def show_input(self, mode):
        self.target = mode
        if not mode:
            self.hide()
            return
        label = self.picker.itemText(self.picker.findData(mode))
        received = "鼠标输入" if mode == "mouse" else f"{label}输入"
        self.message.setText(f"收到{received}")
        self.action.setText(f"切换为{label}")
        self.show()

    def switch(self):
        index = self.picker.findData(self.target)
        if index >= 0 and index != self.picker.currentIndex():
            self.picker.setCurrentIndex(index)
            self.picker.activated.emit(index)


def capture_display_controls(status, progress_bar):
    """Place the two canvas controls beside the existing target and progress."""
    progress_bar.setMinimumWidth(210)
    progress_bar.setMaximumWidth(300)
    status.setStretch(1, 0)
    status.addSpacing(18)
    controls = QtWidgets.QVBoxLayout()
    status.addLayout(controls)
    status.addStretch()
    return controls


def canvas_slider_row(title, accessible_name, hint):
    row = QtWidgets.QHBoxLayout()
    label = QtWidgets.QLabel(title)
    label.setFixedWidth(label.fontMetrics().horizontalAdvance('笔迹粗细') + 14)
    slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
    slider.setMinimumWidth(140)
    slider.setAccessibleName(accessible_name)
    slider.setToolTip(hint)
    label.setBuddy(slider)
    value = QtWidgets.QLabel()
    value.setMinimumWidth(value.fontMetrics().horizontalAdvance('150% · 840 × 480 px') + 6)
    row.addWidget(label)
    row.addWidget(compact_field(slider, maximum=260), 1)
    row.addWidget(value)
    row.addStretch()
    return row, slider, value
