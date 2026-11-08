import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6 import QtCore, QtGui, QtWidgets

from inkstruct.collector import _collector_source
from inkstruct.symbol_capture_ui import create_symbol_widget_class

sys.path.insert(0, str(_collector_source()))
from handwriting_collector import ui
from handwriting_collector.models import TrajectoryPoint


def create_task(widget, groups=('digits',), repeats=5):
    from inkstruct.symbol_task_dialog import SymbolTaskDialog
    def configure():
        dialog = QtWidgets.QApplication.activeModalWidget()
        assert isinstance(dialog, SymbolTaskDialog)
        dialog.select_all(False)
        for group in groups:
            dialog.groups[group].setChecked(True)
        dialog.repeats.setValue(repeats)
        dialog.accept()
    QtCore.QTimer.singleShot(0, configure)
    widget.example_button.click()


def canvas_settings(tmp_path):
    settings = QtCore.QSettings(str(tmp_path / 'canvas.ini'), QtCore.QSettings.Format.IniFormat)
    settings.setValue('canvas_percent', 100)
    return settings


def test_real_symbol_task_save_variable_strokes_and_resume(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args: None)
    cls = create_symbol_widget_class(ui, QtCore, QtGui, QtWidgets)
    widget = cls(lambda: tmp_path, settings=canvas_settings(tmp_path))
    widget.show()
    app.processEvents()
    create_task(widget)
    assert len(widget.task.items) == 50
    assert widget.task.current_item().character == "0"
    for n in (1, 2):
        for i in range(n):
            widget.canvas.trajectory.start_stroke(TrajectoryPoint(150, 150, 0.5, i * 10))
            widget.canvas.trajectory.append_point(TrajectoryPoint(200, 250, 0.5, i * 10 + 5))
        widget.canvas._pen_down = True
        widget.canvas.trajectory_changed.emit()
        assert not widget.save_button.isEnabled()
        widget.save_current()
        assert widget.task.completed_count == n - 1
        widget.canvas._pen_down = False
        widget.canvas.trajectory_changed.emit()
        assert widget.save_button.isEnabled()
        widget.save_button.click()
        assert widget.task.completed_count == n
    widget.resize(1200, 950)
    app.processEvents()
    assert (widget.canvas.width(), widget.canvas.height()) == (560, 320)
    assert len(list((tmp_path / "symbol_collection/samples").rglob("*.json"))) == 2
    reopened = cls(lambda: tmp_path, settings=canvas_settings(tmp_path))
    reopened.resume_task()
    assert reopened.task.completed_count == 2
    assert reopened.task.current_item().repeat_index == 3
    assert all(
        a.shortcutContext() == QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        for a in widget.actions()
    )
    widget.close()
    reopened.close()


def test_task_keeps_output_directory_and_new_task_can_switch(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    chosen = [tmp_path / "first"]
    cls = create_symbol_widget_class(ui, QtCore, QtGui, QtWidgets)
    widget = cls(lambda: chosen[0])
    create_task(widget)
    original = widget._task_dependencies()[0]
    chosen[0] = tmp_path / "second"
    assert widget._task_dependencies()[0] == original
    create_task(widget)
    assert widget._task_dependencies()[0] == chosen[0] / "symbol_collection"
    app.processEvents()
    widget.close()


def test_windows_canvas_scale_and_letter_style_roundtrip(tmp_path, monkeypatch):
    import json

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args: None)
    settings = QtCore.QSettings(str(tmp_path / "canvas.ini"), QtCore.QSettings.Format.IniFormat)
    cls = create_symbol_widget_class(ui, QtCore, QtGui, QtWidgets)
    widget = cls(lambda: tmp_path, settings=settings)
    widget.canvas_size_slider.setValue(30)
    assert (widget.canvas.width(), widget.canvas.height()) == (840, 480)
    create_task(widget, ('latin_upright',))
    widget.canvas.trajectory.start_stroke(TrajectoryPoint(200, 150, 0.4, 0))
    widget.canvas.trajectory.append_point(TrajectoryPoint(250, 250, 0.8, 10))
    widget.canvas.trajectory_changed.emit()
    widget.canvas_size_slider.setValue(10)
    assert widget.canvas.width() == 840
    widget.save_current()
    sample = json.loads(next((tmp_path / "symbol_collection/samples").rglob("*.json")).read_text(encoding='utf-8'))
    assert sample["variant"]["letter_style"] == "upright"
    assert sample["guides"]["em_px"] == 300
    reopened = cls(lambda: tmp_path, settings=settings)
    reopened.resume_task()
    assert reopened.canvas.width() == 840
    assert '英文正体' in reopened.identity_label.text()
    widget.close()
    reopened.close()
    app.processEvents()


def test_mixed_latin_styles_repeat_count_resume_and_cancel(tmp_path, monkeypatch):
    import json

    from handwriting_collector.tasks import TaskRepository

    from inkstruct.symbol_task_dialog import SymbolTaskDialog
    from inkstruct.symbol_tasks import item_letter_style
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    cls = create_symbol_widget_class(ui, QtCore, QtGui, QtWidgets)
    widget = cls(lambda: tmp_path, settings=canvas_settings(tmp_path))
    assert widget.example_button.text() == '创建任务'
    assert not hasattr(widget, 'group_combo') and not hasattr(widget, 'letter_style_combo')
    create_task(widget, ('latin_upright', 'latin_italic', 'digits'), 3)
    task = widget.task
    assert len(task.items) == (52 + 52 + 10) * 3
    assert [(i.repeat_total, item_letter_style(task, i)) for i in task.items if i.character == 'A'] == [(3, 'upright')] * 3 + [(3, 'italic')] * 3
    # Persist progress at the second A, then save a real specimen after reopening.
    task.cursor = next(i for i, item in enumerate(task.items) if item.character == 'A' and item_letter_style(task, item) == 'italic')
    TaskRepository(tmp_path / 'symbol_collection').save(task)
    reopened = cls(lambda: tmp_path, settings=canvas_settings(tmp_path))
    reopened.resume_task()
    assert '英文斜体' in reopened.identity_label.text()
    reopened.canvas.trajectory.start_stroke(TrajectoryPoint(180, 120, .4, 0))
    reopened.canvas.trajectory.append_point(TrajectoryPoint(240, 210, .8, 10))
    reopened.save_current()
    sample = json.loads(next((tmp_path / 'symbol_collection/samples').rglob('*.json')).read_text(encoding='utf-8'))
    assert sample['variant']['letter_style'] == 'italic' and sample['task']['repeat_total'] == 3
    before = widget.task.task_id
    QtCore.QTimer.singleShot(0, lambda: app.activeModalWidget().reject())
    widget.example_button.click()
    assert widget.task.task_id == before
    dialog = SymbolTaskDialog('user_001')
    assert dialog.repeats.value() == 5
    dialog.select_all(False)
    assert not dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
    dialog.reject()
    # Archived v1 task styles remain readable.
    legacy = task.__class__.create('legacy', 'inkstruct:symbol_catalog_v1:upright', 'user_001', [('A', 5, 0)])
    assert item_letter_style(legacy, legacy.current_item()) == 'upright'
    widget.close(); reopened.close(); app.processEvents()


def test_import_preserves_row_counts_and_separates_latin_styles():
    from inkstruct.symbol_task_dialog import SymbolTaskDialog
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = SymbolTaskDialog('scx', imported=[('A', 7, 0), ('1', 2, 1)])
    dialog.select_all(False)
    for key in ('latin_upright', 'latin_italic', 'digits'):
        dialog.groups[key].setChecked(True)
    _, entries = dialog.plan()
    assert entries == [('A', 7, 0), ('A', 7, 1), ('1', 2, 2)]
    assert '16' in dialog.summary.text()
    assert not dialog.repeats.isVisible()
    dialog.reject(); app.processEvents()


def test_chinese_punctuation_task_and_shared_import():
    from inkstruct.symbol_tasks import TASK_GROUPS
    from inkstruct.symbol_task_dialog import SymbolTaskDialog
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = SymbolTaskDialog('user_001')
    dialog.select_all(False)
    dialog.groups['punctuation'].setChecked(True)
    _, entries = dialog.plan()
    assert ''.join(c for c, _, _ in entries) == TASK_GROUPS['punctuation'][1]
    assert sum(n for _, n, _ in entries) == 5 * len(entries)
    dialog.reject()
    dialog = SymbolTaskDialog('user_001', imported=[('，', 5, 0), (',', 5, 1), ('（', 3, 2)])
    _, entries = dialog.plan()
    assert len(entries) == 2 and sum(n for _, n, _ in entries) == 8
    dialog.reject(); app.processEvents()


def test_large_preview_and_rerecord_same_style(tmp_path,monkeypatch):
    from inkstruct.symbol_review_dialog import SymbolReviewDialog
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    errors=[]
    monkeypatch.setattr(QtWidgets.QMessageBox,'warning',lambda *args:errors.append(args[-1]))
    cls=create_symbol_widget_class(ui,QtCore,QtGui,QtWidgets)
    widget=cls(lambda:tmp_path,settings=canvas_settings(tmp_path))
    widget.show(); app.processEvents()
    create_task(widget,('latin_upright',),5)
    assert widget.target_label.fontMetrics().height()>=80
    assert widget.target_label.height()>=140
    for _ in range(8):
        widget.canvas.trajectory.start_stroke(TrajectoryPoint(150,150,.5,0))
        widget.canvas.trajectory.append_point(TrajectoryPoint(220,220,.8,10))
        widget.save_current()
    assert widget.task.completed_count==8
    # Cancel is a read-only inspection.
    QtCore.QTimer.singleShot(0,lambda:app.activeModalWidget().reject())
    widget.review_button.click()
    assert widget.task.completed_count==8
    def choose():
        d=app.activeModalWidget()
        assert isinstance(d,SymbolReviewDialog)
        d.select_same()
        assert len(d.selected_ids())==3 and d.preview.value['character']=='B'
        d.accept()
    QtCore.QTimer.singleShot(0,choose)
    widget.review_button.click()
    assert not errors, errors
    assert widget.task.completed_count==5
    assert widget.task.current_item().character=='B' and widget.task.current_item().repeat_index==1
    assert not widget.canvas.trajectory.point_count
    widget.close(); app.processEvents()


def test_finished_task_can_reopen_for_rerecord(tmp_path,monkeypatch):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(QtWidgets.QMessageBox,'information',lambda *args:None)
    cls=create_symbol_widget_class(ui,QtCore,QtGui,QtWidgets)
    widget=cls(lambda:tmp_path,settings=canvas_settings(tmp_path))
    widget._start('finished',[('B',1,0)])
    widget.canvas.trajectory.start_stroke(TrajectoryPoint(150,150,.5,0))
    widget.canvas.trajectory.append_point(TrajectoryPoint(220,220,.8,10))
    widget.save_current()
    assert widget.task.is_complete
    reopened=cls(lambda:tmp_path,settings=canvas_settings(tmp_path))
    reopened.resume_task()
    assert reopened.task.is_complete and reopened.review_button.isEnabled()
    QtCore.QTimer.singleShot(0,lambda:app.activeModalWidget().accept())
    reopened.review_button.click()
    assert reopened.task.completed_count==0 and reopened.task.current_item().character=='B'
    widget.close(); reopened.close(); app.processEvents()
