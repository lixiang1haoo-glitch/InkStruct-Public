import os
import subprocess
import sys


def test_missing_raster_prompt_cancel_freeze_and_real_errors(tmp_path):
    program = r'''
import json,sys,time
from pathlib import Path
from dataclasses import replace
from PIL import Image
from PySide6 import QtCore,QtWidgets,QtTest,QtGui
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.document_export_dialog import DocumentExportDialog
from unittest.mock import patch
from inkstruct.document.images import ImageStyle,RasterResource
from inkstruct.document.package import save_package,load_package
from inkstruct.plotter.adapters import reference_image_export_scope
from inkstruct.renderers.pages import page_svg
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
Image.new('RGB',(120,60),'blue').save(root/'loaded.png')
source='1\n\n![12](loaded.png)\n\n![23](<中文 图.jpeg>)\n\n3'
w=MixedWindow(source=source);w.show()
w.flow=replace(w.flow,images=(RasterResource.from_file(root/'loaded.png','loaded.png'),),image=ImageStyle(height_mm=20))
w.schedule_layout()

def wait_export():
 end=time.monotonic()+20
 while w.export_job is not None and time.monotonic()<end:
  app.processEvents()
  QtTest.QTest.qWait(10)
 assert w.export_job is None, 'export did not complete'
 assert not getattr(w,'last_export_result',{}).get('error'), getattr(w,'last_export_result',{})

def ready():
 end=time.monotonic()+15
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready()
assert not w.snapshot.exportable and w.export_button.isEnabled()
assert '跳过参考图片' in w.problems_panel.export_state.text()
scope=reference_image_export_scope(w.snapshot)
assert [i['reason'] for i in scope['omitted_images']]==['loaded-raster','resource-not-loaded']
def export(*, proceed=True, before_accept=None):
 def respond(dialog):
  dialog.run_check()
  reports.append(dialog.checked)
  if proceed and not dialog.checked.errors:
   if dialog.checked.images:
    assert not dialog.save.isEnabled()
    dialog.confirm_images.setChecked(True)
   if before_accept:
    before_accept()
   dialog.accept()
  return dialog.result()
 with patch.object(DocumentExportDialog, 'exec', respond):
  w.export_document()
 wait_export()
reports=[]
export(proceed=False)
assert {i['display_name'] for i in reports[-1].images}=={'loaded.png','中文 图.jpeg'}
assert not reports[-1].errors
snapshot=w.snapshot;choices=w.resolver.selection_records();flow=w.flow
before=[page_svg(snapshot,i,debug=True) for i in range(len(snapshot.pages))]
calls=[]
def choose(*args):
 calls.append('file');return str(root/'machine'),''
QtWidgets.QFileDialog.getSaveFileName=choose
export(proceed=False);assert not calls and not (root/'machine').exists()
QtWidgets.QFileDialog.getSaveFileName=lambda *args:('','')
export();assert w.snapshot is snapshot and not calls
QtWidgets.QFileDialog.getSaveFileName=choose
export();assert calls==['file']
report=json.loads((root/'machine/plotter.json').read_text(encoding='utf-8'))
assert [{k:v for k,v in i.items() if k!='output_bounds_mm'} for i in report['export_scope']['omitted_images']]==json.loads(json.dumps(scope['omitted_images']))
assert report['export_scope']['source_snapshot_id']==snapshot.snapshot_id
assert report['snapshot_id']==snapshot.snapshot_id and len(report['export_scope']['omitted_images'])==2
assert choices==w.resolver.selection_records() and w.flow==flow and w.snapshot is snapshot
assert before==[page_svg(w.snapshot,i,debug=True) for i in range(len(w.snapshot.pages))]
# The accepted snapshot and omissions remain frozen through the destination picker.
def choose_frozen(*args):
 cursor=w.editor.textCursor();cursor.movePosition(QtGui.QTextCursor.End);w.editor.setTextCursor(cursor)
 w.editor.insertPlainText('\n\n$\\unknown{1}$');return str(root/'frozen'),''
QtWidgets.QFileDialog.getSaveFileName=choose_frozen
export()
frozen=json.loads((root/'frozen/plotter.json').read_text(encoding='utf-8'))
assert frozen['snapshot_id']==snapshot.snapshot_id and frozen['export_scope']==report['export_scope']
assert (root/'frozen/page-001.svg').read_bytes()==(root/'machine/page-001.svg').read_bytes()
ready();assert w.export_button.isEnabled() and not w.snapshot.exportable
w.editor.undo();ready()
project=root/'saved.inkdoc'
save_package(project,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
restored=load_package(project)
assert restored.session.source==source and restored.flow==flow
assert restored.resolver.selection_records()==choices
# A change during the earlier scope-confirmation step cancels export.
QtWidgets.QFileDialog.getSaveFileName=lambda *args:(_ for _ in ()).throw(AssertionError('unexpected picker'))
export(before_accept=lambda: w.editor.setPlainText('![](missing.svg)'))
ready();export()
assert reports[-1].errors
w.editor.setPlainText('![](only.jpg)');ready();export()
assert reports[-1].errors==('所选页没有可写笔迹',)
assert len(reports[-1].images)==1 and reports[-1].images[0]['reason']=='resource-not-loaded'
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
