from __future__ import annotations

from pathlib import Path

from ..scene.schema import LayoutSnapshot
from .pages import export_pages, page_svg


def create_preview_window(snapshot: LayoutSnapshot, parent=None):
    """Read-only P1 preview. Qt receives exactly the SVG geometry used in export."""
    try:
        from PySide6 import QtCore, QtSvgWidgets, QtWidgets
    except ImportError as error:
        raise RuntimeError("Page preview requires InkStruct's desktop extra (PySide6)") from error

    window = QtWidgets.QMainWindow(parent)
    window.setWindowFlag(QtCore.Qt.WindowType.Window, True)
    window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
    window.setWindowTitle("InkStruct 页面预览")
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    body = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(body)
    status = (
        f"共 {len(snapshot.pages)} 页 · 可导出"
        if snapshot.exportable
        else f"共 {len(snapshot.pages)} 页 · {len(snapshot.diagnostics)} 项问题，正式导出已阻止"
    )
    layout.addWidget(QtWidgets.QLabel(status))
    export_button = QtWidgets.QPushButton("导出页面 SVG 和 PNG…")
    export_button.setEnabled(snapshot.exportable)

    def export():
        target, _ = QtWidgets.QFileDialog.getSaveFileName(window, "指定新的页面输出文件夹")
        if target:
            try:
                export_pages(snapshot, Path(target))
            except (OSError, ValueError) as error:
                QtWidgets.QMessageBox.critical(window, "导出失败", str(error))
            else:
                QtWidgets.QMessageBox.information(window, "导出完成", f"页面已保存到 {target}")

    export_button.clicked.connect(export)
    layout.addWidget(export_button)
    for diagnostic in snapshot.diagnostics[:100]:
        label = QtWidgets.QLabel()
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        label.setText(
            f"{diagnostic.code} [{diagnostic.span.start}:{diagnostic.span.end}] "
            + diagnostic.message
        )
        label.setWordWrap(True)
        layout.addWidget(label)
    if len(snapshot.diagnostics) > 100:
        layout.addWidget(QtWidgets.QLabel("仅显示前 100 项问题；调试导出包含完整诊断。"))
    page_picker = QtWidgets.QSpinBox()
    page_picker.setObjectName("page_picker")
    page_picker.setRange(1, len(snapshot.pages))
    page_picker.setPrefix("第 ")
    page_picker.setSuffix(f" / {len(snapshot.pages)} 页")
    layout.addWidget(page_picker)
    widget = QtSvgWidgets.QSvgWidget()
    scale = 3.0
    widget.setFixedSize(
        round(snapshot.page_profile.width_mm * scale),
        round(snapshot.page_profile.height_mm * scale),
    )
    layout.addWidget(widget, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)

    def load_page(number):
        widget.load(
            QtCore.QByteArray(
                page_svg(snapshot, number - 1, debug=not snapshot.exportable).encode()
            )
        )

    page_picker.valueChanged.connect(load_page)
    load_page(1)
    scroll.setWidget(body)
    window.setCentralWidget(scroll)
    window.resize(760, 900)
    return window


def show_preview(snapshot: LayoutSnapshot) -> int:
    try:
        from PySide6 import QtWidgets
    except ImportError as error:
        raise RuntimeError("Page preview requires InkStruct's desktop extra (PySide6)") from error

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = create_preview_window(snapshot)
    window.show()
    return application.exec()
