"""Common canvas controls for both handwriting capture tabs."""

from PySide6 import QtCore, QtGui, QtWidgets

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


def capture_writing_row(owner, canvas_view, reference=None):
    """Keep a single action column beside the drawing surface in both tabs."""
    column = QtWidgets.QWidget()
    column.setObjectName("captureWritingActions")
    actions = QtWidgets.QVBoxLayout(column)
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(8)
    for button, title, shortcut in (
        (owner.undo_button, "撤销上一笔", "Ctrl+Z"),
        (owner.clear_button, "重写当前字", "Delete"),
        (owner.skip_button, "暂时跳过", "Shift+Enter"),
        (owner.save_button, "保存并下一个", "Enter"),
    ):
        button.setText(f"{title}\n{shortcut}")
        button.setAccessibleName(title)
        button.setAccessibleDescription(shortcut)
        button.setMinimumSize(112, 48)
        actions.addWidget(button)
    owner.save_button.setProperty("inkRole", "primary")
    skip = QtGui.QShortcut(owner)
    skip.setKeys([QtGui.QKeySequence("Shift+Return"), QtGui.QKeySequence("Shift+Enter")])
    skip.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    skip.setAutoRepeat(False)
    skip.activated.connect(owner.skip_button.click)

    row = QtWidgets.QHBoxLayout()
    row.setSpacing(0)
    if reference is not None:
        row.addWidget(reference, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(24)
    row.addStretch()
    row.addWidget(column, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
    row.addSpacing(12)
    row.addWidget(canvas_view, 1)
    row.addStretch()
    return row


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
