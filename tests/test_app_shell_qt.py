"""Navigation stays outside modules; presentation does not alter document or capture state."""
import os
import subprocess
import sys

import pytest

PROGRAM = r''' 
import sys,time
from pathlib import Path
from PySide6 import QtCore,QtGui,QtWidgets,QtTest
from inkstruct.application import InkStructWindow
from inkstruct.resources_ui import open_management
from inkstruct.assets.resolver import AssetResolver
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,sys.argv[1])
w=InkStructWindow(workspace=Path(sys.argv[1])/'workspace');w.show()
w.editor.resolver=AssetResolver(builtin_numbers=True)
w.editor.editor.setPlainText('123123\n\n456456')
end=time.monotonic()+30
while time.monotonic()<end:
 app.processEvents()
 if w.editor.snapshot and not w.editor.worker and not w.editor.timer.isActive():break
 time.sleep(.01)
else:raise AssertionError('document did not finish')
w.editor.recovery_timer.stop()
snapshot=w.editor.snapshot;choices=w.editor.resolver.selection_records()
identity=w.editor.source_session.identity_record();flow=w.editor.flow
assert choices
assert not w.tabs.tabBar().isVisible() and not w.menuBar().isVisible()
assert list(w.navigation_buttons)==[0,1,3,5,2,4]
for button in w.navigation_buttons.values():assert not button.icon().isNull() and button.accessibleName()
assert w.settings_button.text()=='设置' and not w.settings_button.icon().isNull()
from inkstruct.fonts import APP_VERSION
assert w.windowTitle()=='InkStruct 墨构 · '+APP_VERSION
assert w.findChild(QtWidgets.QFrame,'app_header') is None
assert w.settings_button.parentWidget() is w.shell_sidebar
assert not w.settings_button.isCheckable()
assert any(a.text()=='关于 InkStruct' and a.shortcut().toString()=='F1' for a in w.shell_sidebar.actions())
paste=w.editor.findChild(QtWidgets.QToolButton,'paste_source')
assert paste.text()=='粘贴' and paste.toolButtonStyle()==QtCore.Qt.ToolButtonTextBesideIcon
templates=w.template_library
assert '普通页面' in templates.summary.text() and not templates.layouts.isHidden()
assert templates.use_button.isEnabled()
item=QtWidgets.QListWidgetItem('missing-template')
item.setData(QtCore.Qt.UserRole,{'managed':None,'path':str(Path(sys.argv[1])/'missing.json')})
templates.list.addItem(item);templates.list.setCurrentItem(item);templates.describe()
assert templates.summary.text()=='资源不可读取 · 原记录保留' and templates.template is None
assert not templates.use_button.isEnabled()
templates.list.clear();templates.describe()
# Both compact and normal windows keep navigation/settings outside scrollable module bodies.
for width,height in ((1360,900),(1000,720)):
 w.resize(width,height);app.processEvents()
 settings=w.settings_button.mapTo(w,QtCore.QPoint())
 library=w.navigation_buttons[2]
 assert settings.y()>library.mapTo(w,QtCore.QPoint(0,library.height())).y()
 assert w.tabs.mapTo(w,QtCore.QPoint()).y()==0
 for index,button in w.navigation_buttons.items():
  QtTest.QTest.mouseClick(button,QtCore.Qt.LeftButton);app.processEvents()
  assert w.tabs.currentIndex()==index and button.isChecked()
  assert sum(b.isChecked() for b in w.navigation_buttons.values())==1
  assert w.settings_button.mapTo(w,QtCore.QPoint())==settings
  assert w.rect().contains(button.mapTo(w,button.rect().center()))
  assert w.rect().contains(w.settings_button.mapTo(w,w.settings_button.rect().center()))
 # Programmatic transitions and keyboard navigation must use the same selected state.
 w.tabs.setCurrentIndex(3);w.editor.editor.setFocus();app.processEvents()
 for key,index in ((QtCore.Qt.Key_1,0),(QtCore.Qt.Key_2,1),(QtCore.Qt.Key_3,3),(QtCore.Qt.Key_4,2),(QtCore.Qt.Key_5,4),(QtCore.Qt.Key_6,5)):
  QtTest.QTest.keyClick(w, key, QtCore.Qt.AltModifier);app.processEvents()
  assert w.tabs.currentIndex()==index and w.navigation_buttons[index].isChecked()
def close_about():
 box=app.activeModalWidget();assert isinstance(box,QtWidgets.QMessageBox)
 assert APP_VERSION in box.text();box.accept()
QtCore.QTimer.singleShot(10,close_about)
QtTest.QTest.keyClick(w,QtCore.Qt.Key_F1);app.processEvents()
assert w.editor.snapshot is snapshot
assert w.editor.source_session.identity_record()==identity and w.editor.resolver.selection_records()==choices
assert w.editor.flow==flow
open_management(w.editor,'templates');app.processEvents()
assert w.tabs.currentIndex()==4 and w.navigation_buttons[4].isChecked()
open_management(w.editor,'fonts');app.processEvents()
assert w.tabs.currentIndex()==2 and w.navigation_buttons[2].isChecked()
# Existing generated-result handoff reaches the original publication path and synchronizes nav.
workflow=w.generator.centralWidget();calls=[]
w.library.prepare_publication=lambda *args:calls.append(args)
workflow.last_generated_run=Path(sys.argv[1])/'existing-run';workflow.last_generated_writer='existing-writer'
w.use_generated();app.processEvents()
assert calls==[(workflow.last_generated_run,'existing-writer')]
assert w.tabs.currentIndex()==2 and w.navigation_buttons[2].isChecked()
# A taller inactive capture page must not force blank height on the active page.
w.resize(1360,900);w.tabs.setCurrentIndex(0)
w.collector.tabs.setCurrentIndex(0)
for _ in range(10):app.processEvents()
assert w.collector.single_widget.sizePolicy().verticalPolicy()!=QtWidgets.QSizePolicy.Ignored
assert w.collector.symbol_widget.sizePolicy().verticalPolicy()==QtWidgets.QSizePolicy.Ignored
assert w.tabs.widget(0).verticalScrollBar().maximum()==0
viewport=w.tabs.widget(0).viewport();save=w.collector.single_widget.save_button
assert viewport.rect().contains(save.mapTo(viewport,save.rect().center()))
w.collector.tabs.setCurrentIndex(1)
for _ in range(10):app.processEvents()
assert w.collector.symbol_widget.sizePolicy().verticalPolicy()!=QtWidgets.QSizePolicy.Ignored
assert w.collector.single_widget.sizePolicy().verticalPolicy()==QtWidgets.QSizePolicy.Ignored
# Genuine overflow stays scrollable instead of clipping the active page.
w.tabs.widget(0).ensureWidgetVisible(w.collector.symbol_widget.save_button)
app.processEvents()
assert w.tabs.widget(0).verticalScrollBar().maximum()>0
w.editor.timer.stop();w.editor.recovery_timer.stop()
if w.editor.cancelled:w.editor.cancelled.set()
QtCore.QThreadPool.globalInstance().waitForDone();w.editor.canvas.stop_rendering();w.editor.dirty=False;w.close()
'''


@pytest.mark.parametrize('dpi',['1','1.5','2'])
def test_shell_navigation_preserves_modules_and_frozen_document(tmp_path,dpi):
    result=subprocess.run([sys.executable,'-c',PROGRAM,str(tmp_path)],
        env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_SCALE_FACTOR':dpi},
        capture_output=True,text=True,encoding='utf8',timeout=60,check=False)
    assert result.returncode==0,result.stdout+result.stderr
