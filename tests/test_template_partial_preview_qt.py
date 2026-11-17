"""Paste a blocked template document, locate the object, then repair and undo."""

import os
import subprocess
import sys


def test_paste_keeps_preview_and_diagnostic_navigation(tmp_path):
    program = r'''
import sys,time
sys.path.insert(0,'tests')
from pathlib import Path
from PySide6 import QtCore,QtWidgets
from test_flow_templates import frame,template
from inkstruct.document.flow_template import PageLayout
from inkstruct.document.styles import FlowStyle
from inkstruct.editor.mixed import MixedWindow
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,sys.argv[1])
app=QtWidgets.QApplication([])
w=MixedWindow(source='1');w.show()
def ready():
 end=time.monotonic()+20
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():
   w.recovery_timer.stop();return
  time.sleep(.01)
 raise AssertionError(w.status.text())
ready()
t=template(layouts=(PageLayout('p1','p1',(frame(w=40,h=50),)),))
w.flow=FlowStyle(template=t)
source='123\n\n```\n'+'2'*100+'\n```\n\n456'
w.editor.setPlainText(source);ready()
assert ''.join(f.text for f in w.snapshot.fragments)=='123'
assert '后续正文尚未排版' in w.status.text()
assert not w.snapshot.exportable and w.export_button.isEnabled()
error=next(d for d in w.snapshot.diagnostics if d.code=='template-body-no-progress')
index=next(i for i in range(w.diagnostic_picker.count()) if getattr(w.diagnostic_picker.itemData(i),'code',None)==error.code)
w.diagnostic_picker.setCurrentIndex(index);w.navigate_diagnostic()
assert w.editor.textCursor().selectedText().replace('\u2029','\n')==source[error.span.start:error.span.end]
cursor=w.editor.textCursor();cursor.insertText('2\n\n');ready()
assert w.snapshot.exportable and w.export_button.isEnabled()
assert ''.join(f.text for f in w.snapshot.fragments)=='1232456'
w.editor.undo();ready()
assert ''.join(f.text for f in w.snapshot.fragments)=='123'
assert not w.snapshot.exportable
w.dirty=False;w.close()
'''
    result = subprocess.run([sys.executable,'-c',program,str(tmp_path)],
                            env={**os.environ,'QT_QPA_PLATFORM':'offscreen','PYTHONIOENCODING':'utf-8'},
                            capture_output=True,text=True,encoding='utf-8',timeout=45,check=False)
    assert result.returncode == 0, result.stdout+result.stderr
