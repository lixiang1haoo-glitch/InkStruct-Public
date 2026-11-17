import os
import subprocess
import sys


def test_dialog_validation_cancel_and_snapshot_freeze(tmp_path):
    program = r'''
from pathlib import Path
import sys,time,json
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.document_export_dialog import DocumentExportDialog
from dataclasses import replace
from inkstruct.plotter.options import ExportOptions
from inkstruct.editor.export_check import check_export
def selected(window,snapshot,options=None,optimize=True):
 opts=options or ExportOptions(tuple(range(len(snapshot.pages))))
 check=check_export(snapshot,window.markdown_document,window.flow,opts,machine=True)
 assert not check.errors
 return 'machine',check,check.machine,optimize
app=QtWidgets.QApplication([]);root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
w=MixedWindow(source='123');w.show()

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
  if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();snapshot=w.snapshot;choices=w.resolver.selection_records()
five=replace(snapshot,pages=tuple(replace(snapshot.pages[0],index=i) for i in range(5)))
d=DocumentExportDialog(five,w.markdown_document,w.flow,0,True)
d.range.setCurrentIndex(d.range.findData('selection'))
d.pages.setText('6');d.run_check();assert d.checked is None and not d.save.isEnabled()
d.pages.setText('1-2,5');d.scales[0].setValue(102);d.registration.setChecked(True);d.run_check()
assert d.checked.pages==(0,1,4) and d.save.isEnabled()
assert d.checked.machine.scope['coordinate_scale']['x']==1.02
assert len(d.checked.machine.scope['registration_marks'])==6
d.deleteLater()
QtCore.QTimer.singleShot(30,lambda:app.activeModalWidget().reject())
QtWidgets.QFileDialog.getSaveFileName=lambda *a:(_ for _ in ()).throw(AssertionError('cancel must not select path'))
w.export_document();wait_export();assert w.snapshot is snapshot and choices==w.resolver.selection_records()
def changed(s):
 result=selected(w,s)
 w.editor.insertPlainText('4')
 return result
w.configure_document_export=changed;w.export_document();wait_export();ready()
snapshot=w.snapshot
w.configure_document_export=lambda s:selected(w,s,ExportOptions((0,),scale_x=1.32293,scale_y=1.32293,registration=True),False)
def destination(*args):w.editor.insertPlainText('5');return str(root/'machine'),''
QtWidgets.QFileDialog.getSaveFileName=destination
w.export_document();wait_export()
report=json.loads((root/'machine/plotter.json').read_text())
assert report['snapshot_id']==snapshot.snapshot_id and not report['optimized']
assert len(report['export_scope']['registration_marks'])==2
scale=report['export_scope']['coordinate_scale']
assert scale['pen_width_unchanged'] and scale['canvas_policy']=='scale-with-coordinates-v1'
assert scale['canvases'][0]['output_size_mm']==[snapshot.page_profile.width_mm*1.32293,snapshot.page_profile.height_mm*1.32293]
w.dirty=False;w.close()
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=40, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
