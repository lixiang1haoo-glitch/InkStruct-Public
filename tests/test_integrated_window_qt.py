"""Integrated pages must not impose their native form size on the whole window."""
import os
import subprocess
import sys


def test_large_native_form_hints_scroll_instead_of_growing_window(tmp_path):
    program = r'''
import sys
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from inkstruct.application import InkStructWindow
app=QtWidgets.QApplication([])
app.setFont(QtGui.QFont('Arial',13))
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,sys.argv[1])
w=InkStructWindow(workspace=Path(sys.argv[1])/'workspace')
w.show();app.processEvents()
for index in range(3):
    page=w.tabs.widget(index)
    assert isinstance(page,QtWidgets.QScrollArea)
    # Emulate a form larger than the available screen.
    page.widget().setMinimumHeight(1800)
    w.tabs.setCurrentIndex(index);app.processEvents()
    assert w.height()<=app.primaryScreen().availableGeometry().height()
    assert page.verticalScrollBar().maximum()>0
w.tabs.setCurrentIndex(3)
w.editor.timer.stop()
if w.editor.cancelled:w.editor.cancelled.set()
QtCore.QThreadPool.globalInstance().waitForDone()
w.editor.dirty=False;w.close()
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


def test_former_native_capture_window_does_not_keep_stale_mouse_coordinates(tmp_path):
    program = r'''
import sys
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets, QtTest
from inkstruct import collector
from inkstruct.application import InkStructWindow
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,sys.argv[1])
retired=[]
class SurfaceWatch(QtCore.QObject):
    def eventFilter(self, watched, event):
        if event.type()==QtCore.QEvent.Type.PlatformSurface and event.surfaceEventType()==QtGui.QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed:
            retired.append(True)
        return False
watch=SurfaceWatch()
original=collector.main
def with_native_window(*args, **kwargs):
    window=original(*args, **kwargs)
    # Reproduce the native handle created by the standalone collector on macOS.
    window.move(690,280)
    window.winId()
    window.setAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow,False)
    assert window.windowHandle() is not None
    window.windowHandle().installEventFilter(watch)
    return window
collector.main=with_native_window
w=InkStructWindow(workspace=Path(sys.argv[1])/'workspace')
assert retired, 'Standalone native surface must retire when the collector becomes a page'
w.show();w.tabs.setCurrentIndex(0);app.processEvents()
assert w.collector.tabs.count()==2
assert [w.collector.tabs.tabText(i) for i in range(2)] == ['汉字样本', '标点与扩展']
assert all(w.collector.tabs.tabText(i)!='整行采集' for i in range(w.collector.tabs.count()))
for index in range(w.collector.tabs.count()):
    w.collector.tabs.setCurrentIndex(index);app.processEvents()
    page=w.collector.tabs.widget(index)
    field=page.writer_picker
    center=field.rect().center()
    assert field.mapToGlobal(center)==w.mapToGlobal(field.mapTo(w,center))
    assert app.widgetAt(field.mapToGlobal(center)) is field
    QtTest.QTest.mouseClick(field,QtCore.Qt.MouseButton.LeftButton,pos=center)
    assert field.view().isVisible()
    QtTest.QTest.keyClick(field.view().window(),QtCore.Qt.Key_Escape)
    assert not field.view().isVisible()
    assert not field.text() and not page.writer_edit.isVisible()
w.editor.timer.stop()
if w.editor.cancelled:w.editor.cancelled.set()
QtCore.QThreadPool.globalInstance().waitForDone()
w.editor.dirty=False;w.close()
'''
    result = subprocess.run(
        [sys.executable, '-c', program, str(tmp_path)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
