import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
@pytest.mark.parametrize("write_scope,changed", [("sample", 1), ("character", 2)])
def test_correction_sidebar_scopes_reopen_and_expanded_elements(tmp_path, dpi, write_scope, changed):
    program = r'''
import json, sys, time
from pathlib import Path
from PySide6 import QtCore, QtWidgets, QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font
from inkstruct.document.package import save_package
from inkstruct.document.styles import FlowStyle
from inkstruct.document.glyph_corrections import correction_for, update_corrections
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.renderers.pages import page_svg
from inkstruct.theme import use_light_theme
app=QtWidgets.QApplication([]); use_light_theme(app)
root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_font_packages import recorded
path=root/'font.inkfont'
build_font(path,writer='fixture',name='fixture',symbols=recorded(root,styles=('upright','upright','italic')))
w=MixedWindow(source=r'AA $A$'+ '\n\n|A|\n|---|\n|A|',run=str(path)); w.show()
def ready():
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():
            w.recovery_timer.stop(); return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
p=w.glyph_inspector
assert [(p.scope.itemText(i),p.scope.itemData(i)) for i in range(p.scope.count())]==[
    ('仅此处','occurrence'),('本文同一样本','sample'),('本文同一字符的全部样本','character')]
assert not p.write_font.isChecked() and p.write_font.isHidden()
before=page_svg(w.snapshot,0)
f=w.snapshot.fragments[1]
w.select_fragment(f)
assert w.properties_tabs.currentIndex()==1 and p.apply_button.isEnabled()
asset=w.asset_for_fragment(f); original=asset.original_json
p.controls['dx_em'].setValue(-5)
p.controls['scale_x'].setValue(105)
# Unsaved draft affects only local optical preview.
assert not w.flow.glyph_corrections and page_svg(w.snapshot,0)==before
p.apply(); ready()
assert len(w.flow.glyph_corrections)==1 and w.flow.glyph_corrections[0].scope=='occurrence'
assert p.fragment.occurrence_id==f.occurrence_id
assert p.controls['dx_em'].value()==-5
assert page_svg(w.snapshot,0)!=before and asset.original_json==original
p.undo_button.click(); ready(); assert page_svg(w.snapshot,0)==before
p.redo_button.click(); ready(); assert len(w.flow.glyph_corrections)==1
p.reset_button.click(); ready(); assert not w.flow.glyph_corrections
p.scope.setCurrentIndex(p.scope.findData('sample'))
assert not p.write_font.isHidden() and not p.write_font.isChecked()
p.controls['dy_em'].setValue(1); p.apply(); ready()
assert len(w.flow.glyph_corrections)==1 and w.flow.glyph_corrections[0].asset_id==f.asset_id
# An old single-instance adjustment must not block a later batch operation.
p.scope.setCurrentIndex(p.scope.findData('occurrence'))
p.controls['dy_em'].setValue(2); p.apply(); ready()
assert any(r.scope=='occurrence' for r in w.flow.glyph_corrections)
p.scope.setCurrentIndex(p.scope.findData('sample'))
p.controls['dy_em'].setValue(3); p.apply(); ready()
assert not any(r.scope=='occurrence' for r in w.flow.glyph_corrections)
assert correction_for(w.flow.glyph_corrections,p.fragment).dy_em==.03
p.scope.setCurrentIndex(p.scope.findData('character'))
assert len(p.target_ids())==2 and not p.include_styles.isHidden()
p.include_styles.setChecked(True); assert len(p.target_ids())==3
p.include_styles.setChecked(False); assert len(p.target_ids())==2
p.controls['scale_y'].setValue(95); p.apply(); ready()
assert len(w.flow.glyph_corrections)==2
assert all(r.scope=='character' for r in w.flow.glyph_corrections)
italic=next(g for g in w.resolver.pools['A'] if g.font_core['record']['letter_style']=='italic')
assert all(r.asset_id!=italic.asset_id for r in w.flow.glyph_corrections)
assert not any(r.scope=='document' for r in w.flow.glyph_corrections)
corrected=page_svg(w.snapshot,0)
saved=root/'corrected.inkdoc'
save_package(saved,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
w.dirty=False; w.load_project_path(saved); ready()
assert page_svg(w.snapshot,0)==corrected
w.select_fragment(w.snapshot.fragments[1])
assert p.apply_button.isEnabled()
# Global and per-element forms contain no fold buttons; content survives no-op.
d=SettingsDialog(w)
for kind in ('table','image'):
    d.select(kind); app.processEvents()
    page=d.pages[kind]
    assert not [b for b in page.findChildren(QtWidgets.QToolButton) if b.text()=='更多设置']
    editor=page.editors[None]
    keys=('padding_top_mm','digit_height_mm') if kind=='table' else ('svg_tolerance_mm',)
    for key in keys:
        control=editor.controls[key]
        ancestor=control
        while ancestor is not page:
            assert not ancestor.isHidden(),key
            ancestor=ancestor.parentWidget()
assert d.apply(),d.error.text()
assert page_svg(w.snapshot,0)==corrected
d.reject()
# Font output runs in a worker; all inputs lock, source stays byte-identical.
source_hash=path.read_bytes()
output=root/'derived.inkfont'
p.scope.setCurrentIndex(p.scope.findData(sys.argv[2]))
p.controls['dx_em'].setValue(2); p.write_font.setChecked(True)
old_flow=w.flow
expected=update_corrections(old_flow.glyph_corrections,p.targets(),w.snapshot.fragments)
# Cancel either picker: neither a partial document operation nor a font job.
original_open=QtWidgets.QFileDialog.getOpenFileName
original_save=QtWidgets.QFileDialog.getSaveFileName
QtWidgets.QFileDialog.getOpenFileName=lambda *a,**k:('','')
p.apply(); assert w.flow==old_flow and p.job is None
QtWidgets.QFileDialog.getOpenFileName=lambda *a,**k:(str(path),'')
QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:('','')
p.apply(); assert w.flow==old_flow and p.job is None
QtWidgets.QFileDialog.getOpenFileName=original_open
QtWidgets.QFileDialog.getSaveFileName=original_save
assert w.run_path==''
p.start_font_job(path,output)
assert p.job and not p.fields.isEnabled() and not p.apply_button.isEnabled()
assert w.flow==old_flow
end=time.monotonic()+30
while p.job and time.monotonic()<end:
    app.processEvents(); QtTest.QTest.qWait(10)
assert p.job is None and p.last_result,p.message.text()
assert len(p.last_result['corrected_candidates'])==int(sys.argv[3])
assert p.last_result['document_applied']
ready()
assert FontPackage(output).verify()['candidates']==3
assert path.read_bytes()==source_hash
assert w.flow.glyph_corrections==expected
assert w.run_path==''  # Do not replace frozen resources with the corrected font.
assert page_svg(w.snapshot,0)!=corrected
updated=page_svg(w.snapshot,0)
p.undo_button.click(); ready(); assert w.flow==old_flow and page_svg(w.snapshot,0)==corrected
p.redo_button.click(); ready(); assert page_svg(w.snapshot,0)==updated
# Failure keeps both the document and source package untouched.
stable=w.flow
p.start_font_job(root/'missing.inkfont',root/'no-partial.inkfont')
end=time.monotonic()+10
while p.job and time.monotonic()<end:
    app.processEvents(); QtTest.QTest.qWait(10)
assert p.job is None and p.last_result is None
assert w.flow==stable and not (root/'no-partial.inkfont').exists()
# A source edit during font writing must not receive an obsolete batch edit.
p.start_font_job(path,root/'stale.inkfont')
w.editor.appendPlainText('\n1')
end=time.monotonic()+30
while p.job and time.monotonic()<end:
    app.processEvents(); QtTest.QTest.qWait(10)
assert p.job is None and p.last_result and not p.last_result['document_applied']
assert w.flow==stable
ready()
w.dirty=False; w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
'''
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", program, str(tmp_path),write_scope,str(changed)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
                            capture_output=True, text=True, encoding="utf-8", timeout=70, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
