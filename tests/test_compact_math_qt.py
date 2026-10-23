import os
import subprocess
import sys


def test_math_defaults_cancel_explicit_apply_and_legacy_reopen(tmp_path):
    program=r'''
import sys,time,json
from pathlib import Path
from dataclasses import asdict,replace
from PySide6 import QtCore,QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.math_settings import MathSettingsDialog
from inkstruct.document.styles import FlowStyle
from inkstruct.document.package import save_package,load_package
from inkstruct.global_defaults import GlobalDefaultsStore,LayoutDefaults
from inkstruct.math.style import MathStyle
from inkstruct.settings_dialog import SettingsDialog
app=QtWidgets.QApplication([]);root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
old=LayoutDefaults(flow=FlowStyle(math=MathStyle(em_mm=7.123456789)))
record={'version':1,**asdict(old)}
record['flow']['math'].pop('spacing_policy')
store=GlobalDefaultsStore();raw=json.dumps(record)
store.settings.setValue(store.KEY,raw);store.settings.sync()
store=GlobalDefaultsStore();upgraded,warning=store.load()
assert warning is None and upgraded.flow.math.spacing_policy=='handwriting'
assert upgraded.flow.math.em_mm==7.123456789
assert upgraded.flow.math.radical_source==upgraded.flow.math.delimiter_source=='sample'
assert store.settings.value(store.KEY)==raw and store.settings.value(store.MATH_DEFAULT_KEY) is None
store.save(replace(upgraded,flow=replace(upgraded.flow,math=old.flow.math)))
assert GlobalDefaultsStore().load()[0].flow.math==old.flow.math
w=MixedWindow(source='123')
def ready():
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        app.processEvents()
        if w.snapshot and not w.worker and not w.timer.isActive():
            w.recovery_timer.stop();return
        time.sleep(.01)
    raise AssertionError(w.status.text())
ready()
assert w.flow.math==old.flow.math
original=(w.flow,w.source_session.atom_ids,w.resolver.selection_records())
d=SettingsDialog(w,category='math');page=d.pages['math']
page.spacing_policy.setCurrentIndex(page.spacing_policy.findData('handwriting'))
d.reject()
assert original==(w.flow,w.source_session.atom_ids,w.resolver.selection_records())
d=SettingsDialog(w,category='math');page=d.pages['math']
page.categories.setCurrentRow(0);page.reset_category()
page.categories.setCurrentRow(4);page.reset_category()
page.categories.setCurrentRow(7);page.reset_category()
d.apply_current.setChecked(True)
assert d.apply(),d.error.text()
d.reject();ready()
assert w.flow.math.spacing_policy=='handwriting'
assert w.flow.math.radical_source==w.flow.math.delimiter_source=='sample'
assert w.source_session.atom_ids==original[1] and w.resolver.selection_records()==original[2]
save_package(root/'v2.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow)
w.load_project_path(root/'v2.inkdoc');ready()
assert w.flow.math==load_package(root/'v2.inkdoc').flow.math
save_package(root/'v1.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=replace(w.flow,math=old.flow.math))
w.load_project_path(root/'v1.inkdoc');ready()
assert w.flow.math==old.flow.math
w.timer.stop();w.pool.waitForDone();w.dirty=False;w.close()
'''
    result=subprocess.run([sys.executable,'-X','utf8','-c',program,str(tmp_path)],
                          env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},capture_output=True,
                          text=True,encoding='utf-8',timeout=90,check=False)
    assert result.returncode==0,result.stdout+result.stderr
