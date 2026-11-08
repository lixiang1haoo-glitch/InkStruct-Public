"""Human/agent templates share validation and can drive the existing renderer."""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest
from test_math_layout import resolver

from inkstruct.cli import main
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Anchor, PageTemplate, Region, TemplateBinding, TemplateFace
from inkstruct.document.template_authoring import (
    geometry_preview,
    new_template,
    parse_template,
    read_template,
    template_json,
)
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg


def test_agent_cli_create_validate_preview_and_no_overwrite(tmp_path, capsys):
    source, output = tmp_path / "layout.json", tmp_path / "preview"
    assert main(["document", "template", "new", "--output", str(source)]) == 0
    before = source.read_bytes()
    assert main(["document", "template", "validate", str(source)]) == 0
    assert main(["document", "template", "preview", str(source), "--output", str(output)]) == 0
    report = json.loads((output / "validation.json").read_text(encoding='utf-8'))
    assert report["valid"] and not report["machine_export_ready"]
    assert not report["content_fit_checked"]
    assert source.read_bytes() == before
    for face in ("first", "continuation"):
        ET.fromstring((output / f"{face}.svg").read_text(encoding='utf-8'))
    assert main(["document", "template", "new", "--output", str(source)]) == 2
    assert main(["document", "template", "preview", str(source), "--output", str(output)]) == 2
    assert source.read_bytes() == before


@pytest.mark.parametrize("value", [[], {"schema_version": "unknown"}, {"name": "incomplete"}])
def test_invalid_json_is_not_an_accepted_template(value):
    with pytest.raises((ValueError, TypeError)):
        parse_template(json.dumps(value))


def test_invalid_geometry_never_creates_preview_directory(tmp_path):
    data = json.loads(template_json(new_template()))
    data["continuation"]["body"]["width_mm"] -= 10
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(data))
    output = tmp_path / "preview"
    assert main(["document", "template", "preview", str(source), "--output", str(output)]) == 2
    assert not output.exists()


def test_reference_escaping_and_full_precision_roundtrip():
    template = new_template()
    template = replace(
        template, first=replace(template.first, anchors=(Anchor('<&"', 2.123456789, 5),))
    )
    assert parse_template(template_json(template)) == template
    svg = geometry_preview(template, "first")
    assert "&lt;&amp;&quot;" in svg
    ET.fromstring(svg)


@pytest.mark.parametrize("size", [(210, 297), (100, 140)])
def test_unrelated_templates_bind_and_export_without_source_changes(size, tmp_path):
    width, height = size
    face = TemplateFace(
        Region("body", 10, 40, width - 20, height - 50),
        reserved=(Region("record-key", 10, 10, width - 20, 20),),
    )
    template = PageTemplate("Generic record", width, height, face, face)
    session = SourceSession("123\n\n456\n\n7.89")
    doc = parse_markdown(session)
    r = resolver()
    binding = TemplateBinding("record-key", (doc.nodes[0].node_id,), pages="all")
    flow = FlowStyle(template=template, template_bindings=(binding,))
    snapshot = layout_markdown(doc, r, flow=flow)
    assert snapshot.exportable, snapshot.diagnostics
    assert any(f.container_id == "template-field:record-key" for f in snapshot.fragments)
    assert session.source == "123\n\n456\n\n7.89"
    for page in plan_from_snapshot(snapshot).pages:
        root = ET.fromstring(page_svg(page))
        assert all(e.tag.endswith("path") for e in root)
    path = tmp_path / "generic.inkdoc"
    save_package(path, session, r, snapshot.page_profile, StyleProfile(), flow=flow)
    assert load_package(path).flow.template == template


def test_existing_validation_fixtures_keep_exact_data():
    for path in Path("configs/templates").glob("*.json"):
        if ".measurement." not in path.name:
            template = read_template(path)
            assert parse_template(template_json(template)) == template


def test_designer_transaction_and_pending_values(tmp_path):
    pytest.importorskip("PySide6")
    program = r"""
import sys
from pathlib import Path
from dataclasses import replace
from PySide6 import QtWidgets, QtCore, QtGui
from inkstruct.document.template_authoring import new_template
from inkstruct.editor.template_designer import TemplateDesignerDialog
from inkstruct.editor.template_settings import TemplateSettingsDialog
app = QtWidgets.QApplication([])
# Imported PNG references must render in Qt as well as survive JSON roundtrip.
import base64, io
from hashlib import sha256
from PIL import Image
from inkstruct.document.template import TemplateBackground
png = io.BytesIO()
Image.new('RGB', (2, 2), 'red').save(png, format='PNG')
raw = png.getvalue()
background = TemplateBackground(base64.b64encode(raw).decode(), sha256(raw).hexdigest())
base = new_template()
bg_template = replace(base, first=replace(base.first, background=background))
bg = TemplateDesignerDialog(bg_template)
canvas = QtGui.QImage(210, 297, QtGui.QImage.Format_ARGB32)
canvas.fill(QtCore.Qt.white)
painter = QtGui.QPainter(canvas)
bg.preview.renderer().render(painter)
painter.end()
color = canvas.pixelColor(2, 2)
assert color.red() > color.green() + 50, color.name()
assert bg.configuration() == bg_template
bg.deleteLater()
t = replace(new_template(), offset_x_mm=.123456789)
d = TemplateDesignerDialog(t)
d.show()
app.processEvents()
assert d.configuration() == t
# A partially entered value cannot be accepted or accidentally switched away.
def set_value(table, key, value):
    for row in range(table.rowCount()):
        if table.item(row, 0).data(QtCore.Qt.UserRole) == key:
            table.item(row, 1).setText(value)
            return
    raise AssertionError(key)
d.add_element('reserved')
assert len(d.configuration().first.reserved) == 1
set_value(d.element_properties, 'width_mm', '90.123456789')
assert not d.face.isEnabled() and not d.element.isEnabled()
d.accept()
assert d.result() != QtWidgets.QDialog.Accepted
assert '写入' in d.error.text()
d.apply_element.click()
assert d.configuration().first.reserved[0].width_mm == 90.123456789
assert d.configuration().offset_x_mm == .123456789
# An illegal overlap remains an editable draft; preview is not stale.
set_value(d.element_properties, 'y_mm', '40')
d.apply_element.click()
assert d.valid_template is None and d.preview.isHidden()
d.accept()
assert d.result() != QtWidgets.QDialog.Accepted
d.json_editor.undo()
assert d.configuration().first.reserved[0].y_mm == 10
# Same schema covers arbitrary anchors, rules, and independent continuation.
d.add_element('anchors')
d.add_element('rules')
d.face.setCurrentIndex(1)
assert not d.configuration().continuation.reserved
# First and continuation widths require an intentional coordinated change.
set_value(d.element_properties, 'width_mm', '160')
d.apply_element.click()
assert d.valid_template is None
d.copy_body_width()
assert d.configuration().first.body.width_mm == 160
assert d.configuration().continuation.body.width_mm == 160
d.face.setCurrentIndex(0)
app.processEvents()
d.grab().save(str(Path(sys.argv[1])/'designer.png'))
final = d.configuration()
d.reject()
assert t == replace(new_template(), offset_x_mm=.123456789)
# Nested designer only modifies the outer draft on acceptance.
outer = TemplateSettingsDialog(t)
TemplateDesignerDialog.exec = lambda self: QtWidgets.QDialog.Rejected
outer.design_template()
assert outer.configuration() == t
def accept(self):
    self.set_design(final)
    return QtWidgets.QDialog.Accepted
TemplateDesignerDialog.exec = accept
outer.design_template()
assert outer.configuration() == final
outer.reject()
assert t.first.reserved == ()
for widget in (d, outer):
    widget.deleteLater()
QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        capture_output=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
