"""Page order increases downwards, including the page picker's arrow controls."""

from PySide6 import QtWidgets


class PageNumberSpinBox(QtWidgets.QSpinBox):
    def stepBy(self, steps):
        super().stepBy(-steps)

    def stepEnabled(self):
        original = super().stepEnabled()
        flag = QtWidgets.QAbstractSpinBox.StepEnabledFlag
        reversed_flags = flag.StepNone
        if original & flag.StepUpEnabled:
            reversed_flags |= flag.StepDownEnabled
        if original & flag.StepDownEnabled:
            reversed_flags |= flag.StepUpEnabled
        return reversed_flags
