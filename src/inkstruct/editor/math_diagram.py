"""Keyboard-accessible help button for formula settings."""

from PySide6 import QtCore, QtWidgets


def info_button(parent, text="", name="说明"):
    button = QtWidgets.QToolButton(parent)
    button.setText("i")
    button.setObjectName("info_button")
    button.setAccessibleName(name)
    button.setToolTip(text)
    button.setFixedSize(19, 19)
    button.setCursor(QtCore.Qt.CursorShape.WhatsThisCursor)
    button.setStyleSheet(
        "QToolButton { color: #64748b; border: 1px solid #b7c4d2; "
        "border-radius: 9px; background: transparent; font: italic 12px Georgia; padding: 0; }"
        "QToolButton:hover, QToolButton:focus { color: #1269c7; border-color: #1269c7; }"
    )
    # Hover is the primary action; click/keyboard access exposes the same help.
    button.clicked.connect(
        lambda: QtWidgets.QToolTip.showText(
            button.mapToGlobal(QtCore.QPoint(0, button.height())), button.toolTip(), button
        )
    )
    return button
