import csv
import os
from pathlib import Path
import subprocess
import sys
import uuid

from inkstruct.recommended_capture import STAGES, recording_stages
from inkstruct.structures import StructureRepository


def test_recommended_stages_match_issued_order_and_stroke_budgets():
    historical = Path(__file__).resolve().parents[1] / 'configs/collection/research_v1/historical400.csv'
    with historical.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    stages = recording_stages()
    assert list(stages) == list(STAGES)
    assert [len(stage.entries) for stage in stages.values()] == [32, 68, 300]
    assert all(entry[1:] == (1, index) for stage in stages.values() for index, entry in enumerate(stage.entries))
    combined = [char for stage in stages.values() for char, _, _ in stage.entries]
    assert len(set(combined)) == 400
    assert combined == [row['character'] for row in rows]
    structures = StructureRepository()
    budgets = [sum(len(structures.get(char).strokes) for char, _, _ in stage.entries) for stage in stages.values()]
    assert budgets == [285, 676, 3217]


def test_recommended_task_counts_valid_legacy_samples_per_writer(tmp_path):
    program = r'''
import json
import sys
import time
from pathlib import Path
from PySide6 import QtCore, QtWidgets
from inkstruct.capture_workflow_ui import RecommendedTaskDialog
from inkstruct.collector import main
from inkstruct.recommended_capture import recording_stages

root = Path(sys.argv[1])
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root / 'settings'))
window = main(['InkStruct'], create_only=True, workspace=root / 'workspace')
window.show()
han = window.single_widget
catalog = han._capture_catalog
writer_a = 'old_writer'
writer_b = catalog.create_writer('同名')
stage = recording_stages()['starter32']
first, second, third, fourth = [entry[0] for entry in stage.entries[:4]]

def specimen(char, writer, name, *, folder=None, stored_writer=None, bad=False, no_ink=False):
    graph = han.structures.get(char)
    strokes = []
    tick = 0
    for stroke in graph.strokes:
        points = []
        for x, y in stroke.median:
            points.append({'x': 30 + 150*x, 'y': 30 + 150*y, 'pressure': .5, 't_ms': tick})
            tick += 1
        if no_ink:
            points = [points[0], points[0]]
        strokes.append({'points': points})
    if bad:
        strokes[0]['points'][0]['x'] = -20
    path = catalog.root / 'samples' / writer / (folder or f'U+{ord(char):04X}') / (name + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {'schema_version': 'handwriting_single_v1', 'sample_id': name, 'character': char,
             'writer_id': stored_writer or writer, 'capture': {'canvas_width': 220, 'canvas_height': 220},
             'task': {'source': 'starter_v61_v1/stage_1_32.csv'}, 'strokes': strokes}
    path.write_text(json.dumps(value), encoding='utf-8')
    return path

def pump(predicate):
    deadline = time.monotonic() + 12
    while not predicate():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for capture progress')
        time.sleep(.01)

legacy = specimen(first, writer_a, 'legacy')
original = legacy.read_bytes()
specimen(first, writer_a, 'duplicate')
specimen(second, writer_a, 'invalid', bad=True)
specimen(third, writer_a, 'foreign', stored_writer=writer_b)
specimen(fourth, writer_a, 'touches', no_ink=True)
corrupt = (catalog.root / 'samples' / writer_a / f'U+{ord(fourth):04X}' / 'corrupt.json')
corrupt.write_text('{', encoding='utf-8')
specimen(second, writer_b, 'imported', folder='import-batch')
specimen(third, writer_b, 'saved')
han.writer_picker.reload(writer_a)
han.choose_writer(writer_a)

buttons = [han.findChild(QtWidgets.QPushButton, 'capture_recommended_' + key)
           for key in ('starter32', 'add68', 'add300')]
assert [b.text() for b in buttons] == ['起步 · 32 字', '推荐 · 补至 100 字', '进阶 · 补至 400 字']
assert all(b.isVisible() for b in buttons)
assert buttons[1].property('inkRole') == 'primary'
assert '新增 300 字 · 每字 1 份' in [label.text() for label in han.findChildren(QtWidgets.QLabel)]
assert not window.symbol_widget.findChild(QtWidgets.QPushButton, 'capture_recommended_starter32')

def check_stage(key, count):
    modal = app.activeModalWidget()
    assert isinstance(modal, RecommendedTaskDialog) and modal.stage.key == key
    pump(lambda: modal.start.isEnabled())
    assert len(modal.entries) == count
    modal.reject()

QtCore.QTimer.singleShot(0, lambda: check_stage('add68', 68))
buttons[1].click()
QtCore.QTimer.singleShot(0, lambda: check_stage('add300', 300))
buttons[2].click()
assert not catalog.tasks()

dialog = RecommendedTaskDialog(catalog, writer_a, stage, han.structures, han)
pump(lambda: dialog.start.isEnabled())
assert dialog.entries == stage.entries[1:]
assert '剩余 31 字' in dialog.summary.text()
dialog.writer.setText(writer_b)
dialog.writer.setText(writer_a)
dialog.writer.setText(writer_b)
pump(lambda: dialog.start.isEnabled())
assert [c for c, _, _ in dialog.entries[:2]] == [first, fourth]
assert '剩余 30 字' in dialog.summary.text()
dialog.reject()
dialog.deleteLater()

def start_stage():
    modal = app.activeModalWidget()
    assert isinstance(modal, RecommendedTaskDialog)
    if not modal.start.isEnabled():
        QtCore.QTimer.singleShot(10, start_stage)
        return
    modal.start.click()

QtCore.QTimer.singleShot(0, start_stage)
buttons[0].click()
assert han.task.writer_id == writer_a and han.task.current_item().character == second
assert len(han.task.items) == 31 and han.progress_bar.maximum() == 32 and han.progress_bar.value() == 1
assert '剩余 31' in han.progress_label.text()
task_id = han.task.task_id
han.pause_task()
QtCore.QTimer.singleShot(0, start_stage)
buttons[0].click()
assert han.task.task_id == task_id
assert len(catalog.tasks()) == 1

QtWidgets.QMessageBox.question = lambda *args: QtWidgets.QMessageBox.Yes
han.writer_picker.setText(writer_b)
assert han.task is None and han.writer_edit.text() == writer_b
QtCore.QTimer.singleShot(0, start_stage)
buttons[0].click()
assert han.task.writer_id == writer_b and han.task.task_id != task_id
assert han.task.current_item().character == first
assert han.progress_bar.value() == 2 and '剩余 30' in han.progress_label.text()

from handwriting_collector.models import TrajectoryPoint

tick = 0
for stroke in han.structures.get(first).strokes:
    points = [TrajectoryPoint(30 + 150*x, 30 + 150*y, .5, tick + i)
              for i, (x, y) in enumerate(stroke.median)]
    han.canvas.trajectory.start_stroke(points[0])
    for point in points[1:]:
        han.canvas.trajectory.append_point(point)
    tick += len(points)
han.save_current()
assert han.task.completed_count == 1
assert han.progress_bar.value() == 3 and '剩余 29' in han.progress_label.text()
writer_b_task = han.task.task_id
han.pause_task()
QtCore.QTimer.singleShot(0, start_stage)
buttons[0].click()
assert han.task.task_id == writer_b_task and han.task.current_item().character == fourth
assert han.progress_bar.value() == 3

han.pause_task()
for char, _, _ in stage.entries:
    specimen(char, writer_b, f'complete-{ord(char):04X}')
complete = RecommendedTaskDialog(catalog, writer_b, stage, han.structures, han)
pump(lambda: '均已有合格样本' in complete.summary.text())
assert not complete.start.isEnabled() and complete.entries == ()
assert len(catalog.tasks()) == 2
complete.reject()
assert legacy.read_bytes() == original
window.close()
app.processEvents()
'''
    isolated = tmp_path.parents[1] / ('rec-' + uuid.uuid4().hex[:8])
    run = subprocess.run(
        [sys.executable, '-B', '-X', 'utf8', '-c', program, str(isolated)],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
