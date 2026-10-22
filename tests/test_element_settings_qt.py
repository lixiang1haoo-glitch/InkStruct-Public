"""Default/element inheritance survives real editor layout and portable reopen."""
import os
import subprocess
import sys


def test_table_and_image_scopes_persist_and_restore(tmp_path):
    program = r'''
import sys, time
from pathlib import Path
from PySide6 import QtCore, QtTest, QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.table_settings import TableSettingsDialog
from inkstruct.editor.image_settings import ImageSettingsDialog
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.styles import FlowStyle
from inkstruct.document.package import save_package, load_package
app = QtWidgets.QApplication([])
root = Path(sys.argv[1])
w = MixedWindow(source='|1|2|\n|---|---|\n|3|4|\n\n1\n\n|5|6|7|\n|---|---|---|\n|8|9|0|\n\n![1](a.png)\n\n![2](b.png)')
w.show()
def ready():
    end = time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            w.recovery_timer.stop()
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
doc = w.parse_current_source()
tables = [n for r in doc.nodes for n in r.walk() if n.kind=='table']
images = [n for r in doc.nodes for n in r.walk() if n.kind=='image']
# Both scopes are available without first placing the source cursor in a table.
def table_dialog(d):
    assert d.scope.count()==3
    d.scope.setCurrentIndex(2)
    assert d.columns==3
    d.controls['width_mm'].setValue(120)
    return QtWidgets.QDialog.Accepted
TableSettingsDialog.exec = table_dialog
w.table_settings(); ready()
assert w.flow.table_for(tables[1].node_id).width_mm==120
assert w.flow.table_for(tables[0].node_id).width_mm==160
def defaults(d):
    d.scope.setCurrentIndex(0)
    d.controls['width_mm'].setValue(140)
    return QtWidgets.QDialog.Accepted
TableSettingsDialog.exec = defaults
w.table_settings(); ready()
assert w.flow.table.width_mm==140
assert w.flow.table_for(tables[1].node_id).width_mm==120
assert w.flow.table_for(tables[0].node_id).width_mm==140
# Editing defaults works even before the source contains images.
empty = ImageSettingsDialog(parse_markdown('1'), FlowStyle())
assert empty.controls['width_mm'].isHidden() and not empty.import_button.isEnabled()
empty.controls['height_mm'].setValue(65)
assert empty.configuration().image.height_mm==65
empty.reject()
# No-op on an inherited image must not freeze a new independent override.
d = ImageSettingsDialog(doc, w.flow)
assert d.picker.currentData() is None and d.picker.count()==3
d.picker.setCurrentIndex(1)
assert d.configuration()==w.flow
d.dimension_mode.setCurrentIndex(d.dimension_mode.findData('width'))
d.controls['width_mm'].setValue(45)
d.picker.setCurrentIndex(0)  # Stage the element change before editing defaults.
d.controls['height_mm'].setValue(70)
w.flow = d.configuration()
assert w.flow.image.height_mm==70
assert w.flow.image_for(images[0].node_id).width_mm==45
assert w.flow.image_for(images[1].node_id).height_mm==70
assert images[1].node_id not in dict(w.flow.image_overrides)
d.reject()
before = w.flow
def cancel(d):
    d.controls['height_mm'].setValue(99)
    d.picker.setCurrentIndex(2)
    d.controls['width_mm'].setValue(25)
    return QtWidgets.QDialog.Rejected
ImageSettingsDialog.exec = cancel
w.image_settings()
assert w.flow==before
path = root/'scopes.inkdoc'
save_package(path,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
assert load_package(path).flow==w.flow
w.load_project_path(path); ready()
assert w.flow==before
assert [n.node_id for r in w.markdown_document.nodes for n in r.walk() if n.kind=='image']==[n.node_id for n in images]
# Restore the selected elements, save and reopen again.
def restore_table(d):
    d.scope.setCurrentIndex(2)
    d.inherit.setChecked(True)
    return QtWidgets.QDialog.Accepted
TableSettingsDialog.exec = restore_table
w.table_settings(); ready()
def restore_image(d):
    d.picker.setCurrentIndex(1)
    d.inherit.setChecked(True)
    return QtWidgets.QDialog.Accepted
ImageSettingsDialog.exec = restore_image
w.image_settings(); ready()
assert not w.flow.table_overrides and not w.flow.image_overrides
assert w.flow.table_for(tables[1].node_id).width_mm==140
assert w.flow.image_for(images[0].node_id).height_mm==70
save_package(root/'restored.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow)
assert load_package(root/'restored.inkdoc').flow==w.flow
# Defaults also apply to elements added later.
w.editor.appendPlainText('\n![3](c.png)\n\n|1|\n|---|\n|2|'); ready()
for r in w.markdown_document.nodes:
    for n in r.walk():
        if n.kind=='image': assert w.flow.image_for(n.node_id).height_mm==70
        if n.kind=='table': assert w.flow.table_for(n.node_id).width_mm==140
w.dirty=False; w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'},
                            capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
