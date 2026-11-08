"""Real settings handlers, no-op precision, draft cancellation and seeded persistence."""
import os
import subprocess
import sys

PROGRAM = r"""
import sys,time
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path.cwd()/"tests"))
from PySide6 import QtCore,QtWidgets
from test_justification_han import resources
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.document.han_variation import HanVariation
from inkstruct.global_defaults import GlobalDefaultsStore,LayoutDefaults
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,sys.argv[1])
w=MixedWindow(source="汉中文汉中文")
w.resolver=resources()
w.flow=replace(w.flow,han_variation=HanVariation(strength=.35123456789))
w.show();w.schedule_layout()
def ready():
    end=time.monotonic()+20
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and not w.timer.isActive() and not w.worker:
            assert w.snapshot.plotter_exportable,w.snapshot.diagnostics
            w.recovery_timer.stop();return
        time.sleep(.01)
    raise AssertionError(w.status.text())
ready()
GlobalDefaultsStore().save(replace(LayoutDefaults(),flow=w.flow))
before=w.flow
d=SettingsDialog(w,category="body");p=d.pages["body"]
assert p.configuration()[1]["han_variation"]==w.flow.han_variation
p.han_enabled.setChecked(True);p.han_seed.setValue(123);p.han_strength.setValue(40)
assert p.han_seed.isEnabled() and p.han_strength.isEnabled()
d.reject();assert w.flow==before

d=SettingsDialog(w,category="body");p=d.pages["body"]
p.han_enabled.setChecked(True);p.han_seed.setValue(123);p.han_strength.setValue(40)
p.paragraph_align.setCurrentIndex(p.paragraph_align.findData("justify"))
assert d.apply(to_document=True),d.error.text();d.reject();ready()
assert w.flow.han_variation==HanVariation(enabled=True,seed=123,strength=.4)
assert w.flow.paragraph_align=="justify"
assert GlobalDefaultsStore().load()[0].flow.han_variation==w.flow.han_variation

d=SettingsDialog(w,category="body");p=d.pages["body"]
previous=w.snapshot.pages
p.han_strength.setValue(55)
assert d.apply(to_document=True),d.error.text();ready()
assert w.flow.han_variation.strength==.55
p.han_strength.setValue(40)
assert p.configuration()[1]["han_variation"].strength==.4
assert d.apply(to_document=True),d.error.text();ready()
assert w.snapshot.pages==previous
d.reject()

d=SettingsDialog(w,category="body");p=d.pages["body"]
p.reset_defaults();config=p.configuration()[1]
assert not config["han_variation"].enabled and config["han_variation"].seed==0
assert config["han_variation"].strength==HanVariation().strength and config["paragraph_align"]=="justify"
d.reject();w.dirty=False;w.close();app.processEvents()
"""


def test_settings_seed_strength_precision_apply_and_cancel(tmp_path):
    result=subprocess.run([sys.executable,"-B","-X","utf8","-c",PROGRAM,str(tmp_path)],
                          env={**os.environ,"QT_QPA_PLATFORM":"offscreen","PYTHONIOENCODING":"utf-8"},
                          capture_output=True,text=True,encoding="utf-8",timeout=60,check=False)
    assert result.returncode==0,result.stdout+result.stderr
