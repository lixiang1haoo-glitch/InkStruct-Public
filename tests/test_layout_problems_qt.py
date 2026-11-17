"""Problem browsing, source jumps and stale guards through the actual Qt workspace."""
import os
import subprocess
import sys

PROGRAM = r"""
import os,sys,time
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'packaging'))
os.environ['INKSTRUCT_LAYOUT_PREVIEW_HOME']=str(Path(sys.argv[1])/'private')
from inkstruct_layout_launcher import configure_preview
configure_preview()
os.environ.pop('INKSTRUCT_LAYOUT_PREVIEW',None)
from PySide6 import QtCore,QtWidgets
from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.styles import FlowStyle
from inkstruct.document.han_variation import LEGACY,HanVariation
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.global_defaults import GlobalDefaultsStore,LayoutDefaults
app=QtWidgets.QApplication([])
root=Path(__import__('sys').argv[1])
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
assert Path(GlobalDefaultsStore.make_settings().fileName()).resolve().is_relative_to(root)
w=MixedWindow(source=r'汉汉文 1 $\unknown{2}$ 3')
w.flow=FlowStyle();w.resolver=AssetResolver(builtin_numbers=True);w.show();w.schedule_layout()
def ready():
    end=time.monotonic()+30
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and not w.timer.isActive() and not w.worker and w.canvas.isEnabled():
            w.recovery_timer.stop();return
        time.sleep(.01)
    raise AssertionError(w.status.text())
ready()
p=w.problems_panel
assert w.diagnostic_picker.parent() is w.settings_storage
assert len(p.groups)==3 and p.list.topLevelItemCount()==3,[(g.key,g.title) for g in p.groups]
assert p.current_group().title=='缺少字形「汉」'
assert len(p.current_group().diagnostics)==2 and p.next.isEnabled()
assert not p.technical.isVisible()
p.next.click();assert w.editor.textCursor().selectionStart()==1
p.locate.click();assert w.editor.textCursor().selectedText()=='汉'
p.search.setText('公式');assert p.list.topLevelItemCount()==1
assert p.current_group().key[1]=='math-command-unsupported'
p.search.clear();p.copy.click()
assert 'asset-missing' in app.clipboard().text() and '第 1 行' in app.clipboard().text()
source=w.source_session.identity_record()
w.schedule_layout();assert not p.locate.isEnabled() and not p.next.isEnabled()
ready();assert source==w.source_session.identity_record()
w.editor.setPlainText('123');w.schedule_layout();ready()
assert not p.groups and not p.copy.isEnabled() and not p.locate.isEnabled()
assert '检查通过' in p.summary.text() and '按用途和页码检查' in p.export_state.text()
p.set_failure('fixture rendering failure',w.buffer.raw)
assert p.current_group().key[1]=='preview-failed'
assert 'fixture rendering failure' in p.technical.toPlainText()
assert not p.locate.isEnabled()
w.schedule_layout();ready()
d=SettingsDialog(w,category='body');body=d.pages['body']
body.han_enabled.setChecked(True)
for key,value in [('strength',99),('size_strength',75),('spacing_strength',80),('baseline_strength',65)]:
    body.variation_controls[key].setValue(value)
assert d.apply(to_document=True),d.error.text();ready()
assert w.flow.han_variation.schema_version=='inkstruct_han_variation_v2'
assert w.flow.han_variation.spacing_strength==.8 and w.flow.han_variation.baseline_strength==.65
d.reject()
legacy=HanVariation(enabled=True,strength=.99,schema_version=LEGACY)
GlobalDefaultsStore().save(LayoutDefaults(flow=replace(w.flow,han_variation=legacy)))
d=SettingsDialog(w,category='body');body=d.pages['body']
assert body.variation_configuration()==legacy
body.style.controls['em_mm'].setValue(7)
assert body.variation_configuration()==legacy
body.upgrade_natural.click()
assert body.variation_configuration().schema_version=='inkstruct_han_variation_v2'
d.reject();w.dirty=False;w.close();app.processEvents()
"""


def test_problem_panel_and_new_natural_controls_are_actionable_and_guard_stale_source(tmp_path):
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',PROGRAM,str(tmp_path)],
                          capture_output=True,text=True,encoding='utf-8',timeout=90,check=False,
                          env={**os.environ,'QT_QPA_PLATFORM':'offscreen'})
    assert result.returncode==0,result.stdout+result.stderr
