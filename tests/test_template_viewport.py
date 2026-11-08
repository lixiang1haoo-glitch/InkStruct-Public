"""Zoom/rulers/reference opacity are display state, not physical layout edits."""

import os
import subprocess
import sys
from dataclasses import replace

import pytest

from inkstruct.document.template_authoring import geometry_preview, new_template


@pytest.mark.parametrize("opacity", [-1, 1.1, float("nan"), float("inf"), "low"])
def test_invalid_reference_opacity_rejected(opacity):
    with pytest.raises(ValueError, match="opacity"):
        geometry_preview(new_template(), "first", background_opacity=opacity)


def test_opacity_never_changes_template_fields():
    template = replace(new_template(), offset_x_mm=0.123456789)
    assert geometry_preview(template, "first") == geometry_preview(
        template, "first", background_opacity=0.4
    )
    assert template.offset_x_mm == 0.123456789


def test_qt_zoom_pan_rulers_and_zoomed_drag(tmp_path):
    pytest.importorskip("PySide6")
    program = r"""
import sys,base64,io
from pathlib import Path
from hashlib import sha256
from dataclasses import replace
from PIL import Image
from PySide6 import QtWidgets,QtCore,QtGui,QtTest
from inkstruct.document.template_authoring import new_template
from inkstruct.document.template import TemplateBackground,Region
from inkstruct.editor.template_designer import TemplateDesignerDialog
app=QtWidgets.QApplication([])
buf=io.BytesIO();Image.new('RGB',(2,2),'red').save(buf,format='PNG');raw=buf.getvalue()
background=TemplateBackground(base64.b64encode(raw).decode(),sha256(raw).hexdigest())
t=new_template()
t=replace(t,offset_x_mm=.123456789,offset_y_mm=.234567891,
          first=replace(t.first,background=background,reserved=(Region('field',20,10,60,10),)))
d=TemplateDesignerDialog(t);d.resize(1300,1050);d.show();app.processEvents()
c,v=d.preview,d.canvas_view
original=d.json_editor.toPlainText()
assert not d.json_editor.document().isUndoAvailable()
assert v.horizontalScrollBar().maximum()==v.verticalScrollBar().maximum()==0

# Zoom around a point keeps it at the same screen location, within pixel rounding.
world=(100,140)
a=c.mapTo(v.viewport(),c.to_widget(world).toPoint())
v.set_zoom(2.5,a);app.processEvents()
b=c.mapTo(v.viewport(),c.to_widget(world).toPoint())
assert (a-b).manhattanLength()<=3,(a,b)
assert d.zoom_control.value()==250
assert v.horizontalScrollBar().maximum()>0 and v.verticalScrollBar().maximum()>0
for point in ((0,0),(20,10),(110.123456,200.56789)):
    recovered=c.to_mm(c.to_widget(point))
    assert max(abs(x-y) for x,y in zip(point,recovered))<1e-10

# Rulers refer to the physical paper, not the shifted content origin.
for axis,ruler in enumerate(v.rulers):
    ticks=ruler.tick_positions()
    assert ticks and any(major for _,_,major in ticks)
    origin=c.mapTo(v.viewport(),QtCore.QPoint(0,0))
    rect=c.paper_rect()
    scale=rect.width()/t.width_mm
    offset=origin.x()+rect.x() if axis==0 else origin.y()+rect.y()
    for value,pixel,major in ticks:
        assert abs(pixel-(offset+value*scale))<1e-8

# Actual wheel event uses the view-only zoom path with Ctrl.
pos=QtCore.QPointF(v.viewport().rect().center())
global_pos=QtCore.QPointF(v.viewport().mapToGlobal(pos.toPoint()))
event=QtGui.QWheelEvent(pos,global_pos,QtCore.QPoint(),QtCore.QPoint(0,120),
                       QtCore.Qt.NoButton,QtCore.Qt.ControlModifier,QtCore.Qt.NoScrollPhase,False)
QtWidgets.QApplication.sendEvent(v.viewport(),event);app.processEvents()
assert abs(v.zoom-3.0)<1e-9

# Middle-button drag pans the view without dragging any selected geometry.
v.horizontalScrollBar().setValue(v.horizontalScrollBar().maximum()//2)
v.verticalScrollBar().setValue(v.verticalScrollBar().maximum()//2)
x,y=v.horizontalScrollBar().value(),v.verticalScrollBar().value()
p=v.viewport().rect().center()
QtTest.QTest.mousePress(v.viewport(),QtCore.Qt.MiddleButton,pos=p)
QtTest.QTest.mouseMove(v.viewport(),p+QtCore.QPoint(30,25),20)
QtTest.QTest.mouseRelease(v.viewport(),QtCore.Qt.MiddleButton,pos=p+QtCore.QPoint(30,25))
assert abs(v.horizontalScrollBar().value()-(x-30))<=1
assert abs(v.verticalScrollBar().value()-(y-25))<=1
assert d.json_editor.toPlainText()==original
# Escape rolls back an in-flight pan without closing the designer.
x,y=v.horizontalScrollBar().value(),v.verticalScrollBar().value()
QtTest.QTest.mousePress(v.viewport(),QtCore.Qt.MiddleButton,pos=p)
QtTest.QTest.mouseMove(v.viewport(),p+QtCore.QPoint(20,15),20)
QtTest.QTest.keyClick(c,QtCore.Qt.Key_Escape)
QtTest.QTest.mouseRelease(v.viewport(),QtCore.Qt.MiddleButton,pos=p+QtCore.QPoint(20,15))
assert v.horizontalScrollBar().value()==x and v.verticalScrollBar().value()==y
assert d.isVisible()

# Reference opacity updates pixels but not JSON, selection, undo, or other pages.
def color_at(opacity):
    d.opacity_control.setValue(opacity)
    image=QtGui.QImage(210,297,QtGui.QImage.Format_ARGB32);image.fill(QtCore.Qt.white)
    painter=QtGui.QPainter(image);c.renderer().render(painter);painter.end()
    return image.pixelColor(2,2)
assert color_at(0).green()==255
assert color_at(100).green()==0
assert color_at(40).green()>100
assert d.json_editor.toPlainText()==original
assert not d.json_editor.document().isUndoAvailable()
d.ruler_toggle.setChecked(False);app.processEvents()
assert all(r.isHidden() for r in v.rulers)
d.ruler_toggle.setChecked(True);app.processEvents()
assert d.configuration()==t

# Zooming during a draw cancels the candidate, never commits unintended geometry.
d.fit_button.click();app.processEvents()
assert v.zoom==1 and d.zoom_control.value()==100
assert v.horizontalScrollBar().maximum()==v.verticalScrollBar().maximum()==0
a,b=c.to_widget((40,15)).toPoint(),c.to_widget((50,15)).toPoint()
QtTest.QTest.mousePress(c,QtCore.Qt.LeftButton,pos=a)
QtTest.QTest.mouseMove(c,b,20)
v.set_zoom(2)
QtTest.QTest.mouseRelease(c,QtCore.Qt.LeftButton,pos=b)
assert d.configuration()==t

# Dragging at high zoom and a nonzero horizontal scroll still edits exact millimetres.
v.horizontalScrollBar().setValue(20);v.verticalScrollBar().setValue(0)
a,b=c.to_widget((40,15)).toPoint(),c.to_widget((50,15)).toPoint()
QtTest.QTest.mousePress(c,QtCore.Qt.LeftButton,pos=a)
QtTest.QTest.mouseMove(c,b,20)
QtTest.QTest.mouseRelease(c,QtCore.Qt.LeftButton,pos=b)
app.processEvents()
assert d.configuration().first.reserved[0].x_mm==30
assert d.configuration().first.reserved[0].width_mm==60
assert d.configuration().offset_x_mm==t.offset_x_mm
assert d.configuration().continuation==t.continuation
d.json_editor.undo();assert d.configuration()==t
# Zoom and opacity are independent from source undo and survive a template refresh.
assert v.zoom==2 and c.background_opacity==.4
d.resize(1180,900);app.processEvents()
d.fit_button.click();app.processEvents()
assert v.horizontalScrollBar().maximum()==v.verticalScrollBar().maximum()==0
assert d.configuration()==t
d.grab().save(str(Path(sys.argv[1])/'viewport.png'))
d.reject();d.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
