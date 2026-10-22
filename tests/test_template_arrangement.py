"""Multiple selections edit one final validated arrangement with exact identities."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from inkstruct.document.template import Anchor, Region, TemplateRule
from inkstruct.document.template_authoring import new_template
from inkstruct.editor.template_geometry import (
    arrange_selection,
    element_at,
    element_bounds,
    move_selection,
)


def arrangement_template():
    base = new_template()
    face = replace(
        base.first,
        body=Region("body", 10, 100, 180, 177),
        reserved=(
            Region("a", 20, 10, 20, 10),
            Region("b", 70, 35, 30, 15),
            Region("c", 150, 70, 40, 20),
        ),
        anchors=(Anchor("baseline", 22.123456789, 17),),
        rules=(TemplateRule("underline", ((20.1, 23), (30, 23.2), (40, 23))),),
    )
    return replace(base, first=face, continuation=replace(base.continuation, body=face.body))


KEYS = (("reserved", 0), ("reserved", 1), ("reserved", 2))


@pytest.mark.parametrize(
    "operation,axis,target",
    [
        ("left", 0, 20),
        ("right", 2, 190),
        ("top", 1, 10),
        ("bottom", 3, 90),
        ("center-x", 0, 105),
        ("center-y", 1, 50),
    ],
)
def test_alignment_to_selection_envelope(operation, axis, target):
    template = arrangement_template()
    result = arrange_selection(template, "first", KEYS, operation)
    for key in KEYS:
        b = element_bounds(element_at(result, "first", key))
        observed = (b[axis] + b[axis + 2]) / 2 if operation.startswith("center") else b[axis]
        assert observed == target
    for old, new in zip(template.first.reserved, result.first.reserved):
        assert (old.name, old.width_mm, old.height_mm) == (new.name, new.width_mm, new.height_mm)
    assert result.continuation == template.continuation
    assert result.first.anchors == template.first.anchors
    assert result.first.rules == template.first.rules


@pytest.mark.parametrize(
    "operation,axis,expected",
    [
        ("distribute-x", 0, 40),
        ("distribute-y", 1, 17.5),
    ],
)
def test_distribution_equal_clear_gaps_and_fixed_endpoints(operation, axis, expected):
    template = arrangement_template()
    result = arrange_selection(template, "first", tuple(reversed(KEYS)), operation)
    regions = result.first.reserved
    assert regions[0] == template.first.reserved[0]
    assert regions[-1] == template.first.reserved[-1]
    assert regions[1].bounds[axis] - regions[0].bounds[axis + 2] == expected
    assert regions[2].bounds[axis] - regions[1].bounds[axis + 2] == expected


def test_group_snap_uses_one_translation_and_keeps_relative_positions():
    template = arrangement_template()
    keys = (("reserved", 0), ("anchors", 0), ("rules", 0))
    result = move_selection(template, "first", keys, 8.4, 4.7, 1)
    assert result.first.reserved[0].x_mm == 28
    assert result.first.reserved[0].y_mm == 15
    assert result.first.anchors[0].x_mm == pytest.approx(30.123456789)
    assert result.first.anchors[0].y_mm == 22
    assert result.first.rules[0].points == tuple(
        (x + 8, y + 5) for x, y in template.first.rules[0].points
    )
    assert result.first.reserved[1:] == template.first.reserved[1:]


def test_group_validation_is_atomic_even_when_old_positions_would_overlap():
    base = arrangement_template()
    face = replace(base.first, reserved=(Region("a", 20, 10, 20, 10), Region("b", 40, 10, 20, 10)))
    template = replace(base, first=face)
    result = move_selection(template, "first", KEYS[:2], 20, 0)
    assert result.first.reserved[0].x_mm == 40
    assert result.first.reserved[1].x_mm == 60
    with pytest.raises(ValueError, match="overlap"):
        arrange_selection(template, "first", KEYS[:2], "left")
    assert template.first.reserved == face.reserved


@pytest.mark.parametrize(
    "keys,operation", [(KEYS[:1], "left"), (KEYS[:2], "distribute-x"), (KEYS, "unknown")]
)
def test_invalid_commands_fail_without_changing_template(keys, operation):
    with pytest.raises(ValueError):
        arrange_selection(arrangement_template(), "first", keys, operation)


def test_zero_change_preserves_calibration_and_empty_group_is_noop():
    base = arrangement_template()
    assert move_selection(base, "first", (), 10, 10) is base
    done = arrange_selection(base, "first", KEYS, "left")
    done = replace(done, calibration="user-measured")
    assert arrange_selection(done, "first", KEYS, "left") is done


def test_real_mouse_multi_selection_box_group_drag_arrange_and_undo(tmp_path):
    pytest.importorskip("PySide6")
    program = r"""
from pathlib import Path
import sys
from PySide6 import QtWidgets, QtCore, QtTest
from inkstruct.editor.template_designer import TemplateDesignerDialog
from test_template_arrangement import arrangement_template, KEYS
app=QtWidgets.QApplication([])
t=arrangement_template()
d=TemplateDesignerDialog(t);d.resize(1300,950);d.show();app.processEvents()
c=d.preview

def click(p,mod=QtCore.Qt.NoModifier):
    QtTest.QTest.mouseClick(c,QtCore.Qt.LeftButton,mod,c.to_widget(p).toPoint())
    app.processEvents()

def drag(a,b,mod=QtCore.Qt.NoModifier):
    a,b=c.to_widget(a).toPoint(),c.to_widget(b).toPoint()
    QtTest.QTest.mousePress(c,QtCore.Qt.LeftButton,mod,a)
    QtTest.QTest.mouseMove(c,b,20)
    QtTest.QTest.mouseRelease(c,QtCore.Qt.LeftButton,mod,b)
    app.processEvents()

def choose(keys):
    c.set_selections(keys,notify=True)
    assert c.selections == tuple(keys)

# Shift toggles preserve a deterministic selection set and primary property target.
click((30,15));click((85,40),QtCore.Qt.ShiftModifier);click((165,80),QtCore.Qt.ShiftModifier)
assert c.selections==KEYS and d.element.currentData()==KEYS[-1]
assert '3' in d.selection_count.text()
click((85,40),QtCore.Qt.ShiftModifier)
assert c.selections==(KEYS[0],KEYS[2])
click((85,40),QtCore.Qt.ShiftModifier)
assert set(c.selections)==set(KEYS)
# Use actual arrangement controls. One undo restores all original positions.
d.arrange_mode.setCurrentIndex(d.arrange_mode.findData('distribute-x'))
d.arrange_button.click()
assert d.configuration().first.reserved[1].x_mm==80
assert set(c.selections)==set(KEYS)
d.json_editor.undo();assert d.configuration()==t
# A group drag preserves field/anchor/line relationships, names and whole transaction.
keys=(KEYS[0],('anchors',0),('rules',0))
choose(keys)
drag((30,15),(40,20))
assert d.configuration().first.reserved[0].x_mm==30
assert d.configuration().first.anchors[0].x_mm==t.first.anchors[0].x_mm+10
assert d.configuration().first.rules[0].points==tuple((x+10,y+5) for x,y in t.first.rules[0].points)
assert c.selections==keys
d.json_editor.undo();assert d.configuration()==t
# A drop outside the page leaves the entire JSON unchanged.
choose(KEYS)
before=d.json_editor.toPlainText()
drag((165,80),(195,80))
assert d.json_editor.toPlainText()==before
# Explicit marquee includes only complete elements, and source is untouched.
d.canvas_tool.setCurrentIndex(d.canvas_tool.findData('marquee'))
drag((15,5),(105,52))
assert set(c.selections)=={KEYS[0],KEYS[1],('anchors',0),('rules',0)}
assert d.configuration()==t
# Reverse rectangle plus Shift adds without clearing earlier selection.
drag((195,95),(145,65),QtCore.Qt.ShiftModifier)
assert set(c.selections)=={*KEYS,('anchors',0),('rules',0)}
# Inactive rectangle selects nothing; Esc cancels an in-flight marquee.
before=c.selections
a,b=c.to_widget((1,1)).toPoint(),c.to_widget((200,95)).toPoint()
QtTest.QTest.mousePress(c,QtCore.Qt.LeftButton,pos=a)
QtTest.QTest.mouseMove(c,b,20)
QtTest.QTest.keyClick(c,QtCore.Qt.Key_Escape)
QtTest.QTest.mouseRelease(c,QtCore.Qt.LeftButton,pos=b)
assert c.selections==before and d.isVisible()
# Coordinate editing targets the primary element; other selected objects are unchanged.
d.canvas_tool.setCurrentIndex(0)
choose(KEYS)
for row in range(d.element_properties.rowCount()):
    if d.element_properties.item(row,0).data(QtCore.Qt.UserRole)=='x_mm':
        d.element_properties.item(row,1).setText('145')
        break
assert not d.arrange_button.isEnabled()
d.apply_element.click()
assert d.configuration().first.reserved[:2]==t.first.reserved[:2]
assert d.configuration().first.reserved[2].x_mm==145
d.json_editor.undo();assert d.configuration()==t
choose(KEYS)
d.arrange_mode.setCurrentIndex(d.arrange_mode.findData('left'));d.arrange_button.click()
assert all(r.x_mm==20 for r in d.configuration().first.reserved)
app.processEvents()
d.grab().save(str(Path(sys.argv[1])/'arranged.png'))
d.json_editor.undo();assert d.configuration()==t
d.face.setCurrentIndex(1);assert len(c.selections)<=1
d.face.setCurrentIndex(0)
# Blank click clears selection; explicit property choice restores single selection.
click((205,95));assert c.selections==()
d.canvas_select(KEYS[1]);assert c.selections==(KEYS[1],)
d.reject();assert t.first.reserved[1].x_mm==70
d.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONPATH": str(Path(__file__).parent),
        },
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
