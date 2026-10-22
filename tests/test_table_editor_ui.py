import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6 import QtWidgets

from inkstruct.table_editor.app import create_window


def test_editing_blocks_stale_export_and_exports_current_svg(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = create_window()
    assert window.svg and window.export_button.isEnabled()
    original = window.svg
    window.editor.setPlainText("<table><tr><td>123.45</td></tr></table>")
    assert window.svg is None
    assert not window.export_button.isEnabled()
    out = tmp_path / "numeric.svg"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(out), "SVG"))
    window.export_svg()
    assert out.read_text() == window.svg and window.svg != original
    window.editor.setPlainText("<table><tr><td>不可导出</td></tr></table>")
    assert not window.refresh()
    assert not window.export_button.isEnabled()
    window.export_svg()
    assert out.read_text() != ""
    window.editor.document().setModified(False)
    window.project_dirty = False
    window.close()
    app.processEvents()


def test_project_roundtrip_preserves_html_and_physical_settings(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = create_window()
    window.controls["digit_height"].setValue(5.5)
    window.controls["row_height"].setValue(12)
    window.weights.setText("1, 2, 3")
    source = window.editor.toPlainText()
    project = tmp_path / "saved.inktable"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(project), ""))
    window.save_project()
    assert not window.project_dirty
    restored = create_window()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a: (str(project), ""))
    restored.open_project()
    assert restored.controls["digit_height"].value() == 5.5
    assert restored.settings().column_weights == (1, 2, 3)
    assert restored.editor.toPlainText() == source
    assert restored.svg and not restored.project_dirty
    window.close()
    restored.close()
    app.processEvents()


def test_routing_options_export_and_project_compatibility(tmp_path, monkeypatch):
    import json

    from inkstruct.table_editor.core import drawing_svg
    from inkstruct.table_editor.routing import optimize_paths

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = create_window()
    assert not window.optimize_checkbox.isChecked()
    assert not hasattr(window, "reverse_checkbox")
    baseline = window.svg
    out = tmp_path / "optimized.svg"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(out), ""))
    window.optimize_checkbox.setChecked(True)
    assert window.project_dirty
    window.export_svg()
    route = optimize_paths((*window.drawing.borders, *window.drawing.numbers))
    assert out.read_text() == drawing_svg(window.drawing, paths=route.paths)
    assert out.read_text() != baseline
    assert "空行程" in window.status.text()
    assert f"反转 {sum(route.reversed_paths)} 条" in window.status.text()
    window.optimize_checkbox.setChecked(False)
    window.export_svg()
    assert out.read_text() == baseline
    window.optimize_checkbox.setChecked(True)
    project = tmp_path / "routing.inktable"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(project), ""))
    window.save_project()
    restored = create_window()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a: (str(project), ""))
    restored.open_project()
    assert restored.optimize_checkbox.isChecked()
    assert not restored.project_dirty
    payload = json.loads(project.read_text())
    # Old projects cannot switch off reversal while retaining optimization.
    payload["routing"]["allow_reverse"] = False
    project.write_text(json.dumps(payload))
    restored.open_project()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(out), ""))
    restored.export_svg()
    assert out.read_text() == drawing_svg(restored.drawing, paths=route.paths)
    del payload["routing"]
    project.write_text(json.dumps(payload))
    restored.open_project()
    assert not restored.optimize_checkbox.isChecked()
    window.close()
    restored.close()
    app.processEvents()
