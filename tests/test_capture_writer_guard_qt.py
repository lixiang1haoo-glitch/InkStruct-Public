import os
import subprocess
import sys
import uuid


def test_save_during_writer_change_cannot_reassign_newly_saved_specimen(tmp_path):
    program = r'''
import sys,json
from pathlib import Path
from PySide6 import QtCore,QtWidgets
from inkstruct.collector import main
app=QtWidgets.QApplication([]);root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
w=main(['InkStruct'],create_only=True,workspace=root/'w');w.show();app.processEvents()
a=w.single_widget;c=a._capture_catalog;x=c.create_writer('原作者');y=c.create_writer('新作者')
from handwriting_collector.tasks import CollectionTask,TaskRepository
from handwriting_collector.models import TrajectoryPoint
t=CollectionTask.create('采集','test',x,[('一',2,0)]);TaskRepository(c.root).save(t);a.set_task(t)
a.canvas.trajectory.start_stroke(TrajectoryPoint(120,120,.4,0))
a.canvas.trajectory.append_point(TrajectoryPoint(230,120,.8,10));a.canvas.trajectory_changed.emit()
# Reproduce choosing Save and Continue in the unsaved-ink guard.
def save_and_continue():
 a.save_current();return not a.canvas.trajectory.point_count
a._can_switch=save_and_continue
QtWidgets.QMessageBox.question=lambda *args:(_ for _ in ()).throw(AssertionError('must not ask to reassign saved ink'))
a.choose_writer(y)
assert a.task.completed_count==1 and a.task.writer_id==x and a.writer_picker.text()==x
sample=json.loads(next((c.root/'samples').rglob('*.json')).read_text('utf-8'))
assert sample['writer_id']==x and TaskRepository(c.root).load(TaskRepository(c.root).path_for(t.task_id)).writer_id==x
a._can_switch=lambda:True;w.close()
'''
    private = tmp_path.parents[1] / ('g' + uuid.uuid4().hex[:6])
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', program, str(private)],
        env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'}, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
