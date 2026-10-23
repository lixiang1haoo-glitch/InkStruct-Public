import os
import subprocess
import sys


def test_dialog_validation_cancel_and_snapshot_freeze(tmp_path):
    program = r'''
from pathlib import Path
import sys,time,json
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.svg_export_dialog import SvgExportDialog
from inkstruct.plotter.options import ExportOptions
app=QtWidgets.QApplication([]);root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
d=SvgExportDialog(5);d.pages.setText('6');d.accept();assert d.options is None and d.error.text()
d.pages.setText('1-2,5');d.scales[0].setValue(102);d.registration.setChecked(True);d.accept()
assert d.options.pages==(0,1,4) and d.options.scale_x==1.02 and d.options.registration
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
QtCore.QTimer.singleShot(30,lambda:app.activeModalWidget().reject())
QtWidgets.QFileDialog.getSaveFileName=lambda *a:(_ for _ in ()).throw(AssertionError('cancel must not select path'))
w.export_machine();wait_export();assert w.snapshot is snapshot and choices==w.resolver.selection_records()
def changed(s):w.editor.insertPlainText('4');return ExportOptions((0,)),True
w.configure_svg_export=changed;w.export_machine();wait_export();ready()
snapshot=w.snapshot
w.configure_svg_export=lambda s:(ExportOptions((0,),scale_x=1.32293,scale_y=1.32293,registration=True),False)
def destination(*args):w.editor.insertPlainText('5');return str(root/'machine'),''
QtWidgets.QFileDialog.getSaveFileName=destination
w.export_machine();wait_export()
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
