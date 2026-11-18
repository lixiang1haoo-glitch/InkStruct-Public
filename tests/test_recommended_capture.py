import csv
import os
from pathlib import Path
import subprocess
import sys
import uuid

from inkstruct.recommended_capture import CUMULATIVE_PREFIX, SOURCE_PREFIX, recording_stages, stage_size
from inkstruct.structures import StructureRepository


def test_cumulative_goals_keep_the_issued_order_and_legacy_sizes():
    historical = Path(__file__).resolve().parents[1] / "configs/collection/research_v1/historical400.csv"
    with historical.open(encoding="utf-8-sig", newline="") as stream:
        characters = [row["character"] for row in csv.DictReader(stream)]
    stages = recording_stages()
    assert [len(stage.entries) for stage in stages.values()] == [32, 100, 400]
    for stage in stages.values():
        assert [char for char, _, _ in stage.entries] == characters[:len(stage.entries)]
        assert all((copies, index) == (1, i) for i, (_, copies, index) in enumerate(stage.entries))
        assert stage.source == CUMULATIVE_PREFIX + stage.key
    assert [stage_size(SOURCE_PREFIX + key) for key in stages] == [32, 68, 300]
    assert [stage_size(stage.source) for stage in stages.values()] == [32, 100, 400]
    structures = StructureRepository()
    assert [sum(len(structures.get(c).strokes) for c, _, _ in stage.entries)
            for stage in stages.values()] == [285, 961, 4178]


def test_unified_creation_cumulative_missing_legacy_resume_and_import(tmp_path):
    program = r'''
import json
import sys
import time
from pathlib import Path
from PySide6 import QtCore, QtWidgets
from handwriting_collector.tasks import CollectionTask, TaskRepository
from inkstruct.capture_task_dialog import CaptureTaskDialog
from inkstruct.collector import main
from inkstruct.recommended_capture import SOURCE_PREFIX, recording_stages

root = Path(sys.argv[1])
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root / "settings"))
window = main(["InkStruct"], create_only=True, workspace=root / "workspace")
window.show()
han, symbol = window.single_widget, window.symbol_widget
catalog = han._capture_catalog
writer_a, writer_b = catalog.create_writer("甲"), catalog.create_writer("乙")
stages = recording_stages()
first, second, third, fourth = [e[0] for e in stages["starter32"].entries[:4]]

def specimen(char, writer, name, *, stored_writer=None, bad=False, no_ink=False):
    strokes, tick = [], 0
    for stroke in han.structures.get(char).strokes:
        points = [{"x":30+150*x,"y":30+150*y,"pressure":.5,"t_ms":tick+i}
                  for i,(x,y) in enumerate(stroke.median)]
        tick += len(points)
        strokes.append({"points": [points[0],points[0]] if no_ink else points})
    if bad:
        strokes[0]["points"][0]["x"] = -20
    path = catalog.root/"samples"/writer/f"U+{ord(char):04X}"/(name+".json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"schema_version":"handwriting_single_v1","sample_id":name,
        "character":char,"writer_id":stored_writer or writer,"task":{"source":"legacy.csv"},
        "capture":{"canvas_width":220,"canvas_height":220},"strokes":strokes}),encoding="utf-8")
    return path

legacy_sample=specimen(first,writer_a,"legacy")
original_sample=legacy_sample.read_bytes()
specimen(first,writer_a,"duplicate")
specimen(second,writer_a,"invalid",bad=True)
specimen(third,writer_a,"foreign",stored_writer=writer_b)
specimen(fourth,writer_a,"touches",no_ink=True)
specimen(second,writer_b,"valid")
han.choose_writer(writer_a)
app.processEvents()
assert han.capture_workspace.stack.currentIndex()==0 and not han.canvas.isVisible()
assert han.new_task_button.isVisible()
assert not han.findChild(QtWidgets.QPushButton,"capture_recommended_starter32")

def pump(predicate):
    deadline=time.monotonic()+15
    while not predicate():
        app.processEvents()
        if time.monotonic()>deadline:
            raise AssertionError("Capture operation timed out")
        time.sleep(.005)

dialog=CaptureTaskDialog(han)
pump(lambda:dialog.job is None)
for key,count in (("starter32",31),("add68",99),("add300",399)):
    dialog.select_stage(key)
    assert len(dialog.entries)==count and dialog.start.isEnabled()
    assert first not in [c for c,_,_ in dialog.entries]
    assert dialog.counts["existing"].text()=="1 字"
dialog.select_preview(True)
assert dialog.preview.count()==400
dialog.reject()
dialog.dispose()
assert not catalog.tasks()

legacy_entries=tuple((c,n,i) for i,(c,n,_) in enumerate(stages["add68"].entries[32:]))
old=CollectionTask.create("旧 68 字任务",SOURCE_PREFIX+"add68",writer_a,legacy_entries)
repo=TaskRepository(catalog.root)
repo.save(old)
old_path=repo.path_for(old.task_id)
old_bytes=old_path.read_bytes()
han.open_managed_task(next(e for e in catalog.tasks() if e["task"].task_id==old.task_id))
assert len(han.task.items)==68 and han.progress_bar.maximum()==68
han.pause_task()
assert old_path.read_bytes()==old_bytes and han.capture_workspace.recent.topLevelItemCount()==1
item=han.capture_workspace.recent.topLevelItem(0)
han.capture_workspace.resume(item.data(0,QtCore.Qt.ItemDataRole.UserRole))
pump(lambda:han.task is not None)
assert han.task.task_id==old.task_id
han.pause_task()

def accept_new():
    modal=app.activeModalWidget()
    assert isinstance(modal,CaptureTaskDialog)
    if modal.job is not None:
        QtCore.QTimer.singleShot(10,accept_new)
        return
    modal.select_stage("add68")
    modal.start.click()

QtCore.QTimer.singleShot(0,accept_new)
han.new_task_button.click()
assert len(han.task.items)==99 and han.progress_bar.maximum()==99 and han.progress_bar.value()==0
new_id=han.task.task_id
assert han.task.source!=old.source
han.pause_task()
QtCore.QTimer.singleShot(0,accept_new)
han.new_task_button.click()
assert han.task.task_id==new_id
han.pause_task()
han.choose_writer(writer_b)
dialog=CaptureTaskDialog(han)
pump(lambda:dialog.job is None)
dialog.select_stage("starter32")
assert len(dialog.entries)==31 and dialog.entries[0][0]==first
dialog.reject()
dialog.dispose()

path=root/"conflict.csv"
path.write_text("character,repeats\n一,2\n一,3\n",encoding="utf-8")
dialog=CaptureTaskDialog(han,path=path)
assert not dialog.start.isEnabled() and "冲突" in dialog.error.text()
path.write_text("character,repeats\n一,2\n十,1\n",encoding="utf-8")
dialog.read_file()
assert dialog.start.isEnabled() and sum(n for _,n,_ in dialog.entries)==3
dialog.reject()
dialog.dispose()
assert len(catalog.tasks())==2 and han.task is None

symbol.choose_writer(writer_b)
dialog=CaptureTaskDialog(symbol)
assert dialog.sources.tabText(0)=="按类别选字" and not dialog.start.isEnabled()
dialog.selection.groups["digits"].setChecked(True)
dialog.selection.repeats.setValue(1)
assert dialog.start.isEnabled() and len(dialog.entries)==10
source,entries=dialog.source,dialog.entries
dialog.accept()
dialog.dispose()
symbol._start("数字",entries,source,writer_b)
symbol_id=symbol.task.task_id
assert len(symbol.task.items)==10
symbol.pause_task()
symbol.capture_workspace.resume(next(e for e in catalog.tasks() if e["task"].task_id==symbol_id))
pump(lambda:symbol.task is not None)
assert symbol.task.task_id==symbol_id
symbol.pause_task()
assert legacy_sample.read_bytes()==original_sample and old_path.read_bytes()==old_bytes
for char,_,_ in stages["add68"].entries:
    specimen(char,writer_a,f"complete-{ord(char):04X}")
han.choose_writer(writer_a)
complete=CaptureTaskDialog(han)
pump(lambda:complete.job is None)
assert complete.entries==() and not complete.start.isEnabled()
assert complete.counts["target"].text()=="100 字"
assert complete.counts["existing"].text()=="100 字"
complete.reject()
complete.dispose()
assert len(catalog.tasks())==3
from handwriting_collector.models import TrajectoryPoint
from inkstruct.symbol_tasks import task_plan

source,entries=task_plan(["latin_upright"],1)
symbol._start("复用供体",entries,source,writer_b)
width,height=symbol.canvas.width(),symbol.canvas.height()
symbol.canvas.trajectory.start_stroke(TrajectoryPoint(width*.3,height*.4,.5,0))
symbol.canvas.trajectory.append_point(TrajectoryPoint(width*.45,height*.7,.5,50))
symbol.save_current()
assert symbol.task.completed_count==1
sample_id=symbol.task.items[0].sample_id
symbol.pause_task()
reuse=CaptureTaskDialog(symbol)
reuse.selection.reuse[("latin_italic","A")]={
    "group":"latin_italic","target":"A","source":"A","source_style":"upright",
    "sample_ids":[sample_id],"confirmed":True}
reuse.selection.update_summary()
assert reuse.start.isEnabled() and reuse.entries==[]
assert reuse.counts["target"].text()=="1 字／写法" and reuse.counts["existing"].text()=="1 字"
assert reuse.counts["copies"].text()=="0 份"
reuse.select_preview(True)
assert reuse.preview.count()==1 and "复用" in reuse.preview.item(0).text()
reuse.accept()
source,entries=reuse.source,reuse.entries
reuse.dispose()
symbol._start("供体复用",entries,source,writer_b)
from inkstruct.symbol_tasks import source_configuration
assert not symbol.task.items and source_configuration(symbol.task.source)["reuse"][0]["sample_ids"]==[sample_id]
assert symbol.capture_workspace.complete.text()=="复用配置已保存"
symbol.pause_task()
assert all(symbol.capture_workspace.recent.topLevelItem(i).text(0)!="供体复用"
           for i in range(symbol.capture_workspace.recent.topLevelItemCount()))
from inkstruct.capture_workflow_ui import TaskListDialog

def rename_old():
    modal=app.activeModalWidget()
    assert isinstance(modal,TaskListDialog)
    for index in range(modal.tree.topLevelItemCount()):
        item=modal.tree.topLevelItem(index)
        entry=item.data(0,QtCore.Qt.ItemDataRole.UserRole)
        if entry["task"].task_id==old.task_id:
            modal.tree.setCurrentItem(item)
            modal.choose("rename")
            return
    raise AssertionError("Old task was absent from task management")

original_input=QtWidgets.QInputDialog.getText
han.choose_writer(writer_a)
QtWidgets.QInputDialog.getText=lambda *args,**kwargs:("重命名的旧任务",True)
QtCore.QTimer.singleShot(0,rename_old)
han.task_list()
QtWidgets.QInputDialog.getText=original_input
assert any(han.capture_workspace.recent.topLevelItem(i).text(0)=="重命名的旧任务"
           for i in range(han.capture_workspace.recent.topLevelItemCount()))
original_directory=QtWidgets.QFileDialog.getExistingDirectory
QtWidgets.QFileDialog.getExistingDirectory=lambda *args,**kwargs:str(root/"new-capture")
window.choose_output_root()
QtWidgets.QFileDialog.getExistingDirectory=original_directory
assert han.capture_workspace.recent.topLevelItemCount()==0
assert not han.writer_edit.text() and not han.capture_workspace.begin.isEnabled()
assert legacy_sample.read_bytes()==original_sample
window.close()
app.processEvents()
'''
    isolated = tmp_path.parents[1] / ("rec-" + uuid.uuid4().hex[:8])
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", program, str(isolated)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
