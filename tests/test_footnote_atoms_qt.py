"""Nested table/figure source selection, local table settings and project replay."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_nested_note_table_and_image_in_actual_editor(tmp_path):
    program = r"""
import sys,time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.document.images import ImageStyle
from inkstruct.document.line_svg import LineSvgResource
app=QtWidgets.QApplication([])
root=Path(sys.argv[1]);svg=root/'plot.svg'
svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm" viewBox="0 0 40 20"><path fill="none" stroke="black" d="M3 3 L37 17"/></svg>')
source='1[^a]\n\n[^a]: 2\n\n    |3|4|\n    |---|---|\n'+'    |5|6|\n'*20+'\n    ![7](plot.svg)\n\n    ---'
w=MixedWindow(source=source)
w.page=PageProfile(95,85,5)
w.flow=FlowStyle(table=TableStyle(width_mm=50),images=(LineSvgResource.from_file(svg,'plot.svg'),),image=ImageStyle(width_mm=30))
w.show();w.schedule_layout()
def ready():
 end=time.monotonic()+15
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();assert w.snapshot.plotter_exportable,w.snapshot.diagnostics
atoms=w.source_session.atom_ids;choices=w.resolver.selection_records()
table=next(n for root_node in w.markdown_document.nodes for n in root_node.walk() if n.kind=='table')
header=next(f for f in w.snapshot.fragments if f.text=='3' and f.repeated)
w.select_fragment(header);app.processEvents()
assert w.editor.textCursor().selectedText()=='3'
assert w.current_table().node_id==table.node_id
w.apply_table_settings(table.node_id,replace(w.flow.table,width_mm=60));ready()
assert w.flow.table.width_mm==50 and w.flow.table_for(table.node_id).width_mm==60
assert w.snapshot.plotter_exportable
figure=next(f for f in w.snapshot.fragments if f.status=='image-vector')
w.select_fragment(figure);app.processEvents()
assert 'plot.svg' in w.editor.textCursor().selectedText()
assert w.source_session.source==source and w.source_session.atom_ids==atoms
assert w.resolver.selection_records()==choices
before=w.snapshot.pages
path=root/'atomic-footnotes.inkdoc'
QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'')
assert w.save_project()
w.load_project_path(path);ready()
assert w.snapshot.pages==before
w.dirty=False;w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
