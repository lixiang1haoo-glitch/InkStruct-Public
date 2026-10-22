"""Table defaults, overrides and legacy import in the actual Qt editor."""

import importlib.util
import os
import subprocess
import sys

import pytest
from test_table_import import legacy_project


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_table_settings_and_legacy_import(tmp_path):
    legacy, _ = legacy_project(tmp_path)
    original = legacy.read_bytes()
    program = r"""
import sys, time
from dataclasses import replace
from pathlib import Path
from PySide6 import QtWidgets, QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor.table_settings import TableSettingsDialog
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.document.package import load_package

app = QtWidgets.QApplication([])
root = Path(sys.argv[1])
flow = FlowStyle(table=TableStyle(digit_height_mm=3.81234567))
d = TableSettingsDialog(flow, "table1", 2)
assert d.configuration() == ("table1", flow.table)  # Display precision does not round saved values.
d.controls["width_mm"].setValue(140)
d.mode.setCurrentIndex(d.mode.findData("fixed")); d.sizes.setText("80, 60")
d.alignments.setText("左，小数点")
target, style = d.configuration()
assert target == "table1" and style.columns == (80, 60)
assert style.column_alignments == ("left", "decimal")
d.sizes.setText("80"); d.accept()
assert d.result() != QtWidgets.QDialog.DialogCode.Accepted and "2" in d.error.text()
d.inherit.setChecked(True); assert d.configuration() == ("table1", None)
d.scope.setCurrentIndex(0); assert d.configuration() == (None, flow.table)
d.controls["width_mm"].setValue(130); d.reject()
assert flow.table.width_mm == 160

w = MixedWindow(source="缺字\n\n|1|2|\n|---|---|\n|001.20|0.005|\n\n缺字")
errors = []; w.message_error = lambda e: errors.append(str(e))
w.show()
def ready():
    end = time.monotonic() + 10
    while time.monotonic() < end:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())
ready()
assert not w.snapshot.exportable
assert not hasattr(w, 'table_export') and not hasattr(w, 'table_numbers_only')
assert not hasattr(w, 'export_table')
assert not any('单表' in b.text() or '导出此表' in b.text() for b in w.findChildren(QtWidgets.QAbstractButton))
table = next(n for n in w.markdown_document.nodes if n.kind == "table")
w.navigate_span(table.span)
assert w.current_table() == table
w.apply_table_settings(table.node_id, replace(w.flow.table, width_mm=140))
ready()
assert w.flow.table.width_mm == 160 and w.flow.table_for(table.node_id).width_mm == 140
w.apply_table_settings(None, replace(w.flow.table, width_mm=150)); ready()
assert w.flow.table_for(table.node_id).width_mm == 140
w.apply_table_settings(table.node_id, None); ready()
assert w.flow.table_for(table.node_id).width_mm == 150
assert not w.snapshot.exportable  # Styling does not hide full-document errors.

w.load_project_path(root / "old.inktable"); ready()
assert w.session_path is None and w.session_hash is None and w.dirty
assert w.snapshot.exportable and w.flow.table.numeric_spacing == "legacy-ink"
before = [(f.occurrence_id, f.asset_id) for f in w.snapshot.fragments]
QtWidgets.QFileDialog.getSaveFileName = lambda *a, **k: (str(root / "imported.inkdoc"), "")
assert w.save_project()
w.load_project_path(root / "imported.inkdoc"); ready()
assert before == [(f.occurrence_id, f.asset_id) for f in w.snapshot.fragments]
assert w.flow == load_package(root / "imported.inkdoc").flow
assert not errors, errors
w.dirty = False; w.close()
print("Table UI acceptance passed")
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-12000:]
    assert legacy.read_bytes() == original
