"""Math dimensions apply atomically and survive the actual editor's save/reopen."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec('PySide6') is None, reason='desktop extra missing')
def test_category_rows_fit_large_windows_fonts_without_overlap():
    program = r'''
from PySide6 import QtCore, QtGui, QtWidgets, QtTest
from inkstruct.editor.math_settings import MathSettingsDialog, GROUPS
from inkstruct.math.style import MathStyle
app = QtWidgets.QApplication([])
for points in (9, 14, 20):
    app.setFont(QtGui.QFont('Microsoft YaHei UI', points))
    d = MathSettingsDialog(MathStyle()); d.show(); app.processEvents()
    height = d.categories.fontMetrics().height()
    for index, (title, *_) in enumerate(GROUPS):
        item = d.categories.item(index)
        d.categories.scrollToItem(item); app.processEvents()
        rect = d.categories.visualItemRect(item)
        assert rect.height() >= height + 20, (points, title, rect.height(), height)
        assert rect.width() >= d.categories.fontMetrics().horizontalAdvance(title) + 16
        QtTest.QTest.mouseClick(d.categories.viewport(), QtCore.Qt.LeftButton, pos=rect.center())
        assert d.category_title.text() == title
    d.close()
'''
    result = subprocess.run([sys.executable, '-c', program],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_sample_construction_choices_preview_cancel_reset_and_persist(tmp_path):
    program = r"""
import sys
sys.path.insert(0, 'tests')
from pathlib import Path
from unittest.mock import patch
from PySide6 import QtWidgets
from test_math_sample_constructions import resolver
from inkstruct.editor.math_settings import MathSettingsDialog
from inkstruct.math.style import MathStyle
from inkstruct.document.styles import FlowStyle
from inkstruct.document.editing import SourceSession
from inkstruct.document.package import save_package,load_package
from inkstruct.document.schema import PageProfile,StyleProfile
app=QtWidgets.QApplication([])
r=resolver();original=MathStyle()
d=MathSettingsDialog(original,resolver=r);d.show();app.processEvents()
for index,key in [(3,'fraction_source'),(4,'radical_source'),(7,'delimiter_source')]:
 d.categories.setCurrentRow(index)
 d.sources[key].setCurrentIndex(d.sources[key].findData('sample'))
 d.refresh_preview()
 assert d.preview.box.ready, d.preview_status.text()
 assert all(rule.asset_id for rule in d.preview.box.rules if key!='delimiter_source' or 'delimiter' in rule.occurrence_id)
 assert getattr(d.configuration(),key)=='sample'
before=d.configuration()
d.reset_category();assert d.configuration().delimiter_source=='sample'
d.categories.setCurrentRow(3)
d.sources['fraction_source'].setCurrentIndex(d.sources['fraction_source'].findData('geometric'))
d.reset_category();assert d.configuration().fraction_source=='sample'
d.reject();assert original==MathStyle() and not r.selections
path=Path(sys.argv[1])/'sources.inkdoc'
save_package(path,SourceSession(r'$\sqrt{12}$'),r,PageProfile(),StyleProfile(),flow=FlowStyle(math=before))
assert load_package(path).flow.math==before
class LinkedFont:
 def glyphs(self, characters, *, reuse):
  assert '√' in characters and any(g.character=='√' for g in reuse)
  return ()
with patch('inkstruct.fonts.core.cached_font', return_value=LinkedFont()):
 d = MathSettingsDialog(original,resolver=r,font_path=path.with_suffix('.inkfont'))
 d.categories.setCurrentRow(4);d.refresh_preview()
 assert '√' not in d.preview_resolver.pools  # no fallback to the other font's recorded root
 assert '1' in d.preview_resolver.pools  # ordinary numeric fallback still applies
 assert d.print_preview.box.ready
print('sample sources Qt passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_math_settings_and_editor_roundtrip(tmp_path):
    program = r"""
import sys, time
from pathlib import Path
from PySide6 import QtCore, QtWidgets, QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.math_settings import MathSettingsDialog
from inkstruct.editor.code_settings import CodeSettingsDialog
from inkstruct.document.code_style import CodeStyle
from inkstruct.math.style import MathStyle
from inkstruct.document.package import load_package

app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, sys.argv[1])
style = MathStyle(em_mm=6.123456789, axis_em=.251234567)
d = MathSettingsDialog(style)
assert d.configuration() == style
d.controls['em_mm'].setValue(7)
d.reject()
assert style.em_mm == 6.123456789
c = CodeSettingsDialog(CodeStyle(advance_mm=4.123456789))
assert c.configuration().advance_mm == 4.123456789
c.controls['advance_mm'].setValue(5)
c.reject()
assert c.original.advance_mm == 4.123456789

w = MixedWindow(source='1 $12.50$ 2')
w.show()
def ready():
    end = time.monotonic() + 10
    while time.monotonic() < end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
assert w.snapshot.exportable
old_table = w.flow.table
def accept(dialog):
    dialog.controls['em_mm'].setValue(7.25)
    dialog.controls['fraction_clearance_em'].setValue(30)
    dialog.controls['script_scale'].setValue(75)
    dialog.controls['limits_scale'].setValue(85)
    assert 'script_clearance_em' not in dialog.controls
    dialog.controls['tag_gap_em'].setValue(150)
    dialog.controls['tag_scale'].setValue(80)
    dialog.controls['small_matrix_scale'].setValue(85)
    dialog.controls['array_rule_clearance_em'].setValue(35)
    dialog.controls['accent_clearance_em'].setValue(30)
    dialog.controls['accent_height_em'].setValue(40)
    dialog.controls['alignment_row_gap_em'].setValue(90)
    dialog.controls['alignment_pair_gap_em'].setValue(180)
    dialog.alignment.setCurrentIndex(dialog.alignment.findData('left'))
    return QtWidgets.QDialog.DialogCode.Accepted
MathSettingsDialog.exec = accept
w.math_settings(); ready()
assert w.flow.math.em_mm == 7.25 and w.flow.table == old_table
assert w.flow.math.fraction_clearance_em == .3 and w.flow.math.script_scale == .75
assert w.flow.math.limits_scale == .85
def accept_code(dialog):
    dialog.controls['em_mm'].setValue(3.5)
    dialog.tabs.setValue(3)
    dialog.wrap.setChecked(True)
    return QtWidgets.QDialog.DialogCode.Accepted
CodeSettingsDialog.exec = accept_code
w.code_settings(); ready()
assert w.flow.code.em_mm == 3.5 and w.flow.code.tab_columns == 3 and w.flow.code.wrap_lines
before = w.snapshot
path = Path(sys.argv[1]) / 'formula.inkdoc'
QtWidgets.QFileDialog.getSaveFileName = lambda *a, **k: (str(path), '')
assert w.save_project()
assert load_package(path).flow.math == w.flow.math
assert load_package(path).flow.code == w.flow.code
w.load_project_path(path); ready()
assert w.snapshot.pages == before.pages
assert w.flow.math.tag_scale == .8 and w.flow.math.tag_gap_em == 1.5
assert w.flow.math.small_matrix_scale == .85 and w.flow.math.array_rule_clearance_em == .35
assert w.flow.math.accent_clearance_em == .3 and w.flow.math.accent_height_em == .4
assert w.flow.math.display_align == 'left'
assert w.flow.math.alignment_row_gap_em == .9 and w.flow.math.alignment_pair_gap_em == 1.8
w.mode_picker.setCurrentIndex(w.mode_picker.findData('plain-text'))
assert not w.math_settings_button.isEnabled()
assert not w.code_settings_button.isEnabled()
w.dirty = False; w.close()
print('Math UI acceptance passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-12000:]


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_graphical_categories_live_geometry_percentages_and_transaction(tmp_path):
    program = r"""
from PySide6 import QtWidgets,QtCore
from inkstruct.editor.math_settings import MathSettingsDialog,GROUPS
from inkstruct.math.style import MathStyle
from inkstruct.assets.resolver import AssetResolver
app=QtWidgets.QApplication([])
r=AssetResolver(builtin_numbers=True)
style=MathStyle(em_mm=6.123456789,axis_em=.251234567)
d=MathSettingsDialog(style,resolver=r);d.show();app.processEvents()
assert d.configuration()==style and not r.selections
assert len(GROUPS)==11 and d.preview.box.ready
for i in range(len(GROUPS)):
 d.categories.setCurrentRow(i);d.refresh_preview();app.processEvents()
 assert d.preview.box is not None
 assert d.panels.currentIndex()==i
 assert d.controls['em_mm'].isVisible()==(i==0)
d.categories.setCurrentRow(10);d.refresh_preview();assert d.preview.box.ready
before=d.preview.box.ascent
d.controls['accent_height_em'].setValue(80);d.refresh_preview();assert d.preview.box.ascent>before
d.reset_category();assert d.configuration().accent_height_em==.18
d.categories.setCurrentRow(9);d.refresh_preview();assert d.preview.box.ready
before=d.preview.box.width
d.controls['tag_gap_em'].setValue(180);d.refresh_preview();assert d.preview.box.width>before
d.reset_category();assert d.configuration().tag_gap_em==1
d.categories.setCurrentRow(8);d.refresh_preview()
assert d.print_preview.box.ready
before_height=d.preview.box.ascent+d.preview.box.descent
d.controls['alignment_row_gap_em'].setValue(120);d.refresh_preview()
assert d.preview.box.ascent+d.preview.box.descent>before_height
d.reset_category();assert d.configuration().alignment_row_gap_em==.5
d.categories.setCurrentRow(3);d.refresh_preview()
before=d.preview.box
d.controls['fraction_clearance_em'].setValue(80)
d.refresh_preview()
assert d.configuration().fraction_clearance_em==.8
assert d.preview.box.width>before.width
assert not r.selections
d.reset_category();assert d.configuration().fraction_clearance_em==.06
d.categories.setCurrentRow(0)
d.points.setValue(18)
assert abs(d.configuration().em_mm-6.35)<1e-4
assert abs(d.points.value()-18)<1e-4
d.categories.setCurrentRow(5);d.example_choice.setCurrentIndex(1);d.refresh_preview()
assert '缺少字形' in d.preview_status.text() and not d.preview.box.ready
d.reject();assert style.em_mm==6.123456789 and not r.selections
d.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_live_measurements_semantics_and_small_window():
    program = r"""
from PySide6 import QtCore, QtWidgets, QtTest
from inkstruct.editor.math_settings import MathSettingsDialog, GROUPS
from inkstruct.math.style import MathStyle
app = QtWidgets.QApplication([])
d = MathSettingsDialog(MathStyle(em_mm=6.123456789))
d.show(); app.processEvents()
assert d.reference.font.familyName() == "Latin Modern Math"
for i, group in enumerate(GROUPS):
    d.categories.setCurrentRow(i); d.refresh_preview(); app.processEvents()
    assert d.example_choice.isVisible() == (d.example_choice.count() > 1)
    for key, label in group[2]:
        control = d.controls[key]
        control.setFocus(); app.processEvents()
        assert d.active_key == key and control.property("activeMathDimension")
        assert control.suffix().strip() in {"mm", "%"}
        assert control.buttonSymbols() == QtWidgets.QAbstractSpinBox.NoButtons
    for j in range(d.example_choice.count()):
        d.example_choice.setCurrentIndex(j); d.refresh_preview(); app.processEvents()
        assert d.preview.box is not None, d.preview_status.text()
        assert not any(e.code == "reference-glyph-missing" for e in d.print_preview.box.diagnostics)
d.categories.setCurrentRow(1)
d.example_choice.setCurrentIndex(0)
assert d.example_choice.currentIndex() == 0
d.refresh_preview(); app.processEvents()
assert len(d.print_preview.guide_rows) == len(d.preview.guide_rows) == 2
assert all(d.print_preview.annotation_marks(key) for key, _ in GROUPS[1][2])
for key in ('operator_gap_em', 'binary_gap_em', 'operator_gap_em'):
    d.controls[key].setFocus(); app.processEvents()
    assert d.active_key == key and d.example_choice.currentIndex() == 0
d.example_choice.setCurrentIndex(2); d.refresh_preview()
glyphs = [(g.occurrence.text, g.outline.character) for g in d.print_preview.box.glyphs if g.outline]
assert ("x", "𝑥") in glyphs and ("α", "𝛼") in glyphs
assert all((c,c) in glyphs for c in "sinlogrankd2")
assert "手写缺少字形" in d.preview_status.text()
d.categories.setCurrentRow(2)
d.controls["superscript_raise_em"].setValue(0)
d.refresh_preview()
for pane in (d.print_preview, d.preview):
    mark = next(m for m in pane.box.dimensions if m.key == "superscript_raise_em")
    assert mark.actual > mark.requested and mark.start[1] == 0
parsed = d.preview_document
d.controls["superscript_raise_em"].setValue(100); d.refresh_preview()
assert d.preview_document is parsed
d.categories.setCurrentRow(3)
d.sources["fraction_source"].setCurrentIndex(d.sources["fraction_source"].findData("geometric"))
d.example_choice.setCurrentIndex(1); d.refresh_preview()
assert d.example_choice.currentData() != GROUPS[3][1]
d.controls["fraction_clearance_em"].setValue(0); d.refresh_preview()
for pane in (d.print_preview, d.preview):
    marks = [m for m in pane.box.dimensions if m.key == "fraction_clearance_em"]
    assert len(marks) == 4 and all(m.actual >= .449 for m in marks)
    sizes = [m.actual for m in pane.box.dimensions if m.key == "fraction_scale"]
    assert len(sizes) == 2 and min(sizes) < max(sizes)
assert d.print_preview.pixels_per_mm == d.preview.pixels_per_mm
d.categories.setCurrentRow(4); d.categories.setCurrentRow(3)
assert d.configuration().fraction_clearance_em == 0
d.reset_buttons["fraction_clearance_em"].click()
assert d.configuration().fraction_clearance_em == MathStyle.handwriting().fraction_clearance_em
assert d.configuration().em_mm == 6.123456789
d.resize(760,440); app.processEvents()
assert d.categories.isVisible()
assert d.parameter_scroll.verticalScrollBar().maximum() > 0
assert d.parameter_scroll.horizontalScrollBar().maximum() == 0
assert all(b.isVisible() and d.rect().contains(b.mapTo(d,b.rect().center()))
           for b in d.findChild(QtWidgets.QDialogButtonBox).buttons())
d.example_choice.setCurrentIndex(0); d.refresh_preview()
assert d.preview.box is not None
d.reject()
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_keyboard_edits_refresh_without_focus_loss_and_keep_preview_scale():
    program = r"""
from PySide6 import QtWidgets, QtTest
from inkstruct.editor.math_settings import MathSettingsDialog
from inkstruct.math.style import MathStyle
app = QtWidgets.QApplication([])
d = MathSettingsDialog(MathStyle()); d.show()
def wait():
    QtTest.QTest.qWait(220)
    assert not d.timer.isActive()
def type_value(key, text):
    control = d.controls[key]
    control.setFocus(); control.selectAll()
    QtTest.QTest.keyClicks(control, text)
    wait()
    assert control.hasFocus()
# Use the digit example so this test can exercise edits without a linked font.
# No refresh_preview call or Enter/Tab: exercise the real input and timer path.
d.categories.setCurrentRow(2); d.example_choice.setCurrentIndex(1); wait()
before = d.preview.box
zoom = d.preview.pixels_per_mm
selected = d.preview_resolver.selection_records()
image = d.preview.grab().toImage()
type_value('script_scale', '90')
assert d.configuration().script_scale == .9
assert d.preview.box.glyphs[-1].em_mm > before.glyphs[-1].em_mm
assert d.preview.pixels_per_mm == zoom
assert d.preview.grab().toImage() != image
assert d.preview_resolver.selection_records() == selected
# Out-of-range text used to show the new number with stale, apparently frozen geometry.
type_value('script_scale', '40')
assert d.controls['script_scale'].text().startswith('40')
assert d.preview.box is None
assert '50–100%' in d.preview_status.text() and d.preview_status.isVisible()
try:
    d.configuration()
except ValueError:
    pass
else:
    raise AssertionError('invalid text must not silently reuse the previous value')
type_value('script_scale', '80')
assert d.preview.box is not None and not d.preview_status.isVisible()
# Main font size used to be canceled out by fit-to-height on every repaint.
d.categories.setCurrentRow(0); wait()
old = d.preview.box
old_pixels = old.glyphs[0].em_mm * d.preview.pixels_per_mm
type_value('em_mm', '12')
assert d.preview.box.glyphs[0].em_mm * d.preview.pixels_per_mm == old_pixels * 2
d.categories.setCurrentRow(5); wait()
assert '自动' in d.explanation.toolTip() or '独立' in d.explanation.toolTip()
type_value('limits_scale', '90')
assert d.preview.box.glyphs[1].em_mm == 10.8
assert d.configuration().script_scale == .8
# Bracket parameters also refresh in place; wide examples scroll at the same scale.
d.categories.setCurrentRow(7); wait()
old_width = d.preview.box.width
type_value('delimiter_width_em', '100')
assert d.preview.box.width > old_width and d.preview.pixels_per_mm == zoom
d.categories.setCurrentRow(0); wait()
type_value('em_mm', '150')
assert d.preview_scroll.horizontalScrollBar().maximum() > 0
assert d.preview.pixels_per_mm == zoom
d.preview_zoom.setCurrentIndex(d.preview_zoom.findData(100)); app.processEvents()
assert d.preview.pixels_per_mm == zoom / 2
print('typed edits, invalid input recovery, stable zoom and overflow passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
