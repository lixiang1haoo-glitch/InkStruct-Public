"""New app defaults and explicit old document settings remain separate."""

import os
import subprocess
import sys


def test_punctuation_settings_transaction_and_optimization_default(tmp_path):
    program = r'''
import sys,time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtCore,QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.document.package import save_package,load_package
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
w=MixedWindow(source='123,456。')
def ready():
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        app.processEvents()
        if w.snapshot and not w.worker and not w.timer.isActive():
            w.recovery_timer.stop();return
        time.sleep(.01)
    raise AssertionError(w.status.text())
ready()
assert w.optimize.isChecked() and w.flow.punctuation_spacing=='handwriting'
assert not w.dirty
save_package(root/'new.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow,optimize=w.optimize.isChecked())
loaded=load_package(root/'new.inkdoc')
assert loaded.optimize and loaded.flow.punctuation_spacing=='handwriting'
save_package(root/'old.inkdoc',w.source_session,w.resolver,w.page,w.style,
             flow=replace(w.flow,punctuation_spacing='capture'),optimize=False)
w.load_project_path(root/'old.inkdoc');ready()
assert not w.optimize.isChecked() and w.flow.punctuation_spacing=='capture'
before=(w.flow,w.resolver.selection_records(),w.source_session.atom_ids)
d=SettingsDialog(w,category='body')
assert d.pages['body'].punctuation_spacing.currentData()=='handwriting'
d.pages['body'].punctuation_spacing.setCurrentIndex(1)
d.reject()
assert before==(w.flow,w.resolver.selection_records(),w.source_session.atom_ids)
d=SettingsDialog(w,category='body')
assert d.apply(to_document=True),d.error.text()
d.reject();ready()
assert w.flow.punctuation_spacing=='handwriting' and not w.optimize.isChecked()
assert w.resolver.selection_records()==before[1] and w.source_session.atom_ids==before[2]
save_package(root/'explicit.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow,optimize=w.optimize.isChecked())
w.load_project_path(root/'explicit.inkdoc');ready()
assert not w.optimize.isChecked() and w.flow.punctuation_spacing=='handwriting'
w.timer.stop();w.pool.waitForDone();w.dirty=False;w.close()
'''
    result = subprocess.run(
        [sys.executable, '-X', 'utf8', '-c', program, str(tmp_path)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
        capture_output=True, text=True, encoding='utf-8', timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
