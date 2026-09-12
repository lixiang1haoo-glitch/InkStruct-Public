import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6 import QtCore, QtGui, QtWidgets

from inkstruct.capture_boundary import install_capture_boundary_guard


def test_guide_resize_undo_and_save_confirmation(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Canvas(QtWidgets.QWidget):
        trajectory_changed = QtCore.Signal()

    owner = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(owner)
    owner.canvas = Canvas(owner)
    owner.canvas.trajectory = SimpleNamespace(strokes=[])
    layout.addWidget(owner.canvas)
    guard = install_capture_boundary_guard(owner, QtCore, QtGui, QtWidgets)
    owner.resize(400, 600)
    owner.show()
    app.processEvents()
    assert guard.guide.geometry() == owner.canvas.rect()
    assert guard.guide.testAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert guard.allow_save()
    owner.canvas.trajectory.strokes = [SimpleNamespace(points=[SimpleNamespace(x=0, y=20)])]
    owner.canvas.trajectory_changed.emit()
    assert "触及" in guard.label.text()
    calls = []

    def answer(*args):
        calls.append(args)
        return QtWidgets.QMessageBox.StandardButton.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", answer)
    assert not guard.allow_save()
    assert calls[0][-1] == QtWidgets.QMessageBox.StandardButton.No
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        lambda *args: QtWidgets.QMessageBox.StandardButton.Yes)
    assert guard.allow_save()
    owner.canvas.trajectory.strokes = []
    owner.canvas.trajectory_changed.emit()
    assert guard.status() == "clear"
    owner.resize(600, 400)
    app.processEvents()
    assert guard.guide.geometry() == owner.canvas.rect()
    assert guard.allow_save()
    owner.close()
