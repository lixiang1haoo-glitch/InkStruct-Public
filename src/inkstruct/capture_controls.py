"""Common canvas controls for both handwriting capture tabs."""

from PySide6 import QtCore, QtWidgets


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
    row.addWidget(slider, 1)
    row.addWidget(value)
    return row, slider, value
