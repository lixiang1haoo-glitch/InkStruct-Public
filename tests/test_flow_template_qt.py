"""Real Windows Qt transactions, PDF process lifetime, content identity and DPI."""

import os
import subprocess
import sys

import pytest


def make_pdf(path):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R 9 0 R] /Count 4 >>",
    ]
    for i in range(4):
        content = f"{i / 4} 0.4 0.8 rg 0 0 340 340 re f\n".encode()
        objects.extend(
            [
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 340.157480315 340.157480315] /Resources << >> /Contents {4 + i * 2} 0 R >>".encode(),
                f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream",
            ]
        )
    raw = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(raw))
        raw += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    pos = len(raw)
    raw += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    raw += b"".join(f"{p:010d} 00000 n \n".encode() for p in offsets[1:])
    raw += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{pos}\n%%EOF\n".encode()
    )
    path.write_bytes(raw)


PROGRAM = r"""
import sys,time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtCore,QtGui,QtWidgets
from inkstruct.document.flow_template import FlowTemplate,NamedField,PageLayout,TextFrame
from inkstruct.document.template import Region
from inkstruct.editor.flow_template_designer import FlowTemplateDesigner
from inkstruct.editor.flow_template_pdf import PdfPagesDialog
from inkstruct.editor.template_content import TemplateContentDialog
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.styles import FlowStyle
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.document.package import save_package,load_package
from inkstruct.renderers.pages import page_svg
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,str(root))
def wait(check,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents()
        if check(): return
        time.sleep(.01)
    raise AssertionError('Timed out')
t=FlowTemplate(name='test',kind='custom',width_mm=120,height_mm=120,
    layouts=(PageLayout('one','第一页',(TextFrame('b','正文',Region('b',5,40,100,60)),TextFrame('f','姓名框',Region('f',5,5,50,20),'field',field_id='name'))),),
    loop_pages=('one',),fields=(NamedField('name','姓名',True),))
d=FlowTemplateDesigner(t)
d.show();app.processEvents()
d.tabs.setCurrentIndex(1)
d.frames.item(1,0).setText('改过的框名')
d.apply_layout()
assert d.template.layouts[0].frames[1].field_id=='name'
d.history(False);assert d.template==t
d.history(True);assert d.template.layouts[0].frames[1].label=='改过的框名'
d.canvas.grab().save(str(root/'canvas.png'))
d.tabs.setCurrentIndex(2)
d.fields.item(0,1).setText('显示名已修改')
d.apply_fields();assert d.template.fields[0].field_id=='name'
d.reject();assert t.fields[0].label=='姓名'
crlf=':::field name\r\n123\r\n:::\r\n\r\n456'
content=TemplateContentDialog(t,crlf)
assert content.configuration()==crlf
content.source.setPlainText(content.source.toPlainText().replace('123','321'))
assert content.configuration()==crlf.replace('123','321')
content.reject();content.deleteLater()

# Cancellable, transactional four-page PDF import from a single process snapshot.
empty=FlowTemplate(kind='custom',layouts=(PageLayout('empty','空布局'),),loop_pages=('empty',))
pdf=PdfPagesDialog(root/'reference.pdf',empty)
pdf.show();wait(lambda:pdf.count==4 and not pdf.pdf.pending)
pdf.pages.setText('1-4');pdf.start_render()
wait(lambda:pdf.candidate is not None or pdf.pdf.closed)
assert pdf.candidate is not None,pdf.error.text()
candidate=pdf.candidate
assert abs(candidate.width_mm-120)<.001
assert [p.source_page for p in candidate.layouts[1:]]==[1,2,3,4]
assert len({p.background.sha256 for p in candidate.layouts[1:]})==4
from inkstruct.layout.blocks import layout_markdown
from inkstruct.assets.resolver import AssetResolver
cycle=replace(candidate,layouts=(candidate.layouts[0],*(replace(p,frames=(replace(p.frames[0],region=replace(p.frames[0].region,height_mm=10)),)) for p in candidate.layouts[1:])))
cycled=layout_markdown(parse_markdown('\n\n'.join(['123']*6),field_blocks=True),AssetResolver(builtin_numbers=True),flow=FlowStyle(template=cycle))
assert cycled.exportable,cycled.diagnostics
assert [p.background.sha256 for p in cycled.pages]==[candidate.layouts[i+1].background.sha256 for i in (0,1,2,3,0,1)]
pdf.accept();assert pdf.pdf.closed
assert pdf.pdf.process.state()==QtCore.QProcess.ProcessState.NotRunning
cancel=PdfPagesDialog(root/'reference.pdf',empty)
cancel.reject();assert cancel.pdf.closed and cancel.candidate is None
assert empty.layouts[0].background is None

w=MixedWindow(source=':::field name\n123\n:::\n\n456 789')
w.show()
w.flow=FlowStyle(template=t)
w.schedule_layout()
wait(lambda:w.snapshot and not w.timer.isActive() and not w.worker)
assert w.snapshot.exportable,w.status.text()
assert w.canvas.page_rect(0).top()>=20  # Source-layout label is fully visible above page one.
before_source=w.source_session.source
body_before={o.text+str(o.span.start):o.occurrence_id for n in w.parse_current_source().nodes if n.kind!='named_field' for c in n.walk() for o in c.occurrences}
before_choices=w.resolver.selection_records()
previous_flow=w.flow
w.template_content_panel.apply_template(replace(t,name='另一个模板'))
wait(lambda:not w.timer.isActive() and not w.worker)
w.template_content_panel.template_history(False)
wait(lambda:not w.timer.isActive() and not w.worker)
assert w.flow==previous_flow
w.template_content_panel.template_history(True)
wait(lambda:not w.timer.isActive() and not w.worker)
assert w.flow.template.name=='另一个模板'
w.template_content_panel.template_history(False)
wait(lambda:not w.timer.isActive() and not w.worker)
assert w.flow==previous_flow
def cancel_content():
    dialog=app.activeModalWidget()
    dialog.source.setPlainText('not applied')
    dialog.reject()
QtCore.QTimer.singleShot(10,cancel_content)
w.template_content_panel.edit()
assert w.source_session.source==before_source
def fill():
    dialog=app.activeModalWidget()
    assert isinstance(dialog,TemplateContentDialog)
    dialog.source.setPlainText(dialog.source.toPlainText().replace('123','321'))
    dialog.accept()
QtCore.QTimer.singleShot(10,fill)
w.template_content_panel.edit()
wait(lambda:not w.timer.isActive() and not w.worker)
body_after={o.text+str(o.span.start):o.occurrence_id for n in w.parse_current_source().nodes if n.kind!='named_field' for c in n.walk() for o in c.occurrences}
assert body_before==body_after
w.source_history('undo')
wait(lambda:not w.timer.isActive() and not w.worker)
assert w.source_session.source==before_source
assert all(s in w.resolver.selection_records() for s in before_choices)
first=page_svg(w.snapshot,0)
save_package(root/'saved.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow)
loaded=load_package(root/'saved.inkdoc')
assert loaded.flow.template==t
assert loaded.session.atom_ids==w.source_session.atom_ids

# Global defaults carry layout only; current-document content remains reachable.
settings=SettingsDialog(w)
settings.select('paper')
paper=settings.pages['paper']
assert not any('当前文档' in b.text() for b in paper.findChildren(QtWidgets.QPushButton))
settings.select('templates')
assert any('打开模板库' in b.text() for b in settings.pages['templates'].findChildren(QtWidgets.QPushButton))
assert not any('编辑当前文档布局' in b.text() for b in settings.pages['templates'].findChildren(QtWidgets.QPushButton))
assert any('编辑本文布局' in b.text() for b in w.template_content_panel.findChildren(QtWidgets.QPushButton))
assert not settings.buttons.isVisible()
before_current=(w.flow,w.style,w.page,w.source_session.atom_ids)
def cancel_current_layout():
    dialog=app.activeModalWidget()
    assert isinstance(dialog,FlowTemplateDesigner)
    assert dialog.template==t
    dialog.name.setText('取消的布局修改')
    dialog.reject()
QtCore.QTimer.singleShot(10,cancel_current_layout)
from inkstruct.editor.template_manager import perform_template_action
perform_template_action(w,'document',t)
assert before_current==(w.flow,w.style,w.page,w.source_session.atom_ids)
paper.template.set_template(candidate)
settings.apply_current.setChecked(False)
assert settings.apply(),settings.error.text()
assert w.flow.template==t and page_svg(w.snapshot,0)==first
settings.reject()
from inkstruct.global_defaults import GlobalDefaultsStore
defaults,warning=GlobalDefaultsStore().load()
assert warning is None and defaults.flow.template==candidate
w.dirty=False;w.recovery_timer.stop();w.close()
for dialog in (d,pdf,cancel,settings):dialog.deleteLater()
app.processEvents()
"""


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
def test_template_transactions_pdf_and_content(tmp_path, dpi):
    make_pdf(tmp_path / "reference.pdf")
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
        timeout=65,
    )
    assert result.returncode == 0, result.stdout + result.stderr
