"""Blank-launch keyboard/paste editing and optional panels preserve the document."""

import os
import subprocess
import sys


def test_blank_launch_input_paste_undo_and_optional_panels(tmp_path):
    program = r"""
import time
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg

class Window(MixedWindow):
    def write_recovery(self):
        pass

app = QtWidgets.QApplication([])
app.setStyle('Fusion')
w = Window()
w.resize(1000, 700)
w.show()
def ready():
    end = time.monotonic() + 10
    while time.monotonic() < end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():
            assert not w.source_error, w.source_error
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
assert app.focusWidget() is w.editor  # No preliminary click or test-only focus call.
assert not w.problems_dock.isVisible() and not w.review_dock.isVisible()
assert w.editor.height() > 500 and w.scroll.viewport().height() > 500
QtTest.QTest.keyClicks(app.focusWidget(), '12.3')
ready()
assert w.buffer.raw == w.editor.toPlainText() == '12.3'
atoms = w.source_session.atom_ids
app.clipboard().setText('\n\n| 1 | 2 |\n|---|---|\n| 3.4 | 5.6 |')
QtTest.QTest.keySequence(w.editor, QtGui.QKeySequence.Paste)
ready()
assert '| 3.4 | 5.6 |' in w.buffer.raw and w.snapshot.plotter_exportable
QtTest.QTest.keySequence(w.editor, QtGui.QKeySequence.Undo)
ready()
assert w.buffer.raw == '12.3' and w.source_session.atom_ids == atoms
app.clipboard().setText('45.6')
w.editor.selectAll()
paste = w.findChild(QtWidgets.QToolButton, 'paste_source')
QtTest.QTest.mouseClick(paste, QtCore.Qt.LeftButton)
ready()
assert w.editor.toPlainText() == w.buffer.raw == '45.6'
assert app.focusWidget() is w.editor
w.editor.undo(); ready()
assert w.buffer.raw == '12.3' and w.source_session.atom_ids == atoms
settings = w.findChild(QtWidgets.QToolButton, 'unified_settings_button')
assert settings.accessibleName() == '设置'
assert not any(b.text() in ('字形', '排版') for b in w.findChildren(QtWidgets.QToolButton))
from inkstruct.settings_dialog import SettingsDialog
def cancel_settings():
    dialog = app.activeModalWidget()
    assert isinstance(dialog, SettingsDialog)
    dialog.reject()
QtCore.QTimer.singleShot(10, cancel_settings)
QtTest.QTest.mouseClick(settings, QtCore.Qt.LeftButton); app.processEvents()
snapshot = w.snapshot
svg = [page_svg(p) for p in plan_from_snapshot(snapshot).pages]
dialog = SettingsDialog(w)
for category in dialog.items:
    dialog.select(category); dialog.show(); app.processEvents()
    assert w.width() == 1000 and w.height() == 700, w.size()
    assert w.editor.isVisible() and not w.editor.isReadOnly()
dialog.reject()
w.review_dock.show(); app.processEvents(); w.review_dock.hide(); app.processEvents()
assert w.snapshot is snapshot and w.source_session.atom_ids == atoms
assert [page_svg(p) for p in plan_from_snapshot(w.snapshot).pages] == svg
# Native Edit commands must also keep ordinary settings text fields editable.
dialog = SettingsDialog(w, category='body'); dialog.show(); app.processEvents()
field = dialog.pages['body'].style.controls['em_mm'].findChild(QtWidgets.QLineEdit)
field.setFocus(); field.selectAll(); app.clipboard().setText('7')
QtTest.QTest.keySequence(field, QtGui.QKeySequence.Paste)
assert dialog.pages['body'].style.controls['em_mm'].value() == 7 and w.buffer.raw == '12.3'
dialog.reject()
w.dirty = False
w.timer.stop()
if w.cancelled: w.cancelled.set()
w.pool.waitForDone(); w.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
