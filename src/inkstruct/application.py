"""InkStruct integrated desktop: capture, generate, publish, compose."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .fonts import APP_VERSION


def resources_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def database_path():
    root = resources_root()
    return (
        root / "data/characters.sqlite3"
        if getattr(sys, "frozen", False)
        else root / "artifacts/structures/characters.sqlite3"
    )


def workspace_path():
    location = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation)
    return Path(location) / "InkStruct" / "workspace"


class InkStructWindow(QtWidgets.QMainWindow):
    def __init__(self, *, workspace=None, database=None):
        from .theme import use_light_theme
        use_light_theme(QtWidgets.QApplication.instance())
        super().__init__()
        from .collector import main as collector
        from .desktop import main as generator
        from .editor.mixed import MixedWindow
        from .fonts.ui import FontLibrary

        self.workspace = Path(workspace) if workspace else workspace_path()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(f"InkStruct 墨构 · {APP_VERSION}")
        self.resize(1360, 900)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("inkstruct_modules")
        self.setCentralWidget(self.tabs)
        database = Path(database) if database else database_path()
        self.collector = collector(
            ["InkStruct"], create_only=True, workspace=self.workspace, database=database
        )
        self.generator = generator(
            ["InkStruct"], create_only=True, workspace=self.workspace, database=database
        )
        self.generator.centralWidget().writer.clear()
        self.generator.centralWidget().writer.setPlaceholderText('在采集页选择书写者，或填写已有 ID')
        def choose_capture_writer(key):
            workflow = self.generator.centralWidget()
            if not workflow.busy:
                workflow.writer.setText(key)
        self.collector.writer_selected.connect(choose_capture_writer)
        self.editor = MixedWindow()
        self.generator.centralWidget().current_document_provider = lambda: (
            self.editor.editor.toPlainText(), self.editor.flow,
            {'kind': 'current-document', 'document_id': self.editor.source_session.document_id,
             'revision': self.editor.source_session.revision})
        self.generator.centralWidget().refresh()
        self.library = FontLibrary(self.workspace / "fonts")
        self.editor.settings_host = self
        from .resources_ui import ResourceLibrary
        self.resources = ResourceLibrary(self.editor, self.library)
        for title, widget in [
            ("采集", self.collector),
            ("生成", self.generator),
            ("字体与模板", self.resources),
            ("排版", self.editor),
        ]:
            if isinstance(widget, QtWidgets.QMainWindow):
                widget.setWindowFlags(QtCore.Qt.WindowType.Widget)
                widget.menuBar().setNativeMenuBar(False)
            if widget is self.editor:
                self.tabs.addTab(widget, title)
            else:
                # Large native control/font hints must not enlarge every tab or the window.
                scroll = QtWidgets.QScrollArea()
                scroll.setObjectName('module_scroll_' + title)
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
                scroll.setWidget(widget)
                self.tabs.addTab(scroll, title)
            if isinstance(widget, QtWidgets.QMainWindow) and widget.windowHandle() is not None:
                # A formerly standalone window can retain its native QWindow after
                # reparenting on macOS. Its stale screen origin corrupts descendant
                # mapToGlobal()/mouse hit tests. Retire the native resources only;
                # the QWidget and its children remain owned by the module page.
                widget.destroy()
        self.tabs.setCurrentIndex(3)
        from .settings_dialog import gear_button
        self.settings_button = gear_button(self, self.open_settings)
        self.tabs.setCornerWidget(self.settings_button, QtCore.Qt.Corner.TopRightCorner)
        # The integrated application owns the only settings entry point.
        self.editor.settings_button.hide()
        self.editor.settings_shortcut.setEnabled(False)
        self.editor.settings_host = self
        for action in self.collector.menuBar().actions():
            if action.text() == '设置':
                self.collector.menuBar().removeAction(action)
        self.library.use_requested.connect(self.choose_font_for_document)
        self.generator.centralWidget().publish_requested.connect(self.use_generated)
        self.statusBar().showMessage(
            f"InkStruct {APP_VERSION} · 采集、生成、字体与排版 · 工作区：" + str(self.workspace)
        )
        about = QtGui.QAction("关于 InkStruct", self)
        about.triggered.connect(
            lambda: QtWidgets.QMessageBox.information(
                self,
                "InkStruct",
                f"InkStruct {APP_VERSION}\n中心线手写采集、生成、字体与模板管理、Markdown 排版。\n默认 v6.2 exp；另可选 v6.1 exp 和 v4 adaptive。",
            )
        )
        self.menuBar().addAction(about)
        available = self.screen().availableGeometry()
        self.resize(min(1360, available.width() - 32), min(900, available.height() - 64))
        self.move(available.center() - self.rect().center())

    def open_settings(self, *, category=None, target=None, reason=''):
        from .settings_dialog import open_settings
        if category is None and self.tabs.currentIndex() == 0:
            category = 'capture'
        return open_settings(self.editor, self.collector, self, category=category, target=target, reason=reason)

    def use_font(self, path):
        try:
            self.editor.use_font(path)
            self.tabs.setCurrentIndex(3)
        except (ValueError, OSError) as e:
            QtWidgets.QMessageBox.warning(self, "字体未载入", str(e))

    def choose_font_for_document(self, path):
        from .resources_ui import use_document_font
        if use_document_font(self.editor, path, self):
            self.tabs.setCurrentIndex(3)

    def use_generated(self):
        workflow = self.generator.centralWidget()
        path = getattr(workflow, "last_generated_run", None)
        if path:
            if self.library.job:
                QtWidgets.QMessageBox.information(self, "字体操作进行中", "请等待当前字体操作完成。")
                return
            self.tabs.setCurrentIndex(2)
            self.resources.setCurrentIndex(0)
            self.library.prepare_publication(path, workflow.last_generated_writer or workflow.writer.text())
        else:
            QtWidgets.QMessageBox.information(
                self, "生成结果", "请先生成，或在字体库中选择已有 v6.1/旧生成结果目录。"
            )

    def closeEvent(self, event):
        workflow = self.generator.centralWidget()
        if self.library.job or getattr(workflow, "busy", False):
            QtWidgets.QMessageBox.information(
                self, "操作进行中", "请等待字体操作完成，或在生成页取消任务后再退出。"
            )
            event.ignore()
            return
        for capture in (self.collector.single_widget, self.collector.symbol_widget):
            if not capture._can_switch():
                event.ignore()
                return
        if not self.editor.close():
            event.ignore()
            return
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args(argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["InkStruct"])
    app.setApplicationName("InkStruct")
    app.setOrganizationName("InkStruct")
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    window = InkStructWindow(workspace=args.workspace)
    if args.font:
        window.use_font(args.font)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
