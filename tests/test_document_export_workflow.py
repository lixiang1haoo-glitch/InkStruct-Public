import json
import re
import time
from dataclasses import asdict, replace
from xml.etree import ElementTree

import pytest
from PIL import Image

from inkstruct.document.schema import Diagnostic, PageProfile, SourceSpan
from inkstruct.document.template_authoring import pack_reference_image
from inkstruct.editor.export_check import check_export
from inkstruct.plotter.export import export_plan
from inkstruct.plotter.options import ExportOptions
from inkstruct.plotter.parallel import ExportControl
from inkstruct.renderers.visual_export import export_visual
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp, RasterOp


@pytest.fixture
def snapshot():
    def color(rgb):
        return pack_reference_image(Image.new('RGB', (24, 16), rgb))

    paper = PageProfile(110.37, 154.28, 10)
    red, blue, green = (color(rgb) for rgb in ((220, 40, 40), (20, 40, 200), (40, 220, 40)))
    figure = RasterOp('image', 'image', SourceSpan(4, 12), 'image.png', green.sha256,
                      green.png_base64, (20, 40, 80, 90))
    # The black line intersects the green image; the table rule does not.
    ink = PaintOp('caption', ((25, 55), (70, 55)), 4)
    rule = PaintOp('table', ((12, 105), (95, 105)), 2)
    return LayoutSnapshot('snap', 'job', 'doc', 1, paper, (
        Page(0, (), (), background=red),
        Page(1, (), (ink, rule), background=blue, images=(figure,)),
        Page(2, (), (rule,)),
    ), (), 'resources', 'markdown-test')


def test_writer_checks_scope_omissions_and_partial(tmp_path, snapshot):
    box = snapshot.pages[1].images[0]
    bad = PaintOp('too-far', ((107, 100), (114, 100)), 0.2)
    damaged = replace(snapshot, pages=(snapshot.pages[0], replace(snapshot.pages[1],
                      paint_ops=(*snapshot.pages[1].paint_ops, bad)), snapshot.pages[2]),
                      diagnostics=(Diagnostic('ink-overflow', '越界示例', box.span),))
    assert check_export(snapshot, None, None, ExportOptions((0,), registration=True),
                        machine=True).errors == ('所选页没有可写笔迹',)
    selection = check_export(damaged, None, None, ExportOptions((0, 2)), machine=True)
    assert not selection.errors and not selection.images and selection.machine.pages == (2,)
    assert selection.machine.scope['skipped_empty_pages'] == [1]
    normal = check_export(snapshot, None, None, ExportOptions((1,)), machine=True)
    assert not normal.errors and normal.images[0]['page_number'] == 2
    assert [s.occurrence_id for s in normal.machine.plan.pages[1].strokes] == ['caption', 'table']
    checked = check_export(damaged, None, None, ExportOptions((1,)), machine=True)
    assert checked.errors == ('越界示例',) and checked.machine is None
    export_plan(checked.partial.plan, tmp_path / 'partial', export_scope=checked.partial.scope,
                page_indices=checked.partial.pages)
    names = {p.name for p in (tmp_path / 'partial').iterdir()}
    assert names == {'page-002.svg', 'issues.json', 'issues.txt', 'plotter.json'}
    svg = (tmp_path / 'partial/page-002.svg').read_text('utf-8')
    assert {n.tag.split('}')[-1] for n in ElementTree.fromstring(svg)} == {'path'}
    routing = json.loads((tmp_path / 'partial/plotter.json').read_text('utf-8'))
    assert [r['occurrence_id'] for r in routing['pages'][0]['strokes']] == ['caption', 'table']
    issues = json.loads((tmp_path / 'partial/issues.json').read_text('utf-8'))
    assert issues['omitted_strokes'][0]['reason'] == 'stroke-outside-physical-page'


def test_visual_outputs_keep_layers_dimensions_and_order(tmp_path, snapshot):
    from PySide6 import QtWidgets
    from inkstruct.editor.template_pdf import QtPdfDocument

    pytest.importorskip('PySide6.QtPdf')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    png, svg, pdf = (tmp_path / name for name in ('whole.png', 'whole.svg', 'whole.pdf'))
    for path, pages, format in ((png, (0,), 'png'), (svg, (1,), 'svg'), (pdf, (0, 1, 2), 'pdf')):
        export_visual(snapshot, path, pages, format, control=ExportControl(), progress=lambda *_: None)
    with Image.open(png) as image:
        assert image.getpixel((10, 10)) == (220, 40, 40)
    elements = [n.tag.split('}')[-1] for n in ElementTree.parse(svg).getroot()]
    assert elements == ['rect', 'image', 'image', 'polyline', 'polyline']
    export_visual(snapshot, tmp_path / 'pages', (0, 2), 'png', control=ExportControl(), progress=lambda *_: None)
    assert sorted(p.name for p in (tmp_path / 'pages').iterdir()) == ['page-001.png', 'page-003.png']
    raw = pdf.read_bytes()
    sizes = re.findall(rb'/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]', raw)
    assert len(sizes) == 3
    for width, height in sizes:
        assert (float(width) * 25.4 / 72, float(height) * 25.4 / 72) == pytest.approx((110.37, 154.28))
    # Three raster XObjects represent the two backgrounds and embedded image.
    assert len(re.findall(rb'/Subtype /Image\b', raw)) == 3
    rendered = QtPdfDocument(raw)
    try:
        assert rendered.page_count == 3
        assert rendered.render(0, 110, 154).getpixel((10, 10))[:3] == (220, 40, 40)
        second = rendered.render(1, 110, 154)
        assert second.getpixel((10, 10))[:3] == (20, 40, 200)
        assert second.getpixel((40, 70))[:3] == (40, 220, 40)
        assert max(second.getpixel((40, 55))[:3]) < 45
        assert max(second.getpixel((40, 104))[:3]) < 45
        assert rendered.render(2, 110, 154).getpixel((10, 10))[:3] == (255, 255, 255)
    finally:
        rendered.close()
    app.processEvents()


def test_export_dialog_ranges_and_confirmations(snapshot, monkeypatch):
    pytest.importorskip('PySide6')
    from PySide6 import QtWidgets
    from inkstruct.editor.document_export_dialog import DocumentExportDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = DocumentExportDialog(snapshot, None, None, 1, True)
    dialog.show()
    assert dialog.advanced_panel.isVisible() and dialog.advanced_panel.title() == '高级设置'
    assert not dialog.advanced_panel.isCheckable()
    assert all(control.isVisible() for control in (dialog.optimize, dialog.tables,
                                                   dialog.registration, *dialog.scales))
    dialog.range.setCurrentIndex(dialog.range.findData('current'))
    dialog.run_check()
    assert dialog.checked.pages == (1,) and '第 2 页 · image.png' in dialog.report.toPlainText()
    assert not dialog.save.isEnabled()
    dialog.confirm_images.setChecked(True)
    assert dialog.save.isEnabled()
    dialog.purpose.setCurrentIndex(dialog.purpose.findData('page'))
    assert dialog.advanced_panel.isHidden()
    dialog.range.setCurrentIndex(dialog.range.findData('selection'))
    dialog.pages.setText('1,3')
    dialog.run_check()
    assert dialog.checked.pages == (0, 2) and dialog.save.isEnabled() and dialog.format.currentData() == 'png'
    dialog.purpose.setCurrentIndex(dialog.purpose.findData('pdf'))
    assert dialog.advanced_panel.isHidden()
    dialog.run_check()
    assert dialog.checked.pages == (0, 1, 2) and dialog.range.isHidden()
    dialog.accept()
    assert dialog.selection[0] == 'pdf'

    damaged = replace(snapshot, diagnostics=(Diagnostic('asset-missing', '缺字示例', SourceSpan(0, 0)),))
    partial = DocumentExportDialog(damaged, None, None, 1, False)
    partial.show()
    partial.run_check()
    assert not partial.save.isEnabled() and partial.problems.isVisible() and partial.partial.isVisible()
    answers = iter([QtWidgets.QMessageBox.StandardButton.Cancel, QtWidgets.QMessageBox.StandardButton.Yes])
    texts = []
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question', lambda parent, title, text, *_:
                        (texts.append(text), next(answers))[1])
    partial.partial.click()
    assert partial.selection is None
    partial.partial.click()
    assert partial.selection[2].scope['forced'] and all('跳过的位图' in text for text in texts)
    app.processEvents()


def test_editor_preserves_old_reviews_and_character_correction(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    from PySide6 import QtTest, QtWidgets

    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.editing import SourceSession
    from inkstruct.document.package import load_package, save_package
    from inkstruct.document.schema import StyleProfile
    from inkstruct.editor.mixed import MixedWindow
    from inkstruct.editor.review import Review

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    record = Review('a' * 64, '1', 'review', '旧备注', '', 'fixture', 'v1', 'v1', '1', 'hash',
                    0, '2026-01-01T00:00:00+00:00')
    path = tmp_path / 'legacy.inkdoc'
    save_package(path, SourceSession('1'), AssetResolver(builtin_numbers=True),
                 PageProfile(), StyleProfile(), reviews=(asdict(record),))
    window = MixedWindow()
    window.recovery_timer.setInterval(60000)

    def wait_for(predicate):
        deadline = time.monotonic() + 10
        while not predicate():
            QtTest.QTest.qWait(10)
            assert time.monotonic() < deadline, window.status.text()

    errors = []
    monkeypatch.setattr(window, 'message_error', errors.append)
    window.show()
    try:
        window.load_project_path(path)
        wait_for(lambda: window.canvas.isEnabled() and not window.worker)
        assert not window.findChild(QtWidgets.QDockWidget, 'glyph_review_dock')
        assert not window.canvas.show_marks and window.export_button.text() == '导出…'
        assert window.book.records[record.asset_id] == record
        fragment = next(f for f in window.snapshot.fragments if f.asset_id)
        window.select_fragment(fragment)
        assert window.properties_tabs.tabText(window.properties_tabs.currentIndex()) == '字符校正'
        inspector = window.glyph_inspector
        inspector.nudge.step.setValue(5)
        inspector.nudge.buttons[(1, 0)].click()
        inspector.nudge.buttons[(0, -1)].click()
        assert inspector.controls['dx_em'].value() == 5
        assert inspector.controls['dy_em'].value() == -5
        assert not window.flow.glyph_corrections
        inspector.apply()
        wait_for(lambda: window.canvas.isEnabled() and not window.worker)
        assert window.flow.glyph_corrections
        window.request_project_save()
        wait_for(lambda: window.project_save is None and not window.dirty)
        loaded = load_package(path)
        assert loaded.reviews == (asdict(record),)
        assert loaded.flow.glyph_corrections == window.flow.glyph_corrections
        assert not errors
    finally:
        window.dirty = False
        window.close()
        app.processEvents()
