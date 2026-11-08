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
from inkstruct.editor.svg_export_dialog import SvgExportDialog
from inkstruct.plotter.options import ExportOptions
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
assert w.force_machine_export.parent() is w.settings_storage
w.force_svg_action.parent().aboutToShow.emit();assert w.force_svg_action.isEnabled()
assert not w.snapshot.exportable and not w.machine_export.isEnabled() and w.force_machine_export.isEnabled()
source=w.source_session.source;atoms=w.source_session.atom_ids;choices=w.resolver.selection_records()
output=root/'forced-svg'
w.configure_svg_export=lambda snapshot,force=False:(ExportOptions(tuple(range(len(snapshot.pages))),force=force),False)
with patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(output),'')):
    w.force_svg_action.trigger()
end=time.monotonic()+35
while w.export_job is not None and time.monotonic()<end:
    app.processEvents();time.sleep(.01)
assert w.export_job is None
assert w.last_export_result['error'] is None,w.last_export_result
assert (output/'issues.txt').is_file()
assert json.loads((output/'issues.json').read_text(encoding='utf-8'))['forced']
assert w.source_session.source==source and w.source_session.atom_ids==atoms
assert w.resolver.selection_records()==choices and not w.snapshot.exportable
assert not w.machine_export.isEnabled() and w.force_machine_export.isEnabled()
assert 'issues.txt' in w.status.text()
old=w.last_export_result;w.export_machine();assert w.last_export_result is old
for forced in (False,True):
    dialog=SvgExportDialog(2,parent=w,force=forced);dialog.accept()
    assert dialog.options.force is forced
    dialog.deleteLater()
w.dirty=False;w.close();app.processEvents()
"""


def test_template_preservation_and_forced_background_export_handlers(tmp_path):
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',PROGRAM,str(tmp_path)],
                          capture_output=True,text=True,encoding='utf-8',check=False,timeout=120,
                          env={**os.environ,'QT_QPA_PLATFORM':'offscreen','PYTHONIOENCODING':'utf-8'})
    assert result.returncode==0,result.stdout+result.stderr
