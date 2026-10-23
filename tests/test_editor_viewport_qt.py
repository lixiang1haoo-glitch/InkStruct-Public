"""Viewport changes preserve document geometry and keep grouped controls accessible."""

import os
import subprocess
import sys

import pytest

PROGRAM = r"""
import json, sys, time
from hashlib import sha256
from pathlib import Path
from PySide6 import QtCore, QtTest, QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.wrapping import WrappingLayout
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page
from inkstruct.plotter.svg import page_svg
app = QtWidgets.QApplication([])
root = Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
w = MixedWindow(source='12.3\n\n| 1 | 2 |\n|---|---|\n| 3.4 | 5.6 |\n\n' + '\n\n'.join(['78.9'] * 30))
w.show()
if len(sys.argv) > 2:
    w.load_project_path(Path(sys.argv[2]))
end = time.monotonic() + 20
while time.monotonic() < end:
    app.processEvents()
    if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
        break
    QtTest.QTest.qWait(10)
else:
    raise AssertionError(w.status.text())
assert w.snapshot.exportable, w.snapshot.diagnostics
snapshot, revision, raw = w.snapshot, w.revision, w.buffer.raw
selections = w.resolver.selection_records()
def svgs():
    return [page_svg(route_page(p, optimize=True).page) for p in plan_from_snapshot(w.snapshot).pages]
original = svgs()
# A long external resource path must wrap instead of setting the minimum window width.
w.run_label.setText('/a-long-resource-directory/' * 12)
measurements = []
for width, height in ((1440, 900), (1000, 700), (1024, 768)):
    w.resize(width, height); app.processEvents()
    assert w.width() == width and w.height() == height, w.size()
    layout = w.centralWidget().layout()
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if not isinstance(item, WrappingLayout):
            continue
        controls = [item.itemAt(n) for n in range(item.count()) if not item.itemAt(n).isEmpty()]
        for n, control in enumerate(controls):
            assert item.geometry().contains(control.geometry()), (i, control.geometry(), item.geometry())
            assert all(not control.geometry().intersects(other.geometry()) for other in controls[n+1:])
            widget = control.widget()
            if widget.layout():
                for child in widget.findChildren(QtWidgets.QWidget, options=QtCore.Qt.FindDirectChildrenOnly):
                    assert widget.rect().contains(child.geometry()), (widget.size(), child.geometry())
    assert w.editor.width() >= 200 and w.editor.height() >= 80, w.editor.size()
    assert w.scroll.viewport().width() >= 300 and w.scroll.viewport().height() >= 100, w.scroll.size()
    for zoom in range(w.zoom.count()):
        w.zoom.setCurrentIndex(zoom)
        for page in range(1, len(snapshot.pages) + 1):
            w.page_picker.setValue(page); app.processEvents()
        w.page_picker.setValue(1); app.processEvents()
        f = next(f for f in snapshot.pages[0].fragments if f.asset_id and f.text)
        point = w.canvas.rect_for(f).center().toPoint()
        w.scroll.ensureVisible(point.x(), point.y()); app.processEvents()
        assert w.scroll.viewport().rect().contains(w.canvas.mapTo(w.scroll.viewport(), point))
        QtTest.QTest.mouseClick(w.canvas, QtCore.Qt.LeftButton, pos=point)
        assert w.editor.textCursor().selectedText() == f.text
        assert w.snapshot is snapshot and w.revision == revision
        assert w.buffer.raw == raw and w.resolver.selection_records() == selections
        assert svgs() == original
    measurements.append({'window': [w.width(), w.height()], 'source': [w.editor.width(), w.editor.height()],
                         'preview': [w.scroll.viewport().width(), w.scroll.viewport().height()]})
    w.zoom.setCurrentIndex(1); app.processEvents()
    point = w.canvas.rect_for(f).center().toPoint()
    w.scroll.ensureVisible(point.x(), point.y()); app.processEvents()
    assert w.grab().save(str(root / f'window-{width}.png'))
for i, svg in enumerate(original):
    (root / f'page-{i+1:03}.svg').write_text(svg)
(root / 'verification.json').write_text(json.dumps({'device_pixel_ratio': w.devicePixelRatioF(),
    'measurements': measurements, 'pages': len(original), 'zoom_levels': w.zoom.count(),
    'snapshot_unchanged': True, 'source_navigation': True,
    'optimized_svg_sha256': [sha256(s.encode()).hexdigest() for s in original]}, indent=2))
w.dirty = False; w.close()
"""


@pytest.mark.parametrize("scale", ["1", "1.5", "2"])
def test_viewport_keeps_controls_and_frozen_export(tmp_path, scale):
    pytest.importorskip("PySide6")
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": scale},
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
