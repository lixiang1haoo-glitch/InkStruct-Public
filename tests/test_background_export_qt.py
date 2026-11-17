import os
import subprocess
import sys


def test_background_edit_cancel_close_duplicate_and_frozen_settings(tmp_path):
    program = r'''
import json,time,sys
from pathlib import Path
from PySide6 import QtCore,QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.export_job import ExportJob
from inkstruct.editor.export_check import check_export
from inkstruct.plotter.parallel import PageRouter
from inkstruct.plotter.options import ExportOptions
app=QtWidgets.QApplication([]);root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
w=MixedWindow(source='123');w.show();errors=[];w.message_error=lambda e:errors.append(str(e))
def wait(test):
 end=time.monotonic()+20
 while time.monotonic()<end:
  app.processEvents();QtTest.QTest.qWait(5)
  if test():return
 raise AssertionError((w.status.text(),errors))
wait(lambda:w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive())
original=w.snapshot;choices=w.resolver.selection_records()
class SlowRouter(PageRouter):
 def routes(self,*a,control,**kw):
  for i in range(100):
   control.check();time.sleep(.01)
  yield from super().routes(*a,control=control,**kw)
init=ExportJob.__init__
def slow(self,*a,**kw):init(self,*a,**kw);self.router=SlowRouter()
ExportJob.__init__=slow
def configure(snapshot, optimize):
 check=check_export(snapshot,w.markdown_document,w.flow,
                    ExportOptions((0,),scale_x=1.32293,scale_y=1.32293,registration=True),machine=True)
 assert not check.errors
 return 'machine',check,check.machine,optimize
w.configure_document_export=lambda s:configure(s,False)
calls=[]
def choose(*a):calls.append('path');return str(root/'cancelled'),''
QtWidgets.QFileDialog.getSaveFileName=choose
start=time.monotonic();w.export_document();assert time.monotonic()-start<.5
job=w.export_job;assert job and not w.export_button.isEnabled()
w.export_document();assert w.export_job is job and calls==['path']
ticks=[];timer=QtCore.QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start()
QtTest.QTest.qWait(150);w.export_progress.reject()
w.dirty=False;assert not w.close() and w.isVisible()
wait(lambda:w.export_job is None)
assert not (root/'cancelled').exists() and not list(root.glob('.inkstruct-plotter-*'))
assert w.snapshot is original and w.resolver.selection_records()==choices
assert w.last_export_result['cancelled'] and len(ticks)>5
assert w.optimize.isChecked() # cancelled job must not commit a different export preference
w.configure_document_export=lambda s:configure(s,True)
QtWidgets.QFileDialog.getSaveFileName=lambda *a:(str(root/'success'),'')
w.export_document();frozen=w.export_job.plan
w.editor.insertPlainText('4');w.optimize.setChecked(False)
wait(lambda:w.export_job is None)
assert not errors and not w.optimize.isChecked() # old job cannot overwrite newer document preference
report=json.loads((root/'success/plotter.json').read_text('utf-8'))
assert report['snapshot_id']==original.snapshot_id==frozen.snapshot_id
assert report['optimized'] and report['export_scope']['coordinate_scale']['x']==1.32293
assert len(report['export_scope']['registration_marks'])==2
wait(lambda:w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive())
assert w.source_session.source!='123'
QtWidgets.QFileDialog.getSaveFileName=lambda *a:(str(root/'commit-preference'),'')
w.export_document();wait(lambda:w.export_job is None)
assert w.optimize.isChecked() and not w.last_export_result['error']
timer.stop();w.dirty=False;w.close()
'''
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
