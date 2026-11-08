import os
import subprocess
import sys
import uuid


def test_managed_capture_author_confirmation_pause_cancel_rerecord_and_conflict(tmp_path):
    program = r'''
import sys,json
from pathlib import Path
from PySide6 import QtCore,QtWidgets
from inkstruct.collector import main
from inkstruct.capture_workflow_ui import HanTaskDialog,TaskListDialog
from inkstruct.capture_management import CaptureCatalog
app=QtWidgets.QApplication([])
root=Path(sys.argv[1]);QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
w=main(['InkStruct'],create_only=True,workspace=root/'workspace')
w.show();app.processEvents();a=w.single_widget;b=w.symbol_widget;c=a._capture_catalog
assert a.task is None and b.task is None and not a.writer_edit.text() and not b.writer_edit.text()
slider=a.canvas_size_slider
assert slider.isVisible() and slider.isEnabled() and a.canvas.height()==260
slider.setValue(24)
assert a.canvas.height()==312 and '120%' in a.canvas_size_label.text()
def new_name():
 d=app.activeModalWidget();assert isinstance(d,QtWidgets.QInputDialog);d.setTextValue('张三');d.accept()
QtCore.QTimer.singleShot(0,new_name)
next(b for b in a.findChildren(QtWidgets.QPushButton) if b.text()=='新建书写者…').click()
key=a.writer_edit.text();assert key and c.writers()[key]['name']=='张三'
other=c.create_writer('张三')
def renamed():
 d=app.activeModalWidget();d.setTextValue('中文显示名称');d.accept()
QtCore.QTimer.singleShot(0,renamed)
next(b for b in a.findChildren(QtWidgets.QPushButton) if b.text()=='修改名称…').click()
assert a.writer_edit.text()==key and c.writers()[key]['name']=='中文显示名称'
a.writer_picker.reload(key);a.choose_writer(key)
assert a.writer_edit.text()==key
assert b.writer_picker.text()==key and b.writer_edit.text()==key
path=root/'推荐.csv';path.write_text('character,repeats\n一,2\n二,1','utf-8-sig')
d=HanTaskDialog(c,key,path);assert len(d.entries)==2;d.reject();assert a.task is None
def confirm():
 d=app.activeModalWidget();assert isinstance(d,HanTaskDialog);d.accept()
QtCore.QTimer.singleShot(0,confirm);a.configure_han_task(path)
task=a.task;taskpath=c.root/'tasks'/task.task_id/'state.json';before=taskpath.read_bytes()
assert len(task.items)==3 and task.writer_id==key
# Cancelling the new-task dialog leaves an existing unsaved stroke untouched.
from handwriting_collector.models import TrajectoryPoint
a.canvas.trajectory.start_stroke(TrajectoryPoint(120,120,.4,0))
a.canvas.trajectory.append_point(TrajectoryPoint(230,120,.8,10));a.canvas.trajectory_changed.emit()
assert not slider.isEnabled()
slider.setValue(16)
assert slider.value()==24 and a.canvas.height()==312 and a.canvas.trajectory.point_count==2
QtCore.QTimer.singleShot(0,lambda:app.activeModalWidget().reject());a.configure_han_task(path)
assert a.task is task and a.canvas.trajectory.point_count==2 and taskpath.read_bytes()==before
original_exec=QtWidgets.QMessageBox.exec
def answer_box(box):
 next(b for b in box.buttons() if b.text()=='返回采集').click();return 0
QtWidgets.QMessageBox.exec=answer_box;a.pause_task();assert a.task is task and a.canvas.trajectory.point_count==2
def discard_box(box):
 next(b for b in box.buttons() if b.text()=='放弃当前笔迹').click();return 0
QtWidgets.QMessageBox.exec=discard_box;a.pause_task();assert a.task is None
assert slider.isEnabled()
QtWidgets.QMessageBox.exec=original_exec
a.open_managed_task(c.tasks()[0]);task=a.task
QtWidgets.QMessageBox.question=lambda *args:QtWidgets.QMessageBox.Yes
a.choose_writer(other);assert a.task.writer_id==other
def ink():
 a.canvas.trajectory.start_stroke(TrajectoryPoint(120,120,.4,0))
 a.canvas.trajectory.append_point(TrajectoryPoint(230,120,.8,10));a.canvas.trajectory_changed.emit()
QtWidgets.QMessageBox.information=lambda *args:None
ink();a.save_current();assert a.task.completed_count==1
saved=taskpath.read_bytes();sample=next((c.root/'samples').rglob('*.json'));raw=sample.read_bytes()
a.pause_task();assert a.task is None and taskpath.read_bytes()==saved and sample.read_bytes()==raw
entry=next(e for e in c.tasks() if e['task'].task_id==task.task_id)
a.open_managed_task(entry);assert a.task.completed_count==1
a.cancel_task();assert a.task is None and c.tasks()[0]['state']=='cancelled' and sample.read_bytes()==raw
# Startup does not reactivate cancelled tasks, even legacy task bytes remain unchanged.
assert taskpath.read_bytes()==saved
fresh=main(['InkStruct'],create_only=True,workspace=root/'workspace');app.processEvents()
assert fresh.single_widget.task is None
assert fresh.single_widget.canvas_size_slider.value()==24 and fresh.single_widget.canvas.height()==312
c.set_state('han',task.task_id,'paused');a.open_managed_task(entry)
assert a.task.completed_count==1
from inkstruct.symbol_revisions import requeue_completed
with a.task_lock():
 r=a._task_dependencies()[1];requeue_completed(c.root,a.task,r,[a.task.items[0].item_id])
assert a.task.completed_count==0 and not sample.exists()
ink();a.save_current();assert a.task.completed_count==1
# A competing save is rejected before another specimen is written.
value=json.loads(taskpath.read_text('utf-8'));value['name']='other window';taskpath.write_text(json.dumps(value),'utf-8')
errors=[];a._capture_error=lambda e:errors.append(str(e));ink()
count=len(list((c.root/'samples').rglob('*.json')));a.save_current()
assert errors and a.canvas.trajectory.point_count and len(list((c.root/'samples').rglob('*.json')))==count
a.canvas.clear();a._close_task()
dialog=TaskListDialog(c);assert dialog.tree.topLevelItemCount()==1;dialog.reject()
entry=c.tasks()[0];original=entry['path'].read_bytes()
def copy_config():
 d=app.activeModalWidget();from inkstruct.capture_workflow_ui import WriterPicker
 d.findChild(WriterPicker).setText(key);d.accept()
QtCore.QTimer.singleShot(0,copy_config);a.edit_task(entry,'copy',a)
assert len(c.tasks())==2 and entry['path'].read_bytes()==original
copied=next(e for e in c.tasks() if e['task'].task_id!=entry['task'].task_id)
assert len(copied['task'].items)==2 and copied['task'].writer_id==key
# Both tabs use the same registered author catalog and symbol config writer picker.
from inkstruct.symbol_task_dialog import SymbolTaskDialog
sd=SymbolTaskDialog(key,b,collection_root=c.root/'symbol_collection',catalog=c)
assert sd.writer.text()==key;sd.select_all(False);sd.groups['digits'].setChecked(True)
source,entries=sd.plan();b._start('digits',entries,source,key)
assert b.task.writer_id==key;b.pause_task();assert b.task is None
fresh.close();w.close();app.processEvents()
'''
    # Keep ordinary UI cases inside Windows' readable path budget. Deep roots
    # have a separate rejection test, rather than silently creating unreadable ink.
    private = tmp_path.parents[1] / ('c' + uuid.uuid4().hex[:6])
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', program, str(private)],
        env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'}, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
