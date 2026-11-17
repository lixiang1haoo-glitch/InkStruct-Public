"""Overflow remains editable and source-locatable while normal export is blocked."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_oversize_group_navigation_and_draft_save(tmp_path):
    code = r"""
import sys,time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.table_style import TableStyle
app=QtWidgets.QApplication([])
source='<table><tr><th>8</th><th>9</th></tr><tr><td rowspan="2">1</td><td>2</td></tr><tr><td rowspan="2">3</td></tr><tr><td rowspan="2">4</td></tr><tr><td>5</td></tr><tr><td>6</td><td>7</td></tr></table>'
w=MixedWindow(source=source)
w.flow=replace(w.flow,template=None,template_bindings=(),table=TableStyle(width_mm=60,min_row_height_mm=80))
w.show();w.schedule_layout()
def ready():
 end=time.monotonic()+15
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  time.sleep(.01)
 raise AssertionError(w.status.text())
ready()
assert not w.snapshot.exportable and w.export_button.isEnabled()
i=next(i for i in range(w.diagnostic_picker.count()) if w.diagnostic_picker.itemText(i).startswith('table-group-height-overflow'))
w.diagnostic_picker.setCurrentIndex(i);w.navigate_diagnostic();app.processEvents()
selected=w.editor.textCursor().selectedText()
assert selected.startswith('<td rowspan="2">1') and selected.endswith('<td>5</td>')
assert '<td>6</td>' not in selected
path=Path(sys.argv[1])/'overflow-draft.inkdoc'
QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'')
assert w.save_project()
w.load_project_path(path);ready()
assert w.source_session.source==source and not w.snapshot.exportable and w.export_button.isEnabled()
w.dirty=False;w.close()
"""
    p = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert p.returncode == 0, (p.stdout + p.stderr)[-12000:]
