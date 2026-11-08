from PySide6 import QtCore, QtTest, QtWidgets

from inkstruct.editor.page_navigation import PageNumberSpinBox


def test_page_arrows_keyboard_bounds_and_typed_number():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    picker = PageNumberSpinBox()
    picker.setRange(1, 3)
    picker.resize(150, 32)
    picker.show()
    app.processEvents()
    flag = QtWidgets.QAbstractSpinBox.StepEnabledFlag
    option = QtWidgets.QStyleOptionSpinBox()
    picker.initStyleOption(option)
    control = QtWidgets.QStyle.ComplexControl.CC_SpinBox
    sub = QtWidgets.QStyle.SubControl
    up = picker.style().subControlRect(control, option, sub.SC_SpinBoxUp, picker).center()
    down = picker.style().subControlRect(control, option, sub.SC_SpinBoxDown, picker).center()
    assert picker.stepEnabled() == flag.StepDownEnabled
    QtTest.QTest.mouseClick(picker, QtCore.Qt.MouseButton.LeftButton, pos=down)
    assert picker.value() == 2
    QtTest.QTest.mouseClick(picker, QtCore.Qt.MouseButton.LeftButton, pos=up)
    assert picker.value() == 1
    QtTest.QTest.keyClick(picker, QtCore.Qt.Key.Key_Down)
    assert picker.value() == 2
    QtTest.QTest.keyClick(picker, QtCore.Qt.Key.Key_Up)
    assert picker.value() == 1
    picker.lineEdit().setText('3')
    picker.interpretText()
    assert picker.value() == 3 and picker.stepEnabled() == flag.StepUpEnabled
    picker.stepBy(-1)
    assert picker.value() == 3
    picker.stepBy(1)
    assert picker.value() == 2
    picker.setRange(1, 1)
    assert picker.stepEnabled() == flag.StepNone
    picker.close()
