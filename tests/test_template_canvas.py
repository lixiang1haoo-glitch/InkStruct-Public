"""Canvas edits preserve physical geometry and commit whole validated transactions."""

import os
import subprocess
import sys
from dataclasses import replace

import pytest

from inkstruct.document.template import Anchor, Region, TemplateRule
from inkstruct.document.template_authoring import new_template
from inkstruct.editor.template_geometry import (
    add_element,
    edit_element,
    move_element,
    move_vertex,
    resize_region,
)


def test_grouped_body_width_change_and_paper_validation():
    template = new_template()
    changed = resize_region(template.first.body, "br", (180, 270), 1)
    result = edit_element(template, "first", ("body", None), changed)
    assert result.first.body.width_mm == result.continuation.body.width_mm == 160
    assert result.first.body.height_mm == 240
    assert result.continuation.body.height_mm == 247
    with pytest.raises(ValueError, match="equal"):
        edit_element(template, "first", ("body", None), changed, link_body_width=False)
    with pytest.raises(ValueError, match="outside"):
        edit_element(template, "first", ("body", None), move_element(template.first.body, 100, 0))
    assert template.first.body.width_mm == 170


def test_noop_does_not_invalidate_calibration():
    template = replace(new_template(), calibration="user-measured")
    assert edit_element(template, "first", ("body", None), template.first.body) is template


def test_snap_translation_preserves_polyline_shape_and_name():
    rule = TemplateRule("frame", ((2.123456789, 3.5), (15.456, 3.8), (17, 6.1)))
    moved = move_element(rule, 10.13, 2.25, 1)
    assert moved.name == rule.name and moved.width_mm == rule.width_mm
    assert moved.points[0] == (12, 6)
    for a, b, c, d in zip(rule.points, rule.points[1:], moved.points, moved.points[1:]):
        assert (b[0] - a[0], b[1] - a[1]) == pytest.approx((d[0] - c[0], d[1] - c[1]))
    vertex = move_vertex(rule, 1, (20.1, 20.8), 1)
    assert vertex.points == (rule.points[0], (20, 21), rule.points[2])
    assert move_element(Anchor("a", 2, 3), 0.123456789, 0.5).x_mm == 2.123456789


@pytest.mark.parametrize(
    "corner,point,bounds",
    [
        ("tl", (9, 8), (9, 8, 30, 40)),
        ("tr", (35, 8), (10, 8, 35, 40)),
        ("bl", (9, 42), (9, 20, 30, 42)),
        ("br", (35, 42), (10, 20, 35, 42)),
    ],
)
def test_corner_resize(corner, point, bounds):
    assert resize_region(Region("a", 10, 20, 20, 20), corner, point).bounds == bounds


def test_creation_and_overlap_fail_closed():
    template = new_template()
    result, key = add_element(template, "first", "reserved", (80, 20), (20, 10), 1)
    assert key == ("reserved", 0)
    assert result.first.reserved[0].bounds == (20, 10, 80, 20)
    assert not template.first.reserved
    with pytest.raises(ValueError, match="overlap"):
        add_element(result, "first", "reserved", (20, 15), (60, 25))
    with pytest.raises(ValueError):
        resize_region(result.first.reserved[0], "br", (19, 9))
    with pytest.raises(ValueError):
        add_element(template, "first", "rules", (5, 5), (5, 5))
    other, key = add_element(result, "continuation", "anchors", (2, 3))
    assert key == ("anchors", 0) and other.first == result.first


def test_real_mouse_gestures_selection_resize_undo_and_calibration(tmp_path):
    pytest.importorskip("PySide6")
    program = r"""
import sys
from pathlib import Path
from PySide6 import QtWidgets, QtCore, QtTest
from dataclasses import replace
from inkstruct.document.template_authoring import read_template
from inkstruct.editor.template_designer import TemplateDesignerDialog
app=QtWidgets.QApplication([])
t=replace(read_template('configs/templates/generic-record-v1.json'),offset_x_mm=.123456789,offset_y_mm=.234567891)
d=TemplateDesignerDialog(t)
# More than two pixels per millimetre keeps integer mouse coordinates precise
# enough to assert a particular 1 mm snap cell at this fit-to-window scale.
d.resize(1300,1100);d.show();app.processEvents()
c=d.preview
for point in ((0,0),(20,10),(80.123,60.456)):
    recovered=c.to_mm(c.to_widget(point))
    assert max(abs(a-b) for a,b in zip(point,recovered)) < 1e-10

def drag(start,end,mod=QtCore.Qt.NoModifier):
    a,b=c.to_widget(start).toPoint(),c.to_widget(end).toPoint()
    QtTest.QTest.mousePress(c,QtCore.Qt.LeftButton,mod,a)
    QtTest.QTest.mouseMove(c,b,20)
    QtTest.QTest.mouseRelease(c,QtCore.Qt.LeftButton,mod,b)
    app.processEvents()

# Move a generic field with actual mouse events and snapped physical coordinates.
drag((70,15),(80,15))
assert d.configuration().first.reserved[0].x_mm == 30
assert d.configuration().first.reserved[0].width_mm == 100
assert d.element.currentData() == ('reserved',0)
assert d.configuration().offset_x_mm == t.offset_x_mm
d.json_editor.undo();assert d.configuration() == t
d.json_editor.redo();assert d.configuration().first.reserved[0].x_mm == 30
d.json_editor.undo()
# Invalid collision and out-of-paper drops do not mutate the JSON or undo history.
before=d.json_editor.toPlainText()
drag((70,15),(70,50));assert d.json_editor.toPlainText()==before
# Four-corner handles resize, linking continuation width in the same undo entry.
d.canvas_select(('body',None))
drag((190,277),(180,270))
assert d.configuration().first.body.width_mm == d.configuration().continuation.body.width_mm == 160
assert d.configuration().first.body.height_mm == 240
d.json_editor.undo();assert d.configuration() == t
# New generic region from empty space, independent of the existing specimen.
d.canvas_tool.setCurrentIndex(d.canvas_tool.findData('reserved'))
drag((140,10),(180,20))
assert len(d.configuration().first.reserved)==2
assert d.configuration().first.reserved[1].bounds == (140,10,180,20)
assert d.canvas_tool.currentData()=='select'
d.json_editor.undo();assert d.configuration()==t
# Anchors are created by clicking; their calibrated display maps back to local mm.
d.canvas_tool.setCurrentIndex(d.canvas_tool.findData('anchors'))
QtTest.QTest.mouseClick(c,QtCore.Qt.LeftButton,pos=c.to_widget((160,15)).toPoint())
assert d.configuration().first.anchors[-1].x_mm == 160
assert d.configuration().first.anchors[-1].y_mm == 15
d.json_editor.undo();assert d.configuration()==t
# Direct line drawing and vertex editing preserve intermediate points.
d.canvas_tool.setCurrentIndex(d.canvas_tool.findData('rules'))
drag((140,26),(180,26))
assert d.configuration().first.rules[-1].points == ((140,26),(180,26))
drag((180,26),(180,18))
assert d.configuration().first.rules[-1].points == ((140,26),(180,18))
# Esc during an active drag cancels the gesture without closing the dialog.
d.canvas_tool.setCurrentIndex(0)
d.canvas_select(('reserved',0))
before=d.json_editor.toPlainText()
a,b=c.to_widget((70,15)).toPoint(),c.to_widget((80,15)).toPoint()
QtTest.QTest.mousePress(c,QtCore.Qt.LeftButton,pos=a)
QtTest.QTest.mouseMove(c,b,20)
QtTest.QTest.keyClick(c,QtCore.Qt.Key_Escape)
QtTest.QTest.mouseRelease(c,QtCore.Qt.LeftButton,pos=b)
assert d.json_editor.toPlainText()==before and d.isVisible()
# Alt disables snapping; do not round a precision-bearing initial origin.
drag((70,15),(80.4,15),QtCore.Qt.AltModifier)
assert d.configuration().first.reserved[0].x_mm != round(d.configuration().first.reserved[0].x_mm)
d.json_editor.undo()
assert d.snap_grid.isChecked()
# A continuation gesture changes that face, keeping first-page source geometry.
d.face.setCurrentIndex(1)
first=d.configuration().first
drag((60,100),(70,100))
assert d.configuration().first==first
assert d.configuration().continuation.body.x_mm == 30
d.face.setCurrentIndex(0)
# Reference import is face-local, cancel-safe and undoable; it never edits pixels at source.
from PIL import Image
image_path=Path(sys.argv[1])/'reference.png'
Image.new('RGB',(300,400),'white').save(image_path)
original=image_path.read_bytes()
before=d.configuration()
QtWidgets.QFileDialog.getOpenFileName=lambda *args: (str(image_path),'')
d.import_background()
assert d.configuration().first.background is not None
assert d.configuration().continuation.background is None
assert image_path.read_bytes()==original
d.clear_background();assert d.configuration().first.background is None
d.json_editor.undo();assert d.configuration().first.background is not None
d.json_editor.undo();assert d.configuration()==before
app.processEvents()
d.grab().save(str(Path(sys.argv[1])/'canvas.png'))
d.reject();assert t.first.reserved[0].x_mm==20
d.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        check=False,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_reference_import_bounds_format_and_source_preservation(tmp_path):
    import io

    from PIL import Image

    from inkstruct.document.template_authoring import import_reference_image

    path = tmp_path / "image.jpg"
    Image.new("RGB", (1800, 1000), "white").save(path, "JPEG")
    before = path.read_bytes()
    reference = import_reference_image(path)
    assert path.read_bytes() == before
    with Image.open(io.BytesIO(reference.png_bytes())) as image:
        assert image.format == "PNG" and image.width == 1600
        assert image.height <= 1600
    path = tmp_path / "invalid.gif"
    Image.new("RGB", (2, 2), "white").save(path, "GIF")
    with pytest.raises(ValueError, match="PNG/JPEG"):
        import_reference_image(path)
