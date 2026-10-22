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
from inkstruct.plotter.options import ExportOptions
MixedWindow.configure_svg_export=lambda self,snapshot:(ExportOptions(tuple(range(len(snapshot.pages)))),self.optimize.isChecked())
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
assert not w.snapshot.exportable and w.machine_export.isEnabled() and not w.page_export.isEnabled()
assert '可确认跳过位图' in w.status.text()
scope=reference_image_export_scope(w.snapshot)
assert [i['reason'] for i in scope['omitted_images']]==['loaded-raster','resource-not-loaded']
dialog_errors=[]
def inspect_dialog():
 d=app.activeModalWidget()
 try:
  assert isinstance(d,QtWidgets.QMessageBox)
  assert '包括尚未载入的图片' in d.text() and '保留当前预览' in d.text()
  assert '已载入位图：1' in d.informativeText() and '尚未载入的位图引用：1' in d.informativeText()
  assert '中文 图.jpeg' in d.detailedText() and 'loaded.png' in d.detailedText()
  assert d.defaultButton()==d.button(QtWidgets.QMessageBox.Cancel)
 except BaseException as e:dialog_errors.append(repr(e))
 finally:d.done(QtWidgets.QMessageBox.Cancel)
QtCore.QTimer.singleShot(20,inspect_dialog)
assert w.confirm_image_omissions(scope) is False and not dialog_errors,dialog_errors
snapshot=w.snapshot;choices=w.resolver.selection_records();flow=w.flow
before=[page_svg(snapshot,i,debug=True) for i in range(len(snapshot.pages))]
calls=[]
def choose(*args):
 calls.append('file');return str(root/'machine'),''
QtWidgets.QFileDialog.getSaveFileName=choose
w.confirm_image_omissions=lambda scope:False
w.export_machine();wait_export();assert not calls and not (root/'machine').exists()
w.confirm_image_omissions=lambda scope:True
QtWidgets.QFileDialog.getSaveFileName=lambda *args:('','')
w.export_machine();wait_export();assert w.snapshot is snapshot and not calls
QtWidgets.QFileDialog.getSaveFileName=choose
w.export_machine();wait_export();assert calls==['file']
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
w.export_machine();wait_export()
frozen=json.loads((root/'frozen/plotter.json').read_text(encoding='utf-8'))
assert frozen['snapshot_id']==snapshot.snapshot_id and frozen['export_scope']==report['export_scope']
assert (root/'frozen/page-001.svg').read_bytes()==(root/'machine/page-001.svg').read_bytes()
ready();assert not w.machine_export.isEnabled()
w.editor.undo();ready()
project=root/'saved.inkdoc'
save_package(project,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
restored=load_package(project)
assert restored.session.source==source and restored.flow==flow
assert restored.resolver.selection_records()==choices
# A change during the earlier scope-confirmation step cancels export.
def stale(scope):
 w.editor.setPlainText('![](missing.svg)');return True
w.confirm_image_omissions=stale
QtWidgets.QFileDialog.getSaveFileName=lambda *args:(_ for _ in ()).throw(AssertionError('stale scope'))
w.export_machine();wait_export();ready();assert not w.machine_export.isEnabled()
w.confirm_image_omissions=lambda scope:(_ for _ in ()).throw(AssertionError('must block'))
w.export_machine();wait_export()
w.editor.setPlainText('![](only.jpg)');ready()
assert not w.snapshot.exportable and w.machine_export.isEnabled()
def only_missing(scope):
 assert len(scope['omitted_images'])==1 and scope['omitted_images'][0]['reason']=='resource-not-loaded'
 return False
w.confirm_image_omissions=only_missing;w.export_machine();wait_export()
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
