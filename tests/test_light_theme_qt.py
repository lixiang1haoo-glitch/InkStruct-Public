"""Desktop theme selection, native palette changes, and the compatibility fallback."""

import os
import subprocess
import sys

import pytest


def test_font_library_display_recolors_loaded_svg_when_theme_changes(tmp_path):
    program = r"""
import sys
from pathlib import Path
from PySide6 import QtGui, QtWidgets
from inkstruct.fonts.ui import FontLibrary
from inkstruct.theme import use_platform_theme

app = QtWidgets.QApplication([])
use_platform_theme(app, windows11_accents=True, mode="light")
library = FontLibrary(Path(sys.argv[1]) / "fonts")
svg = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 30">'
       b'<rect width="90" height="30" fill="white"/>'
       b'<path d="M 10,10 H 30" stroke="#24354b" stroke-width="4"/>'
       b'<path d="M 40,10 H 60" stroke="#111827" stroke-width="4"/>'
       b'<path d="M 70,10 H 80" stroke="#dc2626" stroke-width="4"/></svg>')
for pane in (library.ink_preview, library.character_preview):
    pane.set_preview(svg)
for mode in ("light", "dark", "light"):
    use_platform_theme(app, windows11_accents=True, mode=mode)
    app.processEvents()
    for pane in (library.ink_preview, library.character_preview):
        assert pane.preview_svg == svg
        image = QtGui.QImage(90, 30, QtGui.QImage.Format_RGB32)
        painter = QtGui.QPainter(image)
        pane.renderer().render(painter)
        painter.end()
        paper, ink, formula, missing = [image.pixelColor(x, y) for x, y in ((2, 2), (20, 10), (50, 10), (75, 10))]
        assert (paper.lightness() < 128) == (mode == "dark")
        assert (ink.lightness() > 128) == (formula.lightness() > 128) == (mode == "dark")
        assert missing.red() > missing.green()
library.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32" or sys.getwindowsversion().build < 22000,
                    reason="requires the Windows 11 Qt platform")
def test_windows11_style_accepts_both_appearance_profiles(tmp_path):
    program = r"""
from unittest.mock import patch
from PySide6 import QtCore, QtGui, QtWidgets
from inkstruct.app_shell import PaletteIcon, _on_accent
from inkstruct.theme import use_platform_theme

app = QtWidgets.QApplication([])
with patch.object(QtWidgets.QStyleFactory, 'create', return_value=None):
    assert use_platform_theme(app) == 'fusion'
if 'windows11' not in [key.lower() for key in QtWidgets.QStyleFactory.keys()]:
    raise SystemExit(77)
for accents in (False, True, False):
    assert use_platform_theme(app, windows11_accents=accents) == 'windows11'
    assert bool(app.styleSheet()) == accents
    button = QtWidgets.QToolButton()
    button.setProperty('inkRole', 'navigation')
    button.setCheckable(True)
    icon = PaletteIcon(button, 'generate')
    button.show()
    for scheme in (QtCore.Qt.ColorScheme.Light, QtCore.Qt.ColorScheme.Dark):
        app.styleHints().setColorScheme(scheme)
        app.processEvents()
        assert use_platform_theme(app, windows11_accents=accents) == 'windows11'
        assert app.styleHints().colorScheme() == scheme
        assert (app.palette().color(QtGui.QPalette.Window).lightness() < 128) == (scheme == QtCore.Qt.ColorScheme.Dark)
        assert icon.color == button.palette().color(QtGui.QPalette.Active, QtGui.QPalette.ButtonText).name()
        button.setChecked(True)
        assert icon.color == _on_accent(button.palette().color(QtGui.QPalette.Active, QtGui.QPalette.Accent))
        button.setChecked(False)
    button.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "windows"},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode == 77:
        pytest.skip("Qt windows11 style plugin unavailable")
    assert result.returncode == 0, result.stdout + result.stderr


def test_theme_preference_is_local_to_application_settings(tmp_path):
    program = r"""
import sys
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from inkstruct.application import InkStructWindow
from inkstruct.global_defaults import GlobalDefaultsStore
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.theme import THEME_KEY, theme_preference

app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, sys.argv[1])
settings = GlobalDefaultsStore.make_settings()
settings.setValue(THEME_KEY, "invalid")
assert theme_preference(settings) == "system"
window = InkStructWindow(workspace=Path(sys.argv[1]) / "workspace")
editor = window.editor
editor.document_started = True
before = (editor.flow, editor.style, editor.page, editor.source_session.atom_ids, editor.dirty)
dialog = SettingsDialog(editor, window.collector, window, category="appearance")
page = dialog.pages["appearance"]
assert page.theme.currentData() == "system"
assert dialog.apply_document.isHidden()
page.theme.setCurrentIndex(page.theme.findData("dark"))
dialog.reject()
assert theme_preference(settings) == "system"
assert app.palette().color(QtGui.QPalette.Base).lightness() > 128

dialog = SettingsDialog(editor, window.collector, window, category="appearance")
page = dialog.pages["appearance"]
page.theme.setCurrentIndex(page.theme.findData("dark"))
dialog.accept()
assert dialog.result() == QtWidgets.QDialog.Accepted, dialog.error.text()
assert theme_preference(settings) == "dark"
assert app.palette().color(QtGui.QPalette.Base).lightness() < 128
assert app.palette().color(QtGui.QPalette.Text).lightness() > 128
assert not settings.contains(GlobalDefaultsStore.KEY)

dialog = SettingsDialog(editor, window.collector, window, category="appearance")
page = dialog.pages["appearance"]
assert page.theme.currentData() == "dark"
dialog.reset_current()
assert page.theme.currentData() == "system"
dialog.accept()
assert dialog.result() == QtWidgets.QDialog.Accepted, dialog.error.text()
assert theme_preference(settings) == "system"
assert app.palette().color(QtGui.QPalette.Base).lightness() > 128
assert not settings.contains(GlobalDefaultsStore.KEY)
assert before == (editor.flow, editor.style, editor.page, editor.source_session.atom_ids, editor.dirty)
editor.timer.stop()
if editor.cancelled:
    editor.cancelled.set()
editor.pool.waitForDone()
window.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
def test_dark_host_uses_light_controls_without_document_changes(tmp_path, dpi):
    program = r"""
import sys,time
from pathlib import Path
from PySide6 import QtCore,QtGui,QtTest,QtWidgets
from inkstruct.application import InkStructWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.theme import native_style_key, use_light_theme
app=QtWidgets.QApplication([])
assert native_style_key('windows', 19045) is None
assert native_style_key('windows', 22000) == 'windows11'
assert native_style_key('offscreen', 26300) is None
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
assert app.property('inkstructDesktopStyle') == 'fusion'
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
unstepped=QtWidgets.QSpinBox()
unstepped.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
unstepped.setValue(3)
unstepped.show();app.processEvents()
QtTest.QTest.mouseClick(unstepped,QtCore.Qt.LeftButton,pos=QtCore.QPoint(unstepped.width()-8,6))
assert unstepped.value()==3
unstepped.close()
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
