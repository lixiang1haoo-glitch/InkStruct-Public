import os
from pathlib import Path
import subprocess
import sys


def test_library_apply_navigation(tmp_path):
    subprocess.run(
        [sys.executable, __file__, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, check=True, timeout=60,
    )


def exercise(root):
    from PySide6 import QtCore, QtWidgets
    from inkstruct.application import InkStructWindow
    from inkstruct.editor.resource_apply import ResourceApplyDialog
    from inkstruct.fonts.importer import build_font
    from test_font_packages import recorded

    app = QtWidgets.QApplication([])
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root))
    window = InkStructWindow(workspace=root / "workspace")
    window.show()
    font = window.library.root / "navigation.inkfont"
    build_font(font, writer="fixture", name="Navigation", symbols=recorded(root))
    window.library.refresh(font)

    for tab, library in ((4, window.template_library), (2, window.library)):
        window.navigation_buttons[tab].click()
        library.list.setCurrentRow(0)
        for accept in (False, True):
            assert window.tabs.currentIndex() == tab and library.use_button.isEnabled()
            clicked = []
            timer = QtCore.QTimer()
            def answer():
                dialog = app.activeModalWidget()
                if not isinstance(dialog, ResourceApplyDialog):
                    return
                if accept:
                    if dialog.result is None:
                        return
                    dialog.acknowledge.setChecked(True)
                role = QtWidgets.QDialogButtonBox.Ok if accept else QtWidgets.QDialogButtonBox.Cancel
                button = dialog.buttons.button(role)
                if button.isEnabled():
                    clicked.append(role)
                    timer.stop()
                    button.click()
            timer.timeout.connect(answer)
            timer.start(10)
            library.use_button.click()
            assert len(clicked) == 1
            expected = window.tabs.indexOf(window.editor) if accept else tab
            assert window.tabs.currentIndex() == expected and window.navigation_buttons[expected].isChecked()
    assert window.editor.run_path == str(font)
    window.editor.dirty = False
    window.close()
    QtCore.QThreadPool.globalInstance().waitForDone()


if __name__ == "__main__":
    exercise(Path(sys.argv[1]))
