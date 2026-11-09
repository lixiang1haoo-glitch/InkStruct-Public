"""Dark host palettes must not leak into the application or settings controls."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
def test_dark_host_uses_light_controls_without_document_changes(tmp_path, dpi):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtCore,QtGui,QtWidgets
from inkstruct.application import InkStructWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.theme import use_light_theme
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,sys.argv[1])
app.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Dark)
palette=QtGui.QPalette()
for group in (QtGui.QPalette.Active,QtGui.QPalette.Inactive,QtGui.QPalette.Disabled):
    for role in (QtGui.QPalette.Window,QtGui.QPalette.Base,QtGui.QPalette.Button):
        palette.setColor(group,role,QtGui.QColor('#202020'))
    for role in (QtGui.QPalette.Text,QtGui.QPalette.WindowText,QtGui.QPalette.ButtonText):
        palette.setColor(group,role,QtGui.QColor('#eeeeee'))
app.setPalette(palette)
w=InkStructWindow(workspace=Path(sys.argv[1])/'workspace');w.show();app.processEvents()
assert app.styleHints().colorScheme()!=QtCore.Qt.ColorScheme.Dark
for group in (QtGui.QPalette.Active,QtGui.QPalette.Inactive,QtGui.QPalette.Disabled):
    p=app.palette()
    assert p.color(group,QtGui.QPalette.Window).lightness()>230
    assert p.color(group,QtGui.QPalette.Base).lightness()>230
    assert p.color(group,QtGui.QPalette.Text).lightness()<180
for widget in (w,w.collector,w.generator,w.library,w.editor,w.editor.editor):
    assert widget.palette().color(QtGui.QPalette.Window).lightness()>230
before=(w.editor.flow,w.editor.style,w.editor.page,w.editor.source_session.atom_ids,
        w.collector.ui_settings)
w.tabs.setCurrentIndex(1);app.processEvents()
spin=w.generator.centralWidget().candidate_limit
option=QtWidgets.QStyleOptionSpinBox()
spin.initStyleOption(option)
step_rect=spin.style().subControlRect(QtWidgets.QStyle.CC_SpinBox,option,QtWidgets.QStyle.SC_SpinBoxUp,spin)
assert step_rect.width() >= 20, step_rect
spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
spin.initStyleOption(option)
assert spin.style().subControlRect(QtWidgets.QStyle.CC_SpinBox,option,QtWidgets.QStyle.SC_SpinBoxUp,spin).isEmpty()
spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.UpDownArrows)
d=SettingsDialog(w.editor,w.collector,w,category='capture');d.show()
for key in d.items:
    d.select(key);app.processEvents()
    page=d.pages[key]
    assert page.palette().color(QtGui.QPalette.Base).lightness()>230
    for field in page.findChildren(QtWidgets.QAbstractSpinBox):
        assert field.palette().color(QtGui.QPalette.Base).lightness()>230
    assert len(d.findChildren(QtWidgets.QPushButton))>0
assert d.apply(),d.error.text()
assert before==(w.editor.flow,w.editor.style,w.editor.page,w.editor.source_session.atom_ids,w.collector.ui_settings)
menu=QtWidgets.QMenu(w);menu.addAction('menu item')
assert menu.palette().color(QtGui.QPalette.Window).lightness()>230
box=QtWidgets.QMessageBox(w);box.setText('message')
assert box.palette().color(QtGui.QPalette.Window).lightness()>230
file=QtWidgets.QFileDialog(w);file.setOption(QtWidgets.QFileDialog.DontUseNativeDialog)
assert file.palette().color(QtGui.QPalette.Base).lightness()>230
# Repeating initialization is stable and does not mutate document preferences.
use_light_theme(app)
assert before==(w.editor.flow,w.editor.style,w.editor.page,w.editor.source_session.atom_ids,w.collector.ui_settings)
d.reject();d.deleteLater();menu.deleteLater();box.deleteLater();file.deleteLater()
w.editor.timer.stop()
if w.editor.cancelled:w.editor.cancelled.set()
w.editor.pool.waitForDone();w.editor.dirty=False;w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
