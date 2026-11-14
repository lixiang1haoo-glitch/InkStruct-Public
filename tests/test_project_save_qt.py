import os
from importlib.util import find_spec
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(find_spec('PySide6') is None, reason='desktop extra missing')
def test_project_save_coalesces_shortcuts_without_blocking_editor(tmp_path):
    program = r'''
        import sys
        import threading
        from pathlib import Path

        from PySide6 import QtCore, QtGui, QtTest, QtWidgets

        from inkstruct.document.package import load_package
        from inkstruct.editor import mixed

        root = Path(sys.argv[1])
        app = QtWidgets.QApplication([])
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
        QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(root))
        window = mixed.MixedWindow(source='1')
        window.show()
        window.activateWindow()
        window.workspace_views.focus_source()
        window.editor.setFocus()
        QtTest.QTest.qWait(50)
        window.recovery_timer.setInterval(60000)
        path = root / 'body.inkdoc'
        dialogs, errors, writes, finished = [], [], [], []
        entered, release = threading.Event(), threading.Event()
        original_save = mixed.save_package
        gui_thread = threading.get_ident()

        def choose_file(*args):
            dialogs.append(True)
            return str(path), ''

        def save(*args, **kwargs):
            assert threading.get_ident() != gui_thread
            writes.append(args[1].source)
            if len(writes) == 1:
                entered.set()
                assert release.wait(8)
            return original_save(*args, **kwargs)

        def wait_for(condition):
            for _ in range(500):
                if condition():
                    return
                QtTest.QTest.qWait(10)
            raise AssertionError((window.status.text(), dialogs, errors, writes, finished))

        def ctrl_s():
            QtTest.QTest.keyClick(window.editor, QtCore.Qt.Key.Key_S, QtCore.Qt.KeyboardModifier.ControlModifier)

        QtWidgets.QFileDialog.getSaveFileName = choose_file
        window.message_error = errors.append
        window.project_save_finished.connect(finished.append)
        mixed.save_package = save
        try:
            ctrl_s()
            wait_for(entered.is_set)
            assert window.project_save is not None and not path.exists()
            for _ in range(25):
                ctrl_s()
            assert not window.project_save_pending
            window.editor.moveCursor(QtGui.QTextCursor.MoveOperation.End)
            QtTest.QTest.keyClicks(window.editor, '2')
            for _ in range(25):
                ctrl_s()
            assert window.project_save_pending
            QtTest.QTest.keyClicks(window.editor, '3')
            assert writes == ['1'] and len(dialogs) == 1
        finally:
            release.set()
        wait_for(lambda: window.project_save is None and finished == [True])
        assert not errors and not window.dirty
        assert writes == ['1', '123']
        assert load_package(path).session.source == '123', window.status.text()
        assert load_package(path.with_name(path.name + '.previous.inkdoc')).session.source == '1'
        for _ in range(25):
            ctrl_s()
        assert window.project_save is None and writes == ['1', '123']

        window.editor.insertPlainText('4')
        original_bytes = path.read_bytes()
        path.write_bytes(original_bytes + b'external')
        ctrl_s()
        wait_for(lambda: finished == [True, False])
        assert window.dirty and '修改' in errors[-1]
        assert path.read_bytes() == original_bytes + b'external'
        path.write_bytes(original_bytes)

        QtWidgets.QMessageBox.question = lambda *args: QtWidgets.QMessageBox.StandardButton.Save
        assert window.close()
        assert load_package(path).session.source == '1234'
        assert writes == ['1', '123', '1234']
    '''
    result = subprocess.run(
        [sys.executable, '-B', '-c', textwrap.dedent(program), str(tmp_path)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'INKSTRUCT_LAYOUT_PREVIEW_HOME': str(tmp_path)},
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
