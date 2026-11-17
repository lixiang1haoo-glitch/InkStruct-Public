"""Real handlers for protected templates, explicit replacement and forced SVG jobs."""
import os
import subprocess
import sys

PROGRAM=r"""
import sys,time,json,os
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'packaging'))
os.environ['INKSTRUCT_LAYOUT_PREVIEW_HOME']=str(Path(sys.argv[1])/'private')
from inkstruct_layout_launcher import configure_preview
configure_preview()
os.environ.pop('INKSTRUCT_LAYOUT_PREVIEW',None)
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_break_commands import multi_frame
from PySide6 import QtCore,QtWidgets
from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.schema import PageProfile,StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.package import save_package,load_package
from inkstruct.global_defaults import GlobalDefaultsStore,LayoutDefaults
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.document_export_dialog import DocumentExportDialog
from inkstruct.settings_dialog import SettingsDialog
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
assert Path(GlobalDefaultsStore.make_settings().fileName()).resolve().is_relative_to(root)
original=multi_frame();other=replace(original,name='default-other',width_mm=130)
GlobalDefaultsStore().save(LayoutDefaults(flow=FlowStyle(template=other)))
w=MixedWindow(source='1\\newpage2');w.resolver=AssetResolver(builtin_numbers=True)
w.page=PageProfile(120,120,0);w.flow=FlowStyle(template=original);w.show();w.schedule_layout()
def ready(window,errors=False):
    end=time.monotonic()+25
    while time.monotonic()<end:
        app.processEvents()
        if window.snapshot and not window.timer.isActive() and not window.worker and window.canvas.isEnabled():
            if not errors:assert window.snapshot.plotter_exportable,window.snapshot.diagnostics
            window.recovery_timer.stop();return
        time.sleep(.01)
    raise AssertionError(window.status.text())
ready(w);paper=w.page;identities=w.source_session.atom_ids

d=SettingsDialog(w,category='body');body=d.pages['body'];body.style.controls['em_mm'].setValue(7)
assert d.apply(to_document=True),d.error.text();ready(w)
assert w.flow.template is original and w.page==paper
body.style.controls['em_mm'].setValue(8);assert d.apply(),d.error.text();ready(w)
assert w.flow.template is original and w.page==paper
# Default resource controls live outside global settings.
assert not {'paper','font'} & d.items.keys()
assert d.apply(),d.error.text();ready(w)
assert w.flow.template is original and w.page==paper
d.reject();assert w.source_session.atom_ids==identities
w.element_inspector.apply_defaults();ready(w)
assert '当前模板' in w.element_inspector.error.text()
assert w.flow.template is original and w.page==paper
path=root/'template.inkdoc';save_package(path,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
loaded=load_package(path);assert loaded.flow.template==original and loaded.page==paper

explicit=replace(original,name='explicit',height_mm=125)
w.template_content_panel.apply_template(explicit);ready(w)
assert w.flow.template==explicit and w.page==paper
w.dirty=False;w.close()

w=MixedWindow(source='1汉2');w.resolver=AssetResolver(builtin_numbers=True)
w.flow=FlowStyle();w.show();w.schedule_layout();ready(w,True)
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete)
assert not w.snapshot.exportable and w.export_button.isEnabled()
source=w.source_session.source;atoms=w.source_session.atom_ids;choices=w.resolver.selection_records()
output=root/'forced-svg'
def choose_partial(dialog):
    dialog.run_check()
    assert not dialog.save.isEnabled() and not dialog.partial.isHidden()
    dialog.accept_partial()
    return dialog.result()
with (patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(output),'')),
      patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.StandardButton.Yes),
      patch.object(DocumentExportDialog,'exec',choose_partial)):
    w.export_button.click()
end=time.monotonic()+35
while w.export_job is not None and time.monotonic()<end:
    app.processEvents();time.sleep(.01)
assert w.export_job is None
assert w.last_export_result['error'] is None,w.last_export_result
assert (output/'issues.txt').is_file()
assert json.loads((output/'issues.json').read_text(encoding='utf-8'))['forced']
assert w.source_session.source==source and w.source_session.atom_ids==atoms
assert w.resolver.selection_records()==choices and not w.snapshot.exportable
assert w.export_button.isEnabled()
assert 'issues.txt' in w.status.text()
dialog=DocumentExportDialog(w.snapshot,w.markdown_document,w.flow,0,False,w)
dialog.run_check();dialog.accept()
assert dialog.selection is None and dialog.checked.partial is not None
dialog.deleteLater()
w.dirty=False;w.close();app.processEvents()
"""


def test_template_preservation_and_forced_background_export_handlers(tmp_path):
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',PROGRAM,str(tmp_path)],
                          capture_output=True,text=True,encoding='utf-8',check=False,timeout=120,
                          env={**os.environ,'QT_QPA_PLATFORM':'offscreen','PYTHONIOENCODING':'utf-8'})
    assert result.returncode==0,result.stdout+result.stderr
