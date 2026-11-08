"""Visibility changes preserve completed layout and frozen document choices."""

import os
import subprocess
import sys


PROGRAM = r'''
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'packaging'))
os.environ['INKSTRUCT_LAYOUT_PREVIEW_HOME'] = str(Path(sys.argv[1]) / 'private')
from inkstruct_layout_launcher import configure_preview
configure_preview()
os.environ.pop('INKSTRUCT_LAYOUT_PREVIEW', None)
from PySide6 import QtCore, QtWidgets
from inkstruct.assets.resolver import AssetResolver
from inkstruct.editor.mixed import MixedWindow
app = QtWidgets.QApplication([])
w = MixedWindow(source='123123\n\n456456')
w.resolver = AssetResolver(builtin_numbers=True)
w.resize(1360, 900)
w.show()
w.schedule_layout()
end = time.monotonic() + 30
while time.monotonic() < end:
    app.processEvents()
    if w.snapshot and not w.worker and not w.timer.isActive() and w.canvas.isEnabled():
        break
    time.sleep(.01)
else:
    raise AssertionError(w.status.text())
w.recovery_timer.stop()
views = w.workspace_views
if sys.argv[2] == 'restore':
    assert views.mode == 'preview'
    assert not w.editor.isVisible() and w.page_picker.isVisible() and w.zoom.isVisible()
    assert views.split_sizes == [int(n) for n in sys.argv[3:5]]
else:
    assert views.mode == 'split'
    identity = w.source_session.identity_record()
    selections = w.resolver.selection_records()
    assert selections
    snapshot = w.snapshot
    source = w.editor.toPlainText()
    views.splitter.moveSplitter(310, 1)
    app.processEvents()
    sizes = views.splitter.sizes()
    assert min(sizes) > 0
    views.buttons['preview'].click()
    app.processEvents()
    assert views.mode == 'preview' and not w.editor.isVisible()
    assert w.page_picker.isVisible() and w.zoom.isVisible()
    assert not w.editor.hasFocus()
    # The existing source shortcut must reveal a reachable editor.
    source_action = next(a for menu in w.menuBar().findChildren(QtWidgets.QMenu)
                         for a in menu.actions() if a.text() == '聚焦 Markdown 源码')
    source_action.trigger()
    app.processEvents()
    assert views.mode == 'split' and w.editor.isVisible()
    assert views.splitter.sizes() == sizes
    views.buttons['source'].click()
    app.processEvents()
    assert w.editor.isVisible() and not w.scroll.isVisible()
    views.buttons['preview'].click()
    app.processEvents()
    assert w.snapshot is snapshot and w.source_session.identity_record() == identity
    assert w.resolver.selection_records() == selections and w.editor.toPlainText() == source
    assert not w.timer.isActive() and not w.worker
    views.settings.sync()
    print('SPLIT_SIZES', *sizes)
w.dirty = False
w.close()
app.processEvents()
QtCore.QThreadPool.globalInstance().waitForDone()
'''


def test_modes_preserve_document_and_restore_preferences_in_new_process(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    first = subprocess.run([sys.executable, "-c", PROGRAM, str(tmp_path), "write"],
                           env=env, capture_output=True, text=True, timeout=60, check=False)
    assert first.returncode == 0, first.stderr
    sizes = next(line.split()[1:] for line in first.stdout.splitlines() if line.startswith("SPLIT_SIZES"))
    second = subprocess.run([sys.executable, "-c", PROGRAM, str(tmp_path), "restore", *sizes],
                            env=env, capture_output=True, text=True, timeout=60, check=False)
    assert second.returncode == 0, second.stderr
