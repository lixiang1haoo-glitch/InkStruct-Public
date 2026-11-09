"""Wheel gestures scroll; body controls stay open; retired math arrows stay hidden."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
def test_parameter_wheel_and_expanded_settings(tmp_path, dpi):
    program = r"""
import sys
from PySide6 import QtCore,QtGui,QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.theme import use_light_theme
app=QtWidgets.QApplication([]);use_light_theme(app);use_light_theme(app)
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,sys.argv[1])
w=MixedWindow();w.timer.stop();w.show()
d=SettingsDialog(w,category='body');d.resize(d.minimumWidth(),650);d.show();app.processEvents()
body=d.pages['body'];scroll=body.parentWidget().parentWidget()
assert not body.findChildren(QtWidgets.QToolButton)
for control in [*body.flow.controls.values(),*body.headings]:
    assert not control.isHidden()
    ancestor=control.parentWidget()
    while ancestor is not body:
        assert not ancestor.isHidden()
        ancestor=ancestor.parentWidget()
spin=body.style.controls['em_mm']
scroll.ensureWidgetVisible(spin);app.processEvents()
def wheel(widget,delta=-120):
    point=QtCore.QPointF(widget.rect().center())
    global_point=QtCore.QPointF(widget.mapToGlobal(point.toPoint()))
    event=QtGui.QWheelEvent(point,global_point,QtCore.QPoint(),QtCore.QPoint(0,delta),
        QtCore.Qt.NoButton,QtCore.Qt.NoModifier,QtCore.Qt.ScrollUpdate,False)
    app.sendEvent(widget,event);app.processEvents()
for focused in (False,True):
    if focused:spin.setFocus()
    else:d.search.setFocus()
    before=spin.value();scroll.verticalScrollBar().setValue(0)
    wheel(spin);assert spin.value()==before
    assert scroll.verticalScrollBar().value()>0
    forwarded_value=scroll.verticalScrollBar().value()
    scroll.verticalScrollBar().setValue(0);wheel(scroll.viewport())
    assert scroll.verticalScrollBar().value()==forwarded_value
    scroll.verticalScrollBar().setValue(0)
    wheel(spin.lineEdit());assert spin.value()==before
    assert scroll.verticalScrollBar().value()>0
mode=body.mode;before=mode.currentIndex();wheel(mode);assert mode.currentIndex()==before
spin.setFocus();before=spin.value();QtTest.QTest.keyClick(spin,QtCore.Qt.Key_Up)
assert spin.value()>before
draft=spin.value()
QtTest.QTest.keyClick(spin.lineEdit(),QtCore.Qt.Key_Return)
assert d.isVisible() and spin.value()==draft and not d.reset.isDefault()
slider=QtWidgets.QSlider(QtCore.Qt.Horizontal,body);slider.setValue(50);slider.show()
wheel(slider);assert slider.value()==50
d.select('math');math=d.pages['math'];app.processEvents()
assert math.guides.isChecked() and math.preview.show_guides
for retired in math.findChildren(QtWidgets.QScrollArea,'retired_math_scroll'):
    assert retired.isHidden()
    assert not any(bar.isVisible() for bar in retired.findChildren(QtWidgets.QScrollBar))
assert math.categories.isVisible()
math.guides.setChecked(False);assert not math.preview.show_guides
math.guides.setChecked(True);assert math.preview.show_guides
before=math.controls['em_mm'].value();wheel(math.controls['em_mm'])
assert math.controls['em_mm'].value()==before
math.controls['em_mm'].setFocus();QtTest.QTest.keyClick(math.controls['em_mm'],QtCore.Qt.Key_Escape)
app.processEvents();assert not d.isVisible() and not math.isHidden()
d.show();app.processEvents();assert math.isVisible()
d.reject();w.dirty=False;w.timer.stop();w.pool.waitForDone();w.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
