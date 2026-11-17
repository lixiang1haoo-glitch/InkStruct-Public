import os
import subprocess
import sys


def test_about_uses_both_themes_browser_and_clipboard(tmp_path):
    program = r'''
import sys
from PySide6 import QtCore, QtGui, QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.theme import use_platform_theme

sys.path.insert(0, 'packaging')
from inkstruct_smoke import verify_about_page

app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, sys.argv[1])
editor = MixedWindow(source='12')
dialog = SettingsDialog(editor, category='about')
dialog.show()
assert dialog.items['about'].parent().text(0) == '应用设置'
for theme in ('light', 'dark'):
    use_platform_theme(app, mode=theme)
    result = verify_about_page(dialog, app)
    field = dialog.pages['about'].qq_number
    assert field.fontMetrics().horizontalAdvance(field.text()) + 8 < field.contentsRect().width()
    for key, dark in (('background', theme == 'dark'), ('ink', theme != 'dark')):
        assert (QtGui.QColor(result[key]).lightness() < 128) == dark, result
    assert 'InkStruct墨构交流群' in [label.text() for label in dialog.pages['about'].findChildren(QtWidgets.QLabel)]
    assert dialog.close_button.text() == '关闭'
dialog.search.setText('1035966437')
assert dialog.current == 'about'
dialog.search.clear()
dialog.select('body')
assert not dialog.save_button.isHidden() and dialog.close_button.text() == '取消'
dialog.reject()
editor.timer.stop()
if editor.cancelled:
    editor.cancelled.set()
editor.pool.waitForDone()
editor.dirty = False
editor.close()
'''
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "1.5"}, capture_output=True,
        text=True, encoding="utf-8", timeout=45, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
