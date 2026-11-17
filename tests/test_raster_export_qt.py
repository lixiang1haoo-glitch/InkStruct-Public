import os
import subprocess
import sys


def test_gui_export_confirmation_cancel_omission_and_errors(tmp_path):
    program = r'''
import sys,time,json
from pathlib import Path
from dataclasses import replace
from PIL import Image
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.document_export_dialog import DocumentExportDialog
from unittest.mock import patch
from inkstruct.document.images import RasterResource
from inkstruct.document.package import load_package,save_package
from inkstruct.document.markdown import parse_markdown
from inkstruct.layout.blocks import layout_markdown
from inkstruct.renderers.pages import page_svg
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
image=root/'p.png';Image.new('RGB',(120,60),'blue').save(image)
w=MixedWindow(source='1\n\n![12](p.png)\n\n2');w.show()
w.flow=replace(w.flow,images=(RasterResource.from_file(image,'p.png'),))
w.schedule_layout()

def wait_export():
 end=time.monotonic()+20
 while w.export_job is not None and time.monotonic()<end:
  app.processEvents()
  QtTest.QTest.qWait(10)
 assert w.export_job is None, 'export did not complete'
 assert not getattr(w,'last_export_result',{}).get('error'), getattr(w,'last_export_result',{})

def ready():
 end=time.monotonic()+20
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready()
assert w.snapshot.exportable and w.export_button.isEnabled()
w.show_font_warnings=lambda:True
snapshot=w.snapshot
choices=w.resolver.selection_records()
before=[page_svg(snapshot,i) for i in range(len(snapshot.pages))]
calls=[]
def select(*args):
 calls.append('file');return str(root/'machine'),''
QtWidgets.QFileDialog.getSaveFileName=select
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
assert not calls and not (root/'machine').exists()
assert len(reports[-1].images)==1
export()
assert calls==['file']
manifest=json.loads((root/'machine/plotter.json').read_text(encoding='utf-8'))
assert len(manifest['export_scope']['omitted_images'])==1
assert '已跳过 1 处' in w.status.text()
assert before==[page_svg(w.snapshot,i) for i in range(len(w.snapshot.pages))]
assert choices==w.resolver.selection_records() and w.snapshot is snapshot
project=root/'saved.inkdoc'
save_package(project,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
loaded=load_package(project)
restored=layout_markdown(parse_markdown(loaded.session),loaded.resolver,page=loaded.page,style=loaded.style,flow=loaded.flow)
assert before==[page_svg(restored,i) for i in range(len(restored.pages))]
assert choices==loaded.resolver.selection_records()
# Cancelling the destination has no effect either.
QtWidgets.QFileDialog.getSaveFileName=lambda *args:('','')
export();assert w.snapshot is snapshot
# The destination picker keeps the already accepted snapshot and omission scope frozen.
def choose_frozen(*args):
 w.editor.setPlainText('1');return str(root/'frozen-machine'),''
QtWidgets.QFileDialog.getSaveFileName=choose_frozen
export()
frozen=json.loads((root/'frozen-machine/plotter.json').read_text(encoding='utf-8'))
assert frozen['snapshot_id']==snapshot.snapshot_id and frozen['export_scope']==manifest['export_scope']
assert (root/'frozen-machine/page-001.svg').read_bytes()==(root/'machine/page-001.svg').read_bytes()
ready();w.editor.setPlainText('1\n\n![12](p.png)\n\n2');ready()
# A source change while confirmation is open invalidates the prepared snapshot.
QtWidgets.QFileDialog.getSaveFileName=select
export(before_accept=lambda: w.editor.setPlainText('1'));assert calls==['file']
ready()
assert w.export_button.isEnabled()
QtWidgets.QFileDialog.getSaveFileName=lambda *a:(str(root/'ordinary'),'')
export();assert (root/'ordinary/plotter.json').is_file() and not reports[-1].images
assert json.loads((root/'ordinary/plotter.json').read_text(encoding='utf-8'))['export_scope']['page_numbers']==[1]
# Actual formula errors remain blocking before the file picker.
w.editor.setPlainText('1\n\n![](p.png)\n\n$\\unknown{1}$');ready()
assert not w.snapshot.exportable and w.export_button.isEnabled()
QtWidgets.QFileDialog.getSaveFileName=lambda *args:(_ for _ in ()).throw(AssertionError('must block'))
export();assert reports[-1].errors
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=70, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
