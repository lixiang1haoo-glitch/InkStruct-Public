"""Model geometry failures retain actionable locations through JSON and the GUI."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from inkstruct.cli import main
from inkstruct.document.template_authoring import parse_template
from inkstruct.document.template_validation import TemplateValidationError, json_value_span


def record():
    return json.loads(Path("configs/templates/generic-record-v2.json").read_text(encoding='utf-8'))


def failure(value):
    with pytest.raises(TemplateValidationError) as caught:
        parse_template(json.dumps(value))
    return caught.value


def test_overlap_reports_both_participants_and_preserves_draft():
    value = record()
    value["first"]["reserved"][0]["y_mm"] = 32
    before = deepcopy(value)
    error = failure(value)
    assert error.code == "template-regions-overlap"
    assert error.paths == (("first", "body"), ("first", "reserved", 0))
    assert value == before


@pytest.mark.parametrize("kind", ["region", "anchor", "rule", "offset"])
def test_outside_paper_points_to_object_and_calibration(kind):
    value = record()
    if kind == "region":
        value["first"]["reserved"][0]["x_mm"] = -1
        expected = ("first", "reserved", 0)
    elif kind == "anchor":
        value["first"]["anchors"][0]["x_mm"] = -1
        expected = ("first", "anchors", 0)
    elif kind == "rule":
        value["first"]["rules"][0]["points"][0][0] = 0
        expected = ("first", "rules", 0, "points", 0)
    else:
        value["offset_x_mm"] = 100
        expected = ("first", "body")
    error = failure(value)
    assert error.code == "template-outside-paper"
    assert error.paths == (expected, ("offset_x_mm",), ("offset_y_mm",))


@pytest.mark.parametrize(
    "property_name,code",
    [("width_mm", "template-body-width-mismatch"), ("height_mm", "template-body-height-mismatch")],
)
def test_cross_face_constraints_expose_both_property_locations(property_name, code):
    value = record()
    value["continuation"]["body"][property_name] -= 1
    error = failure(value)
    assert error.code == code
    assert error.paths == (
        ("first", "body", property_name),
        ("continuation", "body", property_name),
    )


def test_duplicate_and_malformed_objects_locate_exact_records():
    value = record()
    value["first"]["anchors"].append(deepcopy(value["first"]["anchors"][0]))
    assert failure(value).paths == (
        ("first", "anchors", 0, "name"),
        ("first", "anchors", 1, "name"),
    )
    value = record()
    value["first"]["reserved"][0]["width_mm"] = "bad"
    assert failure(value).paths == (("first", "reserved", 0),)
    value = record()
    value["slots"][0]["region"] = "missing"
    assert failure(value).paths == (("slots", 0, "region"),)


def test_json_locations_handle_whitespace_duplicates_escaped_keys_and_unicode():
    source = ' {"emoji":"😀", "a":[{"x":1}], "a": [ {"x": 23, "q\\"": "汉"} ] } '
    for path, expected in [(("a", 0, "x"), "23"), (("a", 0, 'q"'), '"汉"'), (("emoji",), '"😀"')]:
        a, b = json_value_span(source, path)
        assert source[a:b] == expected
    assert json_value_span(source, ("a", 4)) is None
    assert json_value_span(source, ("missing",)) is None
    with pytest.raises(json.JSONDecodeError):
        json_value_span("{", ())


def test_agent_errors_return_paths_and_do_not_create_preview(tmp_path, capsys):
    value = record()
    value["first"]["reserved"][0]["y_mm"] = 32
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(value))
    original = source.read_bytes()
    output = tmp_path / "preview"
    assert main(["document", "template", "preview", str(source), "--output", str(output)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["valid"] and not output.exists() and source.read_bytes() == original
    assert report["diagnostics"][0]["targets"][1]["pointer"] == "/first/reserved/0"
    source.write_text('{"name": "😀",}',encoding='utf-8')
    assert main(["document", "template", "validate", str(source)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["diagnostics"][0]["code"] == "template-json-syntax"
    with pytest.raises(json.JSONDecodeError) as caught:
        json.loads(source.read_text(encoding='utf-8'))
    assert report["diagnostics"][0]["source_offset"] == caught.value.pos
    source.write_text("[" * 10000 + "]" * 10000)
    assert main(["document", "template", "validate", str(source)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["diagnostics"][0]["code"] == "template-json-depth"


def test_designer_locates_and_repairs_invalid_draft_without_losing_undo():
    pytest.importorskip("PySide6")
    program = r"""
import json
from pathlib import Path
from PySide6 import QtWidgets,QtCore
from inkstruct.document.template_authoring import read_template
from inkstruct.editor.template_designer import TemplateDesignerDialog
app=QtWidgets.QApplication([])
template=read_template(Path('configs/templates/generic-record-v2.json'))
d=TemplateDesignerDialog(template);d.show();app.processEvents()
raw=d.json_editor.toPlainText();data=json.loads(raw)
data['first']['reserved'][0]['y_mm']=32
d.write_draft(data)
bad=d.json_editor.toPlainText()
assert d.valid_template is None and d.preview.isHidden()
assert not d.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
assert d.issue_picker.count()==2 and '填写区' in d.issue_picker.itemText(1)
d.issue_picker.setCurrentIndex(1);d.issue_button.click()
assert d.element.currentData()==('reserved',0)
assert d.json_editor.toPlainText()==bad
assert json.loads(d.json_editor.textCursor().selectedText().replace('\u2029','\n'))['y_mm']==32
d.json_editor.undo();assert d.configuration()==template
d.json_editor.redo();assert d.valid_template is None
d.issue_picker.setCurrentIndex(1);d.locate_issue()
row=next(i for i in range(d.element_properties.rowCount()) if d.element_properties.item(i,0).data(QtCore.Qt.UserRole)=='y_mm')
d.element_properties.item(row,1).setText('10')
assert not d.issue_button.isEnabled() and not d.issue_picker.isEnabled()
d.apply_element.click();assert d.configuration()==template
data=json.loads(raw);data['continuation']['body']['width_mm']=160
d.write_draft(data);d.issue_picker.setCurrentIndex(1);d.locate_issue()
assert d.face.currentData()=='continuation'
assert d.element.currentData()==('body',None)
assert d.element_properties.item(d.element_properties.currentRow(),0).data(QtCore.Qt.UserRole)=='width_mm'
data=json.loads(raw);data['slots'][0]['region']='missing'
d.write_draft(data);d.locate_issue()
assert d.tabs.currentIndex()==1 and d.json_editor.textCursor().selectedText()=='"missing"'
text='{"name": "😀",}'
d.json_editor.setPlainText(text);d.locate_issue()
assert d.tabs.currentIndex()==1
try:
    json.loads(text)
except json.JSONDecodeError as error:
    pos=error.pos
assert d.json_editor.textCursor().selectedText()==text[pos:pos+1]
assert d.json_editor.textCursor().selectionStart()==len(text[:pos].encode('utf-16-le'))//2
assert not d.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
d.json_editor.setPlainText('['*10000+']'*10000);d.locate_issue()
assert d.tabs.currentIndex()==1 and d.valid_template is None
d.reject();assert template.first.reserved[0].y_mm==10
d.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
