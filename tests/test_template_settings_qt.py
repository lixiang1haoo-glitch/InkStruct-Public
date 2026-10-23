"""Exercise actual template editor transaction and portable project loading."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_template_settings_editor_roundtrip(tmp_path):
    program = r"""
import sys, time, json
from pathlib import Path
from dataclasses import replace
from PySide6 import QtWidgets, QtTest, QtCore
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.template_settings import TemplateSettingsDialog
from inkstruct.document.template import PageTemplate
from inkstruct.document.package import save_package, load_package
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(Path(sys.argv[1])/'settings'))
t = PageTemplate(**json.loads(Path('configs/templates/hust-physics-scan-v1.json').read_text(encoding='utf-8')))
t = replace(t, offset_x_mm=.123456789)
d = TemplateSettingsDialog(t)
import shiboken6
assert all(not shiboken6.ownedByPython(b) for b in d.findChildren(QtWidgets.QPushButton))
assert d.configuration() == t
d.controls['offset_x_mm'].setValue(1000)
d.accept()
assert d.result() != QtWidgets.QDialog.Accepted and d.error.text()
d.reject()
assert t.offset_x_mm == .123456789
w = MixedWindow(source='1\n\n2\n\n3')
w.show()
def ready():
    end=time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
def accept(dialog):
    dialog.set_template(t)
    dialog.mode.setCurrentIndex(dialog.mode.findData('blank'))
    return QtWidgets.QDialog.Accepted
TemplateSettingsDialog.exec = accept
w.template_settings(); ready()
assert w.snapshot.exportable
assert w.flow.template.mode == 'blank'
assert w.snapshot.page_profile == t.page
assert w.snapshot.pages[0].paint_ops[0].execution_domain == 'template-frame'
# Bind through the same controls used by a human, then check current preview.
def bind(dialog):
    e = dialog.binding_editor
    e.region.setCurrentIndex(e.region.findData('printed-header'))
    assert not e.apply_button.isEnabled()
    e.apply_binding()
    assert '请选择' in e.error.text() or '请先选择' in e.error.text()
    assert not e.bindings
    dialog.show(); app.processEvents()
    # Use a real list hit instead of injecting selectedItems; the button follows selection.
    QtTest.QTest.mouseClick(e.nodes.viewport(), QtCore.Qt.LeftButton,
        pos=e.nodes.visualItemRect(e.nodes.item(0)).center())
    assert e.apply_button.isEnabled()
    e.scale.setValue(.65)
    e.policy.setCurrentIndex(e.policy.findData('all'))
    e.apply_binding()
    assert e.error.text() and not e.bindings  # Continuation has no matching region.
    e.policy.setCurrentIndex(e.policy.findData('first'))
    e.apply_button.click()
    assert not e.error.text() and len(e.bindings) == 1
    previous = e.bindings
    e.nodes.clearSelection()
    assert not e.apply_button.isEnabled()
    e.apply_binding()
    assert e.bindings == previous and '请先选择' in e.error.text()
    e.nodes.item(0).setSelected(True)
    from inkstruct.document.template_authoring import new_template
    e.set_template(new_template())
    assert not e.apply_button.isEnabled()  # Body-only templates have no fixed field.
    e.apply_binding()
    assert '填写区' in e.error.text() and e.bindings == previous
    e.set_template(t)
    assert e.apply_button.isEnabled()
    dialog.hide()
    return QtWidgets.QDialog.Accepted
TemplateSettingsDialog.exec = bind
w.template_settings(); ready()
assert w.snapshot.exportable
assert len(w.flow.template_bindings) == 1
field_fragment = next(f for f in w.snapshot.fragments if f.container_id == 'template-field:printed-header')
w.select_fragment(field_fragment)
assert w.editor.textCursor().selectedText() == field_fragment.text
# Preserve full precision when viewing an existing binding without changing it.
precise = replace(w.flow.template_bindings[0], scale=.7123456789)
from inkstruct.document.markdown import parse_markdown
d = TemplateSettingsDialog(t, document=parse_markdown(w.source_session), bindings=(precise,))
assert d.binding_configuration() == (precise,)
d.binding_editor.apply_binding()
assert d.binding_configuration() == (precise,)
d.binding_editor.remove_button.click()
assert not d.binding_configuration()
d.reject()
assert w.flow.template_bindings

p = Path(sys.argv[1])/'template.inkdoc'
save_package(p, w.source_session, w.resolver, w.page, w.style, flow=w.flow)
loaded=load_package(p)
assert loaded.flow == w.flow
before=w.flow
TemplateSettingsDialog.exec = lambda dialog: QtWidgets.QDialog.Rejected
w.template_settings()
assert w.flow == before
w.dirty=False
w.close()
# The real desktop returns through QApplication.exec(), which drains deferred
# widget deletion. Mirror that lifecycle before Python interpreter teardown.
d.deleteLater()
QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
