import pytest
from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

from inkstruct.editor.mixed import MixedWindow
from inkstruct.global_defaults import GlobalDefaultsStore


@pytest.mark.parametrize("mode", ["markdown", "plain-text"])
@pytest.mark.parametrize("extension", [".md", ".markdown", ".txt"])
def test_file_menu_import_preserves_selection_resources_and_undo(
    tmp_path, monkeypatch, mode, extension
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / "defaults.ini"), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(GlobalDefaultsStore, "make_settings", staticmethod(lambda: settings))
    monkeypatch.setattr("inkstruct.editor.mixed.recovery_directory", lambda: tmp_path)
    w = MixedWindow(mode=mode)
    w.show()
    menu = next(a.menu() for a in w.findChildren(QtGui.QAction) if a.menu() and a.text() == "文件")
    action = next(a for a in menu.actions() if a.text() == "导入 Markdown / 文本…")

    def import_file(path, choice=None):
        monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
        if choice is None:
            with monkeypatch.context() as m:
                m.setattr(w, "choose_import_action", lambda: pytest.fail("empty document prompted"))
                action.trigger()
            return
        seen = []

        def choose():
            box = app.activeModalWidget()
            seen.extend(b.text() for b in box.buttons())
            if choice == "close":
                box.close()
            else:
                next(b for b in box.buttons() if b.text() == choice).click()

        QtCore.QTimer.singleShot(0, choose)
        action.trigger()
        assert set(seen) == {"在文末追加", "替换全文", "取消"}

    try:
        path = tmp_path / ("input" + extension)
        image = tmp_path / "figure.png"
        Image.new("RGB", (6, 8), "red").save(image)
        original = "原文 ![原](figure.png) 末尾"
        added = "新文 ![新](new.png)"
        path.write_text(original, encoding="utf8")
        import_file(path)
        assert w.source_session.source == original
        original_images = w.flow.images
        assert len(original_images) == (1 if mode == "markdown" else 0)
        Image.new("RGB", (9, 10), "blue").save(tmp_path / "new.png")
        path.write_text(added, encoding="utf8")
        cursor = w.editor.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(4, QtGui.QTextCursor.MoveMode.KeepAnchor)
        w.editor.setTextCursor(cursor)
        for choice in ("取消", "close"):
            import_file(path, choice)
            assert w.source_session.source == original and w.flow.images == original_images
        import_file(path, "在文末追加")
        assert w.source_session.source == original + "\n" + added
        assert len(w.flow.images) == (2 if mode == "markdown" else 0)
        w.source_history("undo")
        assert w.source_session.source == original and w.flow.images == original_images
        import_file(path, "替换全文")
        assert w.source_session.source == added and w.mode == mode
        w.source_history("undo")
        assert w.source_session.source == original and w.flow.images == original_images
    finally:
        w.dirty = False
        w.close()
        app.processEvents()
