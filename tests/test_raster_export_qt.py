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
from inkstruct.plotter.options import ExportOptions
MixedWindow.configure_svg_export=lambda self,snapshot:(ExportOptions(tuple(range(len(snapshot.pages)))),self.optimize.isChecked())
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
assert w.snapshot.exportable and w.machine_export.isEnabled()
w.show_font_warnings=lambda:True
snapshot=w.snapshot
choices=w.resolver.selection_records()
before=[page_svg(snapshot,i) for i in range(len(snapshot.pages))]
calls=[]
def select(*args):
 calls.append('file');return str(root/'machine'),''
QtWidgets.QFileDialog.getSaveFileName=select
messages=[]
def cancel(scope):
 messages.append(scope);return False
w.confirm_image_omissions=cancel
w.export_machine();wait_export()
assert not calls and not (root/'machine').exists()
assert len(messages[-1]['omitted_images'])==1
w.confirm_image_omissions=lambda scope:True
w.export_machine();wait_export()
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
w.export_machine();wait_export();assert w.snapshot is snapshot
# The destination picker keeps the already accepted snapshot and omission scope frozen.
def choose_frozen(*args):
 w.editor.setPlainText('1');return str(root/'frozen-machine'),''
QtWidgets.QFileDialog.getSaveFileName=choose_frozen
w.export_machine();wait_export()
frozen=json.loads((root/'frozen-machine/plotter.json').read_text(encoding='utf-8'))
assert frozen['snapshot_id']==snapshot.snapshot_id and frozen['export_scope']==manifest['export_scope']
assert (root/'frozen-machine/page-001.svg').read_bytes()==(root/'machine/page-001.svg').read_bytes()
ready();w.editor.setPlainText('1\n\n![12](p.png)\n\n2');ready()
# A source change while confirmation is open invalidates the prepared snapshot.
QtWidgets.QFileDialog.getSaveFileName=select
def stale(scope):
 w.editor.setPlainText('1');return True
w.confirm_image_omissions=stale
w.export_machine();wait_export();assert calls==['file']
ready()
assert w.machine_export.isEnabled()
# No image: no omission prompt, ordinary export is unchanged.
w.confirm_image_omissions=lambda scope:(_ for _ in ()).throw(AssertionError('unexpected prompt'))
QtWidgets.QFileDialog.getSaveFileName=lambda *args:(str(root/'ordinary'),'')
w.export_machine();wait_export();assert (root/'ordinary/plotter.json').is_file()
assert json.loads((root/'ordinary/plotter.json').read_text(encoding='utf-8'))['export_scope']['page_numbers']==[1]
# Actual formula errors remain blocking, before any omission prompt/file picker.
w.editor.setPlainText('1\n\n![](p.png)\n\n$\\unknown{1}$');ready()
assert not w.snapshot.exportable and not w.machine_export.isEnabled()
QtWidgets.QFileDialog.getSaveFileName=lambda *args:(_ for _ in ()).throw(AssertionError('must block'))
w.export_machine();wait_export()
w.dirty=False;w.close();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=70, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
