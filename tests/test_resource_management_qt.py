import os
import subprocess
import sys

PROGRAM = r'''
import sys,time,json,shutil
from dataclasses import replace
from pathlib import Path
from PySide6 import QtCore,QtWidgets
from test_font_packages import recorded
from inkstruct.fonts.importer import build_font
from inkstruct.fonts.core import FontPackage,to_user
from inkstruct.fonts.ui import FontLibrary
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import FlowTemplate,PageLayout,TextFrame,NamedField
from inkstruct.document.template import Region
from inkstruct.document.template_authoring import template_json
from inkstruct.document.package import load_package,save_package
from inkstruct.editor.mixed import MixedWindow,build_markdown
from inkstruct.editor.resource_apply import ResourceApplyDialog,TemplateApplyDialog,document_token
from inkstruct.editor.template_library import TemplateLibrary
from inkstruct.editor.template_manager import TemplatePicker,remember_template
from inkstruct.assets.resolver import AssetResolver
from inkstruct.resource_catalog import TemplateStore
from inkstruct.global_defaults import GlobalDefaultsStore
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg

app=QtWidgets.QApplication([]);app.setStyle('Fusion')
root=Path(sys.argv[1]);case=sys.argv[2]
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,str(root/'settings'))
def wait(predicate):
    deadline=time.monotonic()+20
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.002)
    assert predicate(),'operation timed out'
def settle(w):
    wait(lambda:w.snapshot is not None and not w.worker and not w.timer.isActive())
source=root/'font.inkfont'
build_font(source,writer='fixture',name='fixture',symbols=recorded(root))
font=FontPackage(source)
original=source.read_bytes()
workspace=root/'workspace';workspace.mkdir()
w=MixedWindow(source='A A $A$');w.workspace=workspace
w.run_path=str(source);w.resolver=AssetResolver();w.schedule_layout();settle(w)
initial=w.resolver.selection_records();raw=w.source_session.source
if case=='font-apply':
    user=root/'user.inkfont';to_user(source,user)
    check=ResourceApplyDialog(w,font=user);check.show();wait(lambda:check.result is not None)
    assert check.result['retained']==len(initial)
    assert w.resolver.selection_records()==initial
    check.reject();assert w.run_path==str(source) and w.source_session.source==raw
    check=ResourceApplyDialog(w,font=user);check.show();wait(lambda:check.result is not None)
    check.acknowledge.setChecked(True);check.accept();settle(w)
    assert w.run_path==str(user)
    assert w.resolver.selection_records()==initial
    w.source_history('undo');settle(w);assert w.run_path==str(source) and w.resolver.selection_records()==initial
    w.source_history('redo');settle(w);assert w.run_path==str(user) and w.resolver.selection_records()==initial
    save_package(root/'saved.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    saved=load_package(root/'saved.inkdoc')
    assert saved.session.source==raw and saved.resolver.selection_records()==initial
    assert w.snapshot.plotter_exportable,w.snapshot.diagnostics
    before=[page_svg(p) for p in plan_from_snapshot(w.snapshot).pages]
    rebuilt=build_markdown(saved.session,0,saved.resolver,'','',saved.page,saved.style,saved.flow,None)
    assert before==[page_svg(p) for p in plan_from_snapshot(rebuilt['snapshot']).pages]
    assert source.read_bytes()==original
elif case=='stale-and-failure':
    check=ResourceApplyDialog(w,font=source);check.show();wait(lambda:check.result is not None)
    check.acknowledge.setChecked(True)
    w.replace_text('A A A');check.accept()
    assert check.result is None and '变化' in check.summary.text()
    assert w.run_path==str(source)
    check.reject();settle(w)
    broken=root/'broken.inkfont';broken.write_bytes(b'broken')
    check=ResourceApplyDialog(w,font=broken);check.show();wait(lambda:check.summary.text().startswith('未应用'))
    assert not check.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
    assert w.run_path==str(source);check.reject()
elif case=='resource-change-and-picker-cancel':
    target=root/'candidate.inkfont';shutil.copyfile(source,target)
    before=document_token(w)
    check=ResourceApplyDialog(w,font=target);check.show();wait(lambda:check.result is not None)
    check.acknowledge.setChecked(True)
    import os
    stat=target.stat();os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns+10000000))
    check.accept()
    assert check.result is None and '变化' in check.summary.text()
    assert document_token(w)==before;check.reject()
    check=ResourceApplyDialog(w,font=target);check.reject()
    QtCore.QThreadPool.globalInstance().waitForDone();app.processEvents()
    assert document_token(w)==before
    from inkstruct.resources_ui import FontPicker
    picker=FontPicker(w);picker.choose(str(target));picker.reject()
    QtCore.QThreadPool.globalInstance().waitForDone();app.processEvents()
    assert picker.path is None and picker.result()==QtWidgets.QDialog.Rejected
    assert document_token(w)==before
    picker.deleteLater()
elif case=='font-library':
    library=workspace/'fonts';library.mkdir()
    shutil.copyfile(source,library/'first.inkfont');to_user(source,library/'second.inkfont')
    (library/'bad.inkfont').write_bytes(b'bad')
    browser=FontLibrary(library);browser.show()
    wait(lambda:browser.metadata_job is None)
    assert browser.list.count()==3
    assert any('不可读取' in browser.list.item(i).text() for i in range(3))
    browser.show_history.setChecked(True)
    browser.list.setCurrentRow(next(i for i in range(3) if 'bad' not in browser.list.item(i).data(QtCore.Qt.UserRole)))
    wait(lambda:browser.inspection_job is None and not browser.preview_timer.isActive())
    chosen=browser.selected();content=chosen.read_bytes()
    browser.change_metadata(alias='显示别名')
    assert chosen.read_bytes()==content
    browser.archive_font();browser.show_archived.setChecked(True)
    browser.list.setCurrentRow(next(i for i in range(3) if browser.list.item(i).data(QtCore.Qt.UserRole)==str(chosen)))
    browser.archive_font();assert chosen.read_bytes()==content
    before=document_token(w)
    browser.default_font();wait(lambda:browser.job is None)
    assert GlobalDefaultsStore().load()[0].run==str(chosen.resolve())
    assert document_token(w)==before
    browser.character_search.setText('A');wait(lambda:browser.inspection_job is None and not browser.preview_timer.isActive())
    assert '独立录制' in browser.sample_count.text()
    assert 'A' in browser.preview_text.toPlainText()
    browser.character_preview.resize(800,120);app.processEvents()
    image=browser.character_preview.grab().toImage()
    xs=[];ys=[]
    for y in range(image.height()):
        for x in range(image.width()):
            pixel=image.pixelColor(x,y)
            if pixel.red()<100 and pixel.green()<100 and pixel.blue()<120:
                xs.append(x);ys.append(y)
    assert xs and max(xs)-min(xs)<image.height()*2,'glyph stretched to fit wide preview'
    browser.close()
elif case=='template-library':
    template=FlowTemplate(name='模板一')
    path=root/'template.json';path.write_text(template_json(template),'utf-8');remember_template(path)
    library=TemplateLibrary(w);library.show()
    library.recent.setChecked(True);assert library.list.count()==1
    library.add_selected();assert len(library.store.entries())==1
    path.rename(root/'moved.json')
    library.recent.setChecked(False);library.refresh()
    assert library.template==template
    before=document_token(w)
    library.set_default();assert document_token(w)==before
    assert GlobalDefaultsStore().load()[0].flow.template==template
    picker=TemplatePicker(None,library)
    assert any('库内' in picker.list.item(i).text() for i in range(picker.list.count()))
    picker.list.setCurrentRow(2);assert picker.template==template
    picker.reject()
    library.archive();assert not library.list.count()
    library.archived.setChecked(True);assert library.list.count()==1
    library.archive();library.archived.setChecked(False)
    assert library.list.count()==1
    assert w.source_session.source==raw and w.resolver.selection_records()==initial
    library.close()
elif case=='template-apply':
    t=FlowTemplate(name='具名字段',kind='custom',layouts=(PageLayout('p','循环页',(
        TextFrame('body','正文',Region('body',15,30,180,220)),
        TextFrame('field','姓名',Region('name',15,10,60,15),role='field',field_id='name'),)),),loop_pages=('p',),fields=(NamedField('name','姓名',True),))
    check=TemplateApplyDialog(w,t);check.show();wait(lambda:check.result is not None)
    assert any(d.code=='template-field-required' for d in check.result['snapshot'].diagnostics)
    assert w.flow.template is None
    check.acknowledge.setChecked(True);check.accept();settle(w)
    assert w.flow.template==t and w.source_session.source==raw and w.resolver.selection_records()==initial
    w.source_history('undo');settle(w);assert w.flow.template is None
    assert w.resolver.selection_records()==initial
    w.source_history('redo');settle(w);assert w.flow.template==t
w.timer.stop();w.recovery_timer.stop()
if w.cancelled:w.cancelled.set()
QtCore.QThreadPool.globalInstance().waitForDone()
w.dirty=False;w.close();app.processEvents()
'''


import pytest


@pytest.mark.parametrize('case', ['font-apply', 'stale-and-failure', 'resource-change-and-picker-cancel', 'font-library', 'template-library', 'template-apply'])
def test_resource_management_preserves_document(tmp_path, case):
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', PROGRAM, str(tmp_path), case],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONUTF8': '1',
                                 'PYTHONPATH': os.pathsep.join(['tests', os.environ.get('PYTHONPATH', '')])},
                            capture_output=True, text=True, encoding='utf-8', timeout=50, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
