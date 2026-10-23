"""Generic PDF-page references, physical dimensions and transactional import."""

import os
import subprocess
import sys

import pytest


def make_pdf(path):
    # Two independent pages; page two has /Rotate 90. No external PDF library.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    ]
    for index, (width, height, rotation, color) in enumerate(
        ((100, 150, 0, "0.85 0.15 0.15"), (80, 120, 90, "0.15 0.15 0.85"))
    ):
        w, h = width * 72 / 25.4, height * 72 / 25.4
        content = f"{color} rg 0 0 {w} {h} re f\n".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Rotate {rotation} /Resources << >> /Contents {4 + index * 2} 0 R >>".encode()
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream")
    raw = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(raw))
        raw += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(raw)
    raw += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    raw += b"".join(f"{pos:010d} 00000 n \n".encode() for pos in offsets[1:])
    raw += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(raw)


def run_qt(tmp_path, program):
    pytest.importorskip("PySide6.QtPdf")
    path = tmp_path / "reference.pdf"
    make_pdf(path)
    setup = r"""
from pathlib import Path
from dataclasses import replace
from hashlib import sha256
import io,sys,time
from PIL import Image
from PySide6 import QtWidgets,QtCore
from inkstruct.editor.template_pdf import PdfReference,PdfReferenceDialog
from inkstruct.editor.template_designer import TemplateDesignerDialog
from inkstruct.document.template_authoring import new_template
from inkstruct.document.template import Region
app=QtWidgets.QApplication([])
def ready(dialog):
    end=time.monotonic()+10
    while time.monotonic()<end:
        app.processEvents()
        if not dialog.pdf.pending and (dialog.candidate is not None or dialog.pdf.closed):return
        time.sleep(.01)
    raise AssertionError(dialog.error.text())
path=Path(sys.argv[1]);raw=path.read_bytes()
"""
    result = subprocess.run(
        [sys.executable, "-c", setup + program, str(path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pdf_snapshot_dimensions_rotation_and_render(tmp_path):
    run_qt(
        tmp_path,
        r"""
pdf=PdfReference(path)
assert pdf.page_count==2 and pdf.source_sha256==sha256(raw).hexdigest()
for actual,expected in zip(pdf.page_size_mm(0),(100,150)):
    assert abs(actual-expected)<1e-4
for actual,expected in zip(pdf.page_size_mm(1),(120,80)):
    assert abs(actual-expected)<1e-4
red=pdf.background(0)
with Image.open(io.BytesIO(red.png_bytes())) as im:
    assert im.width<im.height and max(im.size)<=1600
    p=im.getpixel((5,5));assert p[0]>200 and p[2]<60
blue=pdf.background(1)
assert red.sha256!=blue.sha256
with Image.open(io.BytesIO(blue.png_bytes())) as im:
    assert im.width>im.height
    p=im.getpixel((5,5));assert p[2]>200 and p[0]<60
# The backend renders the immutable bytes already read, even if the file changes.
path.write_bytes(b'changed after opening')
assert pdf.background(0)==red
path.write_bytes(raw)
for index in (-1,2):
    try:pdf.page_size_mm(index)
    except ValueError:pass
    else:raise AssertionError('accepted out of range page')
pdf.close();pdf.close()
assert pdf.device.size()==0 and pdf.cached_background is None
try:pdf.background(0)
except ValueError:pass
else:raise AssertionError('rendered after closing')
""",
    )


def test_pdf_modes_preserve_or_explicitly_replace_geometry(tmp_path):
    run_qt(
        tmp_path,
        r"""
pdf=PdfReference(path)
t=new_template()
t=replace(t,offset_x_mm=.123456789,calibration='user-measured',
          first=replace(t.first,reserved=(Region('field',20,10,50,10),)))
a=pdf.apply(t,'first',0)
assert replace(a.first,background=None)==t.first
assert a.continuation==t.continuation and a.offset_x_mm==t.offset_x_mm
assert a.width_mm==t.width_mm and a.height_mm==t.height_mm
assert a.source_sha256==pdf.source_sha256 and a.calibration=='unreviewed'
b=pdf.apply(a,'continuation',1)
assert b.first==a.first and b.source_sha256==pdf.source_sha256
foreign=replace(a,source_sha256='1'*64)
assert pdf.apply(foreign,'continuation',1).source_sha256==''
new=pdf.apply(b,'first',1,mode='new')
assert abs(new.width_mm-120)<1e-4 and abs(new.height_mm-80)<1e-4
assert not new.first.reserved and not new.continuation.reserved
assert new.offset_x_mm==new.offset_y_mm==0 and new.mode=='preprinted'
assert new.first.body==new.continuation.body
assert abs(new.first.body.x_mm-8)<1e-4 and new.first.body.x_mm==new.first.body.y_mm
assert new.first.background and new.continuation.background is None
assert path.read_bytes()==raw
pdf.close()
""",
    )


def test_pdf_dialog_cancel_accept_and_outer_undo(tmp_path):
    run_qt(
        tmp_path,
        r"""
t=new_template()
d=PdfReferenceDialog(path,t,'first');d.show();ready(d)
assert d.page.maximum()==2 and '尺寸不同' in d.note.text()
assert d.configuration().width_mm==210
assert d.configuration().first.background
first=d.configuration().first.background.sha256
d.page.setValue(2);ready(d)
assert d.configuration().first.background.sha256!=first
d.mode.setCurrentIndex(d.mode.findData('new'));ready(d)
assert abs(d.configuration().width_mm-120)<1e-4
assert '新建' in d.note.text()
d.accept()
assert d.result()==QtWidgets.QDialog.Accepted and d.pdf.closed
assert d.configuration().first.background
d.deleteLater()
outer=TemplateDesignerDialog(t)
QtWidgets.QFileDialog.getOpenFileName=lambda *args:(str(path),'')
PdfReferenceDialog.exec=lambda self:QtWidgets.QDialog.Rejected
outer.import_background()
assert outer.configuration()==t and not outer.json_editor.document().isUndoAvailable()
def accept(self):
    ready(self);self.page.setValue(2);ready(self)
    self.mode.setCurrentIndex(self.mode.findData('new'));ready(self)
    self.accept();return self.result()
PdfReferenceDialog.exec=accept
outer.import_background()
assert abs(outer.configuration().width_mm-120)<1e-4
outer.json_editor.undo();assert outer.configuration()==t
assert path.read_bytes()==raw
# A malformed PDF cannot replace the existing design or create an undo record.
path.write_bytes(b'not a PDF')
def invalid(self):
    ready(self);assert self.error.text() and self.candidate is None
    self.reject();return self.result()
PdfReferenceDialog.exec=invalid
outer.import_background();assert outer.configuration()==t
path.write_bytes(raw)
outer.reject();outer.deleteLater()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
""",
    )


def test_pdf_rejects_invalid_input_and_byte_budget(tmp_path):
    run_qt(
        tmp_path,
        r"""
import inkstruct.editor.template_pdf as module
module.MAX_PDF_BYTES=10
try:PdfReference(path)
except ValueError as e:assert '50 MiB' in str(e)
else:raise AssertionError('accepted oversized input')
module.MAX_PDF_BYTES=50*1024*1024
for data in (b'',b'bad file',b'%PDF-1.4\n%%EOF'):
    path.write_bytes(data)
    try:PdfReference(path)
    except ValueError:pass
    else:raise AssertionError('accepted invalid PDF')
path.write_bytes(raw)
""",
    )


def test_pdf_cli_uses_shared_model_and_new_output_only(tmp_path):
    pytest.importorskip("PySide6.QtPdf")
    path = tmp_path / "reference.pdf"
    make_pdf(path)
    output = tmp_path / "template.json"
    program = r"""
import json,sys
from pathlib import Path
from inkstruct.cli import main
from inkstruct.document.template_authoring import read_template,template_json
path,output=map(Path,sys.argv[1:])
original=path.read_bytes()
assert main(['document','template','from-pdf',str(path),'--page','2','--output',str(output)])==0
first=read_template(output)
assert abs(first.width_mm-120)<1e-4 and first.first.background
saved=output.read_bytes()
assert main(['document','template','from-pdf',str(path),'--page','1','--output',str(output)])==2
assert output.read_bytes()==saved
second=output.with_name('with-continuation.json')
assert main(['document','template','from-pdf',str(path),'--page','1','--template',str(output),
             '--face','continuation','--output',str(second)])==0
changed=read_template(second)
assert changed.first==first.first and changed.width_mm==first.width_mm
assert changed.continuation.background and changed.source_sha256==first.source_sha256
bad=output.with_name('invalid.json')
assert main(['document','template','from-pdf',str(path),'--page','0','--output',str(bad)])==2
assert not bad.exists() and path.read_bytes()==original
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(path), str(output)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
