"""Object and scope summaries follow real selection and reject stale previews."""
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dpi", ["1", "1.5"])
def test_inspector_context_tracks_selection_scope_and_stale_results(tmp_path, dpi):
    program = r'''
from pathlib import Path
import os, sys, time
from PySide6 import QtCore, QtTest, QtWidgets

root = Path(sys.argv[1])
os.environ['INKSTRUCT_LAYOUT_PREVIEW_HOME'] = str(root / 'private')
sys.path.insert(0, str(Path.cwd() / 'packaging'))
from inkstruct_layout_launcher import configure_preview
configure_preview()
os.environ.pop('INKSTRUCT_LAYOUT_PREVIEW', None)
from inkstruct.editor.mixed import MixedWindow
from inkstruct.fonts.importer import build_font
from inkstruct.document.package import save_package
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_font_packages import recorded

app = QtWidgets.QApplication([])
path = root / 'font.inkfont'
build_font(path, writer='fixture', name='fixture',
           symbols=recorded(root, styles=('upright', 'upright', 'italic')))
source = 'AA\n\n|A|\n|---|\n|A|\n\n![first](missing.png)\n\n![second](missing2.png)'
w = MixedWindow(source=source, run=str(path))
w.resize(1360, 900)
w.show()

def ready():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        app.processEvents()
        if w.snapshot and w.canvas.isEnabled() and not w.worker and not w.timer.isActive():
            w.recovery_timer.stop()
            return
        QtTest.QTest.qWait(10)
    raise AssertionError(w.status.text())

ready()
inspector = w.element_inspector
glyph = w.glyph_inspector
assert inspector.context.objectName() == glyph.selection.objectName() == 'inspector_context'
assert glyph.impact.objectName() == 'inspector_scope'
assert inspector.apply_button.property('inkRole') == glyph.apply_button.property('inkRole') == 'primary'
nodes = [n for root_node in w.markdown_document.nodes for n in root_node.walk()]
table = next(n for n in nodes if n.kind == 'table')
images = [n for n in nodes if n.kind == 'image']
before = (w.flow, w.source_session.identity_record(), w.resolver.selection_records(), w.snapshot)

inspector.selector.setCurrentIndex(inspector.selector.findData(table.node_id))
assert inspector.context.text() == '表格 1 · 沿用本文默认'
page = inspector.pages['table']
assert page.status.isHidden()
page.custom.setChecked(True)
assert inspector.context.text() == '表格 1 · 本文独立设置'
page.editors[table.node_id].controls['width_mm'].setValue(123)
inspector.selector.setCurrentIndex(inspector.selector.findData(images[1].node_id))
assert inspector.context.text() == '图片 2 · 沿用本文默认'
inspector.pages['image'].custom.setChecked(True)
assert inspector.context.text() == '图片 2 · 本文独立设置'
assert (w.flow, w.source_session.identity_record(), w.resolver.selection_records(), w.snapshot) == before
assert any(d.code == 'image-resource-missing' for d in w.snapshot.diagnostics)

selected = next(f for f in w.snapshot.fragments if f.text == 'A' and f.asset_id)
w.select_fragment(selected)
assert '「A」 U+0041' in glyph.selection.text() and '样本 ' in glyph.selection.text()
assert glyph.glyph.sample_id[:12] in glyph.selection.text()
assert glyph.impact.text() == '仅此处 · 本文 1 处'
glyph.scope.setCurrentIndex(glyph.scope.findData('sample'))
assert glyph.impact.text().startswith('本文同一样本 · ')
glyph.scope.setCurrentIndex(glyph.scope.findData('character'))
assert glyph.impact.text().startswith('本文同一字符 · 2 份样本／')
glyph.write_font.setChecked(True)
assert '同时另存校正字体' in glyph.impact.text()
assert w.resolver.selection_records() == before[2]

# An edit invalidates only the view, retaining pending element drafts for refresh.
w.editor.moveCursor(w.editor.textCursor().MoveOperation.End)
w.editor.insertPlainText('\nA')
w.timer.stop()
assert not w.canvas.isEnabled()
assert '正在更新' in inspector.context.text() and '图片 2' not in inspector.context.text()
assert not inspector.selector.isEnabled() and not inspector.stack.isEnabled()
assert not inspector.apply_button.isEnabled()
assert '正在更新' in glyph.selection.text() and not glyph.impact.text()
w.timer.start(0)
ready()
inspector.selector.setCurrentIndex(inspector.selector.findData(table.node_id))
assert inspector.context.text() == '表格 1 · 本文独立设置'
assert inspector.pages['table'].editors[table.node_id].controls['width_mm'].value() == 123
inspector.discard()
assert inspector.context.text() == '表格 1 · 沿用本文默认'
assert not w.flow.table_overrides and not w.flow.image_overrides

# Opening a project creates a new session and must clear the old glyph identity.
saved = root / 'same.inkdoc'
save_package(saved, w.source_session, w.resolver, w.page, w.style, flow=w.flow)
w.dirty = False
w.load_project_path(saved)
ready()
assert glyph.fragment is None and glyph.glyph is None
assert glyph.selection.text() == '在排版预览中点击一个有字形的字符。'
assert not glyph.impact.text() and not glyph.apply_button.isEnabled()
w.dirty = False
w.close()
QtCore.QThreadPool.globalInstance().waitForDone()
'''
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
        capture_output=True, text=True, encoding="utf-8", timeout=80, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
