"""Optional Qt integration runs in a separate process with no user windows."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None, reason="desktop extra not installed"
)
def test_qt_preview_uses_full_paper_and_navigates_pages(tmp_path):
    program = r"""
from PySide6 import QtCore, QtGui, QtSvg, QtSvgWidgets, QtWidgets
from inkstruct.document.source import parse_plain_text
from inkstruct.document.schema import PageProfile
from inkstruct.assets.glyph_provider import GlyphProvider
from inkstruct.layout.plain import layout_document
from inkstruct.renderers.qt import create_preview_window
from inkstruct.renderers.pages import page_svg
app = QtWidgets.QApplication([])
doc = parse_plain_text("\n" * 10, page=PageProfile(100, 100, 10))
snapshot = layout_document(doc, GlyphProvider({}))
assert len(snapshot.pages) > 1
window = create_preview_window(snapshot)
window.show()
app.processEvents()
widgets = window.findChildren(QtSvgWidgets.QSvgWidget)
assert len(widgets) == 1
picker = window.findChild(QtWidgets.QSpinBox, "page_picker")
picker.setValue(2)
app.processEvents()
assert widgets[0].renderer().isValid()
renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(page_svg(snapshot, 0).encode()))
image = QtGui.QImage(1000, 1000, QtGui.QImage.Format.Format_RGB32)
image.fill(QtCore.Qt.GlobalColor.red)
painter = QtGui.QPainter(image)
renderer.render(painter, QtCore.QRectF(0, 0, 1000, 1000))
painter.end()
for x, y in [(0, 0), (500, 500), (998, 998), (998, 0), (0, 998)]:
    assert image.pixelColor(x, y).name() == "#ffffff", (x, y)
window.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
