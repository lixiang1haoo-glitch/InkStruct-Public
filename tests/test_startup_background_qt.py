"""The validated blank template can paint before the raster service is available."""

import os
import subprocess
import sys


def test_startup_template_draws_directly_and_drops_the_image_on_change(tmp_path):
    program = r"""
import base64
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event
import sys

from PIL import Image
from PySide6 import QtGui, QtWidgets

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import FlowTemplate, PageLayout
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import TemplateBackground
from inkstruct.editor.continuous_preview import ContinuousPageCanvas, PreviewScrollArea
from inkstruct.editor.mixed import MixedWindow, startup_page
from inkstruct.scene.schema import PaintOp

app = QtWidgets.QApplication([])
stream = BytesIO()
Image.new("RGB", (64, 64), "#2374af").save(stream, format="PNG")
raw = stream.getvalue()
background = TemplateBackground(base64.b64encode(raw).decode(), sha256(raw).hexdigest())
layout = PageLayout("first", "PDF 第 1 页", background=background)
template = FlowTemplate(kind="custom", layouts=(layout,), loop_pages=("first",))
snapshot, kind, image = startup_page({
    "session": SourceSession(), "revision": 1, "resolver": AssetResolver(),
    "run": str(Path(sys.argv[1]) / "unavailable.inkfont"), "symbols": "",
    "page": PageProfile(), "style": StyleProfile(), "flow": FlowStyle(template=template),
    "cancelled": Event(), "cache": None,
})
assert kind == "startup-page" and image.pixelColor(32, 32) == QtGui.QColor("#2374af")
canvas = ContinuousPageCanvas()
scroll = PreviewScrollArea()
scroll.setWidget(canvas)
scroll.resize(500, 500)
painted = []
canvas.first_page_painted.connect(painted.append)
scroll.show()
canvas.load_page(snapshot, 0, startup_image=image)
app.processEvents()
assert canvas.render_jobs == 0 and canvas.viewport_ready()
assert painted == [snapshot]
equivalent = replace(snapshot, revision=2)
canvas.load_page(equivalent, 0)
assert canvas._startup_background[0] is snapshot.pages[0]
ink = PaintOp("current", ((40, 40), (42, 42)), 0.3)
changed = replace(equivalent, pages=(replace(snapshot.pages[0], paint_ops=(ink,)),))
canvas.load_page(changed, 0)
assert canvas._startup_background is None
canvas.stop_rendering()
scroll.close()

w = MixedWindow()
w.flow = FlowStyle(template=template)
w.run_path = str(Path(sys.argv[1]) / "unavailable.inkfont")
w.begin_startup_preview()
assert w.partial_kind == "startup-page" and w.canvas._startup_background
first = w.canvas.snapshot.pages[0]
w.schedule_layout()
assert w.canvas.snapshot.pages[0] is first
assert w.partial_revision == w.canvas.snapshot.revision == w.revision
assert not w.machine_export.isEnabled()
w.editor.insertPlainText("12")
assert w.partial_revision is None and w.canvas._startup_background is None
w.timer.stop()
w.dirty = False
w.close()
"""
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, encoding="utf-8", timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
