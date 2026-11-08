"""Template GUI roles, drafts, direct manipulation and frozen-data transactions."""

import os
import subprocess
import sys

import pytest

PROGRAM = r"""
import sys,time
from dataclasses import replace
from pathlib import Path
from PySide6 import QtCore,QtGui,QtWidgets,QtTest
from inkstruct.document.flow_template import FlowTemplate,PageLayout,TextFrame,NamedField
from inkstruct.document.template import Region
from inkstruct.document.styles import FlowStyle
from inkstruct.editor.flow_template_designer import FlowTemplateDesigner
from inkstruct.editor.template_content import TemplateContentDialog
from inkstruct.editor.template_manager import TemplatePicker,remember_template,perform_template_action
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.document.package import save_package,load_package
from inkstruct.renderers.pages import page_svg
app=QtWidgets.QApplication([])
root=Path(sys.argv[1]);scenario=sys.argv[2]
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root))
t=FlowTemplate(name='GUI fixture',kind='custom',width_mm=120,height_mm=120,
    layouts=(PageLayout('one','内页 1',(TextFrame('b','正文框',Region('b',5,40,100,50)),TextFrame('f','姓名框',Region('f',5,5,50,20),'field',field_id='name'))),PageLayout('two','内页 2',(TextFrame('b','正文框',Region('b',10,40,90,50)),))),
    loop_pages=('one','two'),fields=(NamedField('name','姓名',True),NamedField('date','日期',False,'date')))
def wait(test):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        app.processEvents()
        if test():return
        time.sleep(.01)
    raise AssertionError('Timed out')
def ready(w):wait(lambda:w.snapshot and not w.timer.isActive() and not w.worker)
w=MixedWindow(source=':::field name\r\n123\r\n:::\r\n\r\n456\r\n\r\n789')
w.flow=replace(w.flow,template=t);w.schedule_layout();ready(w);w.recovery_timer.stop()
before=(w.source_session.source,w.source_session.atom_ids,w.resolver.selection_records(),w.flow,w.style,w.page)
if scenario=='workbench':
    d=FlowTemplateDesigner(t,editor=w);d.show();app.processEvents()
    assert d.tabs.isHidden() and d.page_tree.isVisible()
    assert d.property_scroll.horizontalScrollBar().maximum()==0
    assert d.configuration()==t
    assert not any('应用' in b.text() and '草稿' in b.text() for b in d.findChildren(QtWidgets.QPushButton) if b.isVisible())
    d.select_frame('f');assert d.frame_box.isVisible() and d.frame_name.text()=='姓名框'
    d.frame_name.setText('改名');assert d.flush();assert d.template.layouts[0].frames[1].field_id=='name'
    assert d.template.layouts[0].frames[1].label=='改名'
    d.history(False);assert d.template==t
    d.history(True);assert d.template.layouts[0].frames[1].label=='改名'
    d.geometry_controls['x_mm'].setValue(200)
    assert not d.flush();assert d.template.layouts[0].frames[1].region.x_mm==5
    assert d.error.text()
    d.geometry_controls['x_mm'].setValue(5);assert d.flush()
    d.select_frame('b');p=d.current_layout();r=p.frames[0].region
    scale=min((d.canvas.width()-20)/t.width_mm,(d.canvas.height()-20)/t.height_mm)
    a=QtCore.QPoint(round(10+(r.x_mm+10)*scale),round(10+(r.y_mm+10)*scale))
    b=a+QtCore.QPoint(round(3*scale),round(2*scale))
    QtTest.QTest.mousePress(d.canvas,QtCore.Qt.LeftButton,pos=a)
    QtTest.QTest.mouseMove(d.canvas,b,20)
    QtTest.QTest.mouseRelease(d.canvas,QtCore.Qt.LeftButton,pos=b)
    assert abs(d.selected_frame().region.x_mm-8)<1
    assert abs(d.selected_frame().region.y_mm-42)<1
    d.history(False);assert d.selected_frame().region==r
    edge=QtCore.QPoint(round(10+(r.x_mm+r.width_mm)*scale),round(10+(r.y_mm+r.height_mm)*scale))
    enlarged=edge+QtCore.QPoint(round(5*scale),round(5*scale))
    QtTest.QTest.mousePress(d.canvas,QtCore.Qt.LeftButton,pos=edge)
    QtTest.QTest.mouseMove(d.canvas,enlarged,20)
    QtTest.QTest.mouseRelease(d.canvas,QtCore.Qt.LeftButton,pos=enlarged)
    assert d.selected_frame().region.width_mm>104 and d.selected_frame().region.height_mm>54
    d.history(False);assert d.selected_frame().region==r
    loop=d.page_tree.topLevelItem(0);d.page_tree.setCurrentItem(loop.child(1));d.tree_move(-1)
    assert d.template.loop_pages==('two','one')
    d.history(False);assert d.template.loop_pages==t.loop_pages
    d.field_list.setCurrentRow(0)
    def rename_field():
        modal=app.activeModalWidget();modal.label.setText('姓名显示名');modal.accept()
    QtCore.QTimer.singleShot(10,rename_field);d.declare_field(False)
    assert d.template.fields[0].field_id=='name' and d.template.fields[0].label=='姓名显示名'
    d.reject();assert before==(w.source_session.source,w.source_session.atom_ids,w.resolver.selection_records(),w.flow,w.style,w.page)
    shared=FlowTemplateDesigner(replace(t,start_pages=('one','one','two')),editor=w)
    assert shared.tree_data()==('one','start_pages',0)
    shared.page_tree.setCurrentItem(shared.page_tree.topLevelItem(0).child(1))
    assert shared.tree_data()==('one','start_pages',1)
    shared.refresh();assert shared.tree_data()==('one','start_pages',1)
    assert shared.tree_move(1) and shared.tree_data()==('one','start_pages',2)
    shared.tree_remove()
    assert shared.template.start_pages==('one','two') and shared.template.loop_pages==t.loop_pages
    shared.page_tree.setCurrentItem(shared.page_tree.topLevelItem(0).child(0))
    shared.select_frame('f')
    declaration=NamedField('new_field','新字段')
    shared.ask_field=lambda _candidate: declaration
    picker=QtWidgets.QInputDialog.getItem
    QtWidgets.QInputDialog.getItem=lambda *args: ('新建字段…',True)
    checkpoint=len(shared.undo_stack)
    shared.create_frame('field',(70,12,30,18))
    assert len(shared.undo_stack)==checkpoint+1
    assert [f.field_id for f in shared.current_layout().frames if f.role=='field']==['name','new_field']
    shared.history(False)
    assert shared.template.fields==t.fields and shared.current_layout().frames==t.layouts[0].frames
    shared.ask_field=lambda _candidate: None
    shared.create_frame('field',(70,12,30,18))
    assert shared.template.fields==t.fields and shared.current_layout().frames==t.layouts[0].frames
    QtWidgets.QInputDialog.getItem=picker
    shared.reject();shared.deleteLater()
    precise=replace(FlowTemplate(),width_mm=210.123456789,margins_mm=(20.123456789,20,20,20))
    simple=FlowTemplateDesigner(precise);simple.show();app.processEvents()
    assert not simple.left_panel.isVisible() and not simple.property_tabs.isTabVisible(1)
    assert simple.configuration()==precise
    simple.name.setText('仅改名称');assert simple.flush();assert simple.template.width_mm==precise.width_mm and simple.template.margins_mm==precise.margins_mm
    simple.reject();simple.deleteLater();d.deleteLater()
elif scenario=='form':
    d=TemplateContentDialog(t,w.source_session.source)
    d.show();app.processEvents()
    assert d.source.isHidden() and len(d.inputs)==2
    assert d.configuration()==w.source_session.source
    d.inputs['name'].setPlainText('321')
    assert d.configuration()==w.source_session.source.replace('123','321')
    d.inputs['date'].setPlainText('2026-10-19')
    combined=d.configuration();assert combined.endswith(w.source_session.source.replace('123','321'))
    assert combined.startswith(':::field date\r\n2026-10-19\r\n:::\r\n\r\n')
    d.reject();assert w.source_session.source==before[0]
    duplicate=TemplateContentDialog(t,':::field name\n1\n:::\n\n:::field name\n2\n:::\n\n789')
    assert duplicate.blocked and not duplicate.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
    assert duplicate.configuration().endswith('789');duplicate.reject();duplicate.deleteLater()
    def fill():
        modal=app.activeModalWidget();assert isinstance(modal,TemplateContentDialog)
        modal.inputs['name'].setPlainText('321');modal.accept()
    QtCore.QTimer.singleShot(10,fill);w.template_content_panel.edit();ready(w)
    assert w.source_session.source==before[0].replace('123','321')
    tail=before[0].index('456');assert w.source_session.atom_ids[tail:]==before[1][tail:]
    w.source_history('undo');ready(w);assert w.source_session.source==before[0]
    w.source_history('redo');ready(w);assert w.source_session.source==before[0].replace('123','321')
    save_package(root/'form.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    reopened=load_package(root/'form.inkdoc');assert reopened.session.atom_ids==w.source_session.atom_ids and reopened.flow==w.flow
    original_source=w.source_session.source
    w.template_content_panel.fields.setCurrentItem(None)
    def view_source():
        modal=app.activeModalWidget();assert modal.source_field_id=='name'
        modal.source_button.click()
    QtCore.QTimer.singleShot(10,view_source);w.template_content_panel.edit()
    assert w.editor.textCursor().selectedText().startswith(':::field name')
    assert w.source_session.source==original_source
    pending=TemplateContentDialog(t,original_source);pending.inputs['name'].setPlainText('999')
    question=QtWidgets.QMessageBox.question
    QtWidgets.QMessageBox.question=lambda *a,**kw:QtWidgets.QMessageBox.Cancel
    pending.view_source();assert pending.result()!=2
    QtWidgets.QMessageBox.question=lambda *a,**kw:QtWidgets.QMessageBox.Discard
    pending.view_source();assert pending.result()==2 and w.source_session.source==original_source
    QtWidgets.QMessageBox.question=question;pending.deleteLater()
    d.deleteLater()
elif scenario=='scopes_history':
    s=SettingsDialog(w);s.show();app.processEvents()
    assert not {'templates','paper','font'} & s.items.keys()
    assert not any(b.text()=='打开模板库' for b in s.findChildren(QtWidgets.QPushButton))
    assert s.buttons.isVisible()
    assert before==(w.source_session.source,w.source_session.atom_ids,w.resolver.selection_records(),w.flow,w.style,w.page)
    def cancel():
        modal=app.activeModalWidget();assert isinstance(modal,FlowTemplateDesigner)
        modal.name.setText('取消修改');modal.reject()
    QtCore.QTimer.singleShot(10,cancel);perform_template_action(w,'document',t)
    assert w.flow.template==t
    w.template_content_panel.apply_template(replace(t,name='应用'))
    w.editor.moveCursor(QtGui.QTextCursor.End);w.editor.insertPlainText('0');ready(w)
    w.source_history('undo');ready(w);assert w.flow.template.name=='应用' and w.source_session.source==before[0]
    w.source_history('undo');ready(w);assert w.flow.template==t
    w.source_history('redo');ready(w);assert w.flow.template.name=='应用'
    w.source_history('redo');ready(w);assert w.source_session.source.endswith('7890')
    w.source_history('undo');w.source_history('undo');ready(w)
    w.editor.insertPlainText('1');ready(w);assert not w.template_content_panel.template_redo
    s.deleteLater()
elif scenario=='trial':
    from inkstruct.editor.template_trial import TemplateTrialDialog
    d=TemplateTrialDialog(t,w);d.show();wait(lambda:d.snapshot is not None)
    assert d.snapshot.exportable and d.picker.count()==len(d.snapshot.pages)
    assert '当前文档真实试排' in d.summary.text()
    assert before==(w.source_session.source,w.source_session.atom_ids,w.resolver.selection_records(),w.flow,w.style,w.page)
    d.reject();d.deleteLater()
    cancelled=TemplateTrialDialog(t,w);cancelled.reject();QtCore.QThreadPool.globalInstance().waitForDone();cancelled.deleteLater()
elif scenario=='ordinary_default':
    from inkstruct.global_defaults import GlobalDefaultsStore
    from inkstruct.editor.template_library import TemplateLibrary
    lib=TemplateLibrary(w)
    assert lib.selected()['builtin']
    store=GlobalDefaultsStore()
    ordinary=store.ordinary_template()
    changed=store.save_ordinary(ordinary,replace(ordinary,width_mm=205,margins_mm=(10,15,20,25)))
    lib.refresh();assert lib.template==changed
    assert GlobalDefaultsStore().for_new_document()[0].flow.template==changed
    assert w.flow==before[3] and w.style==before[4]
    lib.deleteLater()
elif scenario=='catalog_save':
    from inkstruct.document.template_authoring import template_json
    native_store=QtCore.QSettings(QtCore.QSettings.NativeFormat,QtCore.QSettings.UserScope,'InkStruct','TemplateCatalog')
    native_before=native_store.value('recent_paths',None)
    path=root/'template.json';path.write_text(template_json(t),encoding='utf-8');original=path.read_bytes();remember_template(path)
    assert native_store.value('recent_paths',None)==native_before
    from inkstruct.editor.template_manager import catalog_settings
    assert catalog_settings().format()==QtCore.QSettings.IniFormat
    assert root.as_posix() in catalog_settings().fileName().replace(chr(92),'/')
    picker=TemplatePicker(None);picker.list.setCurrentRow(2);assert picker.template==t;picker.reject();assert w.flow==before[3]
    from inkstruct.document.template_authoring import new_template
    legacy=TemplatePicker(new_template());assert legacy.template.schema_version=='inkstruct_page_template_v1';legacy.reject();legacy.deleteLater()
    d=FlowTemplateDesigner(t,editor=w,document_mode=False)
    old=QtWidgets.QFileDialog.getSaveFileName
    QtWidgets.QFileDialog.getSaveFileName=lambda *a,**kw:(str(path),'')
    assert not d.save() and path.read_bytes()==original
    newer=root/'new-template.json';QtWidgets.QFileDialog.getSaveFileName=lambda *a,**kw:(str(newer),'')
    d.name.setText('新副本');d.accept();assert d.result()==QtWidgets.QDialog.Accepted,d.error.text()
    assert path.read_bytes()==original and newer.exists() and w.flow==before[3]
    QtWidgets.QFileDialog.getSaveFileName=old
    picker.deleteLater();d.deleteLater()
else:raise AssertionError(scenario)
w.timer.stop()
if w.cancelled:w.cancelled.set()
w.pool.waitForDone();QtCore.QThreadPool.globalInstance().waitForDone();w.dirty=False;w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
@pytest.mark.parametrize(
    "scenario",
    ["workbench", "form", "scopes_history", "trial", "ordinary_default", "catalog_save"],
)
def test_template_gui_transactions(tmp_path, dpi, scenario):
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path), scenario],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
