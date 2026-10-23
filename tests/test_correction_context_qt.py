import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('dpi', ['1', '1.5', '2'])
def test_context_preview_uses_frozen_neighbours_and_exact_batch_geometry(tmp_path, dpi):
    program = r'''
import sys,time
from dataclasses import replace
from pathlib import Path
from PySide6 import QtCore,QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.styles import FlowStyle
from inkstruct.document.glyph_corrections import GlyphCorrection
from inkstruct.fonts.importer import build_font
from inkstruct.renderers.pages import page_svg
from inkstruct.theme import use_light_theme
app=QtWidgets.QApplication([]);use_light_theme(app)
root=Path(sys.argv[1]);sys.path.insert(0,str(Path.cwd()/'tests'))
from test_font_packages import recorded
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
font=root/'context.inkfont'
build_font(font,writer='fixture',name='context',symbols=recorded(root,styles=('upright','upright','italic')))
w=MixedWindow(source='AAAAAAAAAAA\n\nAA',run=str(font));w.show()
def ready():
    end=time.monotonic()+30
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():
            w.recovery_timer.stop();return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready();p=w.glyph_inspector
w.select_fragment(w.snapshot.fragments[5])
assert len(p.preview.context)==7
assert [c.fragment for c in p.preview.context]==list(w.snapshot.fragments[2:9])
f=p.fragment;choices=w.resolver.selection_records();svg=page_svg(w.snapshot,0)
raw=tuple(g.original_json for g in w.resolver.pools['A'])
p.controls['dx_em'].setValue(10);p.controls['scale_y'].setValue(110)
groups=p.preview.drawing_groups()
assert sum(color=='#245cec' for _,color in groups)==1
assert sum(color=='#374151' for _,color in groups)==6
assert page_svg(w.snapshot,0)==svg and w.resolver.selection_records()==choices
draft=next(strokes for strokes,color in groups if color=='#245cec')
p.preview.grab().save(str(root/'context-single.png'))
p.apply();ready()
f=p.fragment
actual=tuple(op.points for op in w.snapshot.pages[f.page_index].paint_ops if op.occurrence_id==f.occurrence_id)
assert draft==actual
assert len(p.preview.context)==7 and p.controls['dx_em'].value()==10
p.scope.setCurrentIndex(p.scope.findData('sample'))
assert sum(color=='#245cec' for _,color in p.preview.drawing_groups())==sum(
    c.fragment.asset_id==f.asset_id for c in p.preview.context)
p.scope.setCurrentIndex(p.scope.findData('character'))
assert sum(color=='#245cec' for _,color in p.preview.drawing_groups())==7
p.preview.grab().save(str(root/'context-batch.png'))
assert tuple(g.original_json for g in w.resolver.pools['A'])==raw
# Re-layout refreshes the row and discards stale page positions.
old_context=p.preview.context
w.flow=replace(w.flow,latin_spacing='capture');w.schedule_layout();ready()
assert p.preview.context is not old_context
w.select_fragment(w.snapshot.fragments[-1])
assert len(p.preview.context)==2
assert all(c.fragment.line_index==p.fragment.line_index for c in p.preview.context)
p.controls['scale_x'].setValue(400);p.controls['dx_em'].setValue(-200)
p.preview.grab().save(str(root/'context-boundary.png'))
w.dirty=False;w.close()
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_SCALE_FACTOR': dpi},
                            capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
