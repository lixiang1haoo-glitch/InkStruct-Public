import os
import subprocess
import sys

PROGRAM = r'''
import sys,time,json,shutil
from dataclasses import replace
from pathlib import Path
from PySide6 import QtCore,QtWidgets
from test_font_packages import recorded,specimen
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
samples=recorded(root)
if case=='font-release':
    b_specimen=specimen('B','sample-b')
    (samples/'b.json').write_text(json.dumps(b_specimen),'utf-8')
build_font(source,writer='fixture',name='fixture',symbols=samples)
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
elif case=='template-revision':
    from inkstruct.document.template_revision import version_template
    from inkstruct.document.styles import FlowStyle
    p=PageLayout('p','PDF 第 1 页',(
        TextFrame('body','正文',Region('body',15,30,180,220)),
        TextFrame('field','姓名',Region('name',15,10,60,15),role='field',field_id='name'),
        TextFrame('obsolete','旧字段',Region('obsolete',90,10,60,15),role='field',field_id='obsolete')))
    first=FlowTemplate(name='修订验证',kind='custom',layouts=(PageLayout('unused','布局 1'),p),
        loop_pages=('p',),fields=(NamedField('name','姓名',True),NamedField('obsolete','旧字段')))
    second=version_template(replace(first,width_mm=215,layouts=(first.layouts[0],replace(p,frames=p.frames[:2])),
        fields=(NamedField('name','姓名更新',True),)),parent=first)
    store=TemplateStore(workspace/'templates')
    files=[]
    for number,template in enumerate((first,second)):
        path=root/f'template-{number}.json';path.write_text(template_json(template),'utf-8');files.append(store.add(path))
    w.flow=FlowStyle(template=first)
    w.replace_text(':::field name\nA\n:::\n\n:::field obsolete\nA\n:::\n\nA A')
    settle(w)
    original_choices=w.resolver.selection_records()
    old=root/'old.inkdoc';save_package(old,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    store.update(files[0]['id'],archived=True)
    w.load_project_path(old);settle(w)
    panel=w.template_content_panel;panel.refresh()
    assert w.flow.template==first and w.resolver.selection_records()==original_choices
    assert not panel.newer_template_button.isHidden()
    assert store.newer(w.flow.template)==(files[1],)
    browser=TemplateLibrary(w);browser.show()
    assert browser.layouts.currentData()=='p' and '循环' in browser.layouts.currentText()
    assert '备用版式（未加入页组）' in browser.layouts.itemText(1)
    wait(lambda:not browser.preview_jobs)
    assert browser.preview_stack.currentWidget() is browser.preview
    epoch=browser.preview_epoch;browser.layouts.setCurrentIndex(1)
    browser.layout_failed(epoch,'旧结果')
    wait(lambda:not browser.preview_jobs)
    assert browser.preview_stack.currentWidget() is browser.preview
    browser.layout_loaded((browser.preview_epoch,b'invalid SVG'))
    assert browser.preview_status.text()=='模板预览渲染失败'
    browser.close()
    check=TemplateApplyDialog(w,second);check.show();wait(lambda:check.result is not None)
    assert check.result['invalid_bindings']==('obsolete',)
    assert '纸张' in check.summary.text() and '页数' in check.summary.text() and '溢出' in check.summary.text()
    assert w.flow.template==first
    check.reject();assert w.flow.template==first
    check=TemplateApplyDialog(w,second);check.show();wait(lambda:check.result is not None)
    check.acknowledge.setChecked(True);check.accept();settle(w)
    assert w.flow.template==second and ':::field obsolete' in w.source_session.source
    assert any(d.code=='template-field-unknown' for d in w.snapshot.diagnostics)
    w.source_history('undo');settle(w);assert w.flow.template==first
    w.source_history('redo');settle(w);assert w.flow.template==second
    assert GlobalDefaultsStore().load()[0].flow.template is None
    saved=root/'upgraded.inkdoc';save_package(saved,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    w.load_project_path(saved);settle(w);assert w.flow.template==second
elif case=='font-release':
    from inkstruct.fonts.identity import release_identity
    from inkstruct.fonts.library import find_font_release
    from inkstruct.resource_catalog import FontMetadata
    library=workspace/'fonts';library.mkdir()
    prior=library/'original.inkfont';shutil.copyfile(source,prior)
    only_b=root/'only-b';only_b.mkdir();shutil.copyfile(samples/'b.json',only_b/'b.json')
    newer=library/'newer.inkfont';build_font(newer,writer='fixture',name='fixture',symbols=only_b)
    FontMetadata(library).update(prior.name,archived=True)
    identity=release_identity(font.identity)
    assert FontPackage(newer).identity['font_id']==identity[0]
    assert find_font_release(library,identity)==prior
    # Use an older archive with no explicit release member and no embedded B.
    frozen=AssetResolver(embedded=tuple(font.glyphs('A')),selections=w.resolver.selections.values())
    saved=root/'legacy-font.inkdoc';save_package(saved,w.source_session,frozen,w.page,w.style,flow=w.flow)
    w.load_project_path(saved);settle(w)
    assert not w.run_path and w.resolver.font_identity==identity
    w.template_content_panel.refresh();assert not w.template_content_panel.connect_font_button.isHidden()
    w.replace_text(raw+' B');settle(w)
    assert any(d.code=='asset-missing' for d in w.snapshot.diagnostics)
    old_choices=dict(w.resolver.selections)
    check=ResourceApplyDialog(w,font=newer,exact_identity=identity);check.show()
    wait(lambda:check.summary.text().startswith('未应用'))
    assert '核心哈希' in check.summary.text();check.reject()
    check=ResourceApplyDialog(w,font=prior,exact_identity=identity);check.show();wait(lambda:check.result is not None)
    assert all(check.result['resolver'].selections[key]==value for key,value in old_choices.items())
    assert not any(d.code=='asset-missing' for d in check.result['snapshot'].diagnostics)
    check.acknowledge.setChecked(True);check.accept();settle(w);assert w.run_path==str(prior)
    w.source_history('undo');settle(w);assert not w.run_path
    prior.rename(root/'moved.inkfont')
    assert find_font_release(library,identity) is None
    check=ResourceApplyDialog(w,font=newer);check.show();wait(lambda:check.result is not None)
    assert '重新选样 3 处' in check.summary.text() and '新增缺字' in check.summary.text()
    assert any(check.issues.topLevelItem(i).text(0)=='重新选样' for i in range(check.issues.topLevelItemCount()))
    check.reject();assert not w.run_path and w.resolver.font_identity==identity
    check=ResourceApplyDialog(w,font=newer);check.show();wait(lambda:check.result is not None)
    check.acknowledge.setChecked(True);check.accept();settle(w)
    assert w.run_path==str(newer)
    new_doc=root/'new-font.inkdoc';save_package(new_doc,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    assert load_package(new_doc).resolver.font_identity==release_identity(FontPackage(newer).identity)
elif case=='template-workflow':
    from PySide6 import QtTest
    from inkstruct.editor.flow_template_designer import FlowTemplateDesigner
    from inkstruct.editor.template_trial import TemplateTrialDialog
    from inkstruct.document.styles import FlowStyle
    from inkstruct.document import template_authoring

    library=TemplateLibrary(w);library.resize(980,460);library.show()
    tall=FlowTemplate(name='高窄测试',width_mm=70,height_mm=1800,margins_mm=(6,6,6,6))
    pages=(PageLayout('unused','布局 1'),*(PageLayout(f'p{i}',f'PDF 第 {i} 页') for i in range(1,5)))
    grouped=FlowTemplate(name='四页',kind='custom',layouts=pages,loop_pages=('p1','p2','p3','p4'))
    path=root/'tall.json';path.write_text(template_json(tall),'utf-8')
    group_path=root/'grouped.json';group_path.write_text(template_json(grouped),'utf-8')
    library.import_path(path);old_entry=library.selected()['managed']
    wait(lambda:not library.preview_jobs and not library.metadata_jobs)
    assert library.preview.renderer().defaultSize().height()>1800
    assert library.height()==460
    for button in (library.use_button,library.edit_button,library.default_button,library.more_button):
        assert button.isVisible() and library.rect().contains(button.mapTo(library,button.rect().center()))
    library.search.setText('零匹配')
    assert library.selected() is None and library.template is None and '没有匹配' in library.preview_status.text()
    assert all(not button.isEnabled() for button in (library.use_button,library.edit_button,library.default_button,library.more_button))
    library.import_path(group_path)
    assert library.template==grouped and library.layouts.currentData()=='p1'
    library.kind.setCurrentText('简单模板')
    wait(lambda:library.template==tall)
    library.kind.setCurrentIndex(0);library.search.setText('四页')
    assert library.template==grouped
    editor=FlowTemplateDesigner(grouped)
    assert editor.current_layout().layout_id=='p1'
    spare=editor.page_tree.topLevelItem(1)
    assert not spare.isExpanded()
    spare.setExpanded(True);editor.page_tree.setCurrentItem(spare.child(0));editor.refresh()
    assert editor.current_layout().layout_id=='unused'
    editor.reject()

    default_before=GlobalDefaultsStore().load()[0]
    document_before=document_token(w)
    chooser=QtWidgets.QFileDialog.getSaveFileName
    QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external save dialog'))
    checks=[]
    def edit():
        dialog=app.activeModalWidget()
        lock=QtCore.QLockFile(str(library.store.lock_path))
        try:
            assert isinstance(dialog,FlowTemplateDesigner) and dialog.confirm.text()=='保存修改'
            assert dialog.current_layout().layout_id=='p1'
            dialog.name.setText('四页新版')
            assert lock.tryLock(0)
            try:
                QtTest.QTest.mouseClick(dialog.confirm,QtCore.Qt.LeftButton)
                assert dialog.isVisible() and '另一窗口' in dialog.error.text() and dialog.name.text()=='四页新版'
            finally:
                lock.unlock()
            QtTest.QTest.mouseClick(dialog.confirm,QtCore.Qt.LeftButton)
            checks.append(True)
        finally:
            if dialog.isVisible():dialog.reject()
    QtCore.QTimer.singleShot(20,edit)
    QtTest.QTest.mouseClick(library.edit_button,QtCore.Qt.LeftButton)
    QtWidgets.QFileDialog.getSaveFileName=chooser
    assert checks and library.template.name=='四页新版' and library.template.revision.number==2
    assert len(library.store.entries())==3 and library.store.read(old_entry)==tall
    assert library.list.count()==2 and not any('四页 · 修订 1' == library.list.item(i).text()
                                               for i in range(library.list.count()))
    library.history.setChecked(True);assert library.list.count()==3
    library.history.setChecked(False)
    assert document_token(w)==document_before and GlobalDefaultsStore().load()[0]==default_before
    picker=TemplatePicker(grouped,library)
    picker.resize(760,420);picker.show();app.processEvents()
    ok=picker.buttons.button(QtWidgets.QDialogButtonBox.Ok)
    open_file=QtWidgets.QFileDialog.getOpenFileName
    QtWidgets.QFileDialog.getOpenFileName=lambda *a,**k:(str(path),'')
    QtTest.QTest.mouseClick(picker.import_button,QtCore.Qt.LeftButton)
    QtWidgets.QFileDialog.getOpenFileName=open_file
    assert picker.options[picker.list.currentRow()]['id']==old_entry['id']
    assert picker.template==tall and '高窄测试' in picker.summary.text() and ok.isEnabled()
    assert picker.height()==420 and picker.preview.renderer().aspectRatioMode()==QtCore.Qt.KeepAspectRatio
    geometry=template_authoring.geometry_preview
    template_authoring.geometry_preview=lambda *_:'broken svg'
    picker.render_layout()
    assert not ok.isEnabled() and picker.template is None and not picker.preview.renderer().isValid()
    assert '高窄测试' not in picker.summary.text() and '渲染失败' in picker.error.text()
    template_authoring.geometry_preview=geometry
    picker.render_layout();assert picker.template==tall and ok.isEnabled()
    library.store.path(old_entry['id']).write_text('broken private fixture','utf-8')
    picker.select(picker.list.currentRow())
    assert not ok.isEnabled() and not picker.preview.renderer().isValid() and '高窄测试' not in picker.summary.text()
    picker.reject()
    trial=TemplateTrialDialog(tall)
    trial.resize(760,420);trial.show();wait(lambda:trial.snapshot is not None)
    assert trial.height()==420 and trial.preview.renderer().aspectRatioMode()==QtCore.Qt.KeepAspectRatio
    assert '纸面校准' not in trial.summary.text()
    trial.reject()
    from inkstruct.editor.template_manager import remember_template
    from inkstruct.document.template_authoring import read_template
    external=root/'recent-only.json';external.write_text(template_json(grouped),'utf-8')
    remember_template(external);library.recent.setChecked(True)
    library.list.setCurrentRow(next(i for i in range(library.list.count())
        if library.list.item(i).text().startswith('待入库 · recent-only')))
    saved=[]
    def edit_external():
        dialog=app.activeModalWidget()
        try:
            assert dialog.confirm.text()=='保存修改'
            save_as=next(button for button in dialog.findChildren(QtWidgets.QPushButton)
                         if button.text()=='另存为新模板…')
            dialog.name.setText('直接修改最近文件')
            copy=root/'separate-copy.json'
            QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(copy),'')
            QtTest.QTest.mouseClick(save_as,QtCore.Qt.LeftButton)
            assert read_template(external)==grouped and read_template(copy).revision.number==1
            QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external save dialog'))
            QtTest.QTest.mouseClick(dialog.confirm,QtCore.Qt.LeftButton)
            assert read_template(external).name=='直接修改最近文件'
            assert read_template(external).revision.template_id!=read_template(copy).revision.template_id
            saved.append(True)
        finally:
            QtWidgets.QFileDialog.getSaveFileName=chooser
            if dialog.isVisible():dialog.reject()
    QtCore.QTimer.singleShot(20,edit_external)
    QtTest.QTest.mouseClick(library.edit_button,QtCore.Qt.LeftButton)
    assert saved and library.selected()['managed'] is None and library.template.name=='直接修改最近文件'
    assert len(library.store.entries())==4
    library.close()
w.timer.stop();w.recovery_timer.stop()
if w.cancelled:w.cancelled.set()
QtCore.QThreadPool.globalInstance().waitForDone()
w.dirty=False;w.close();app.processEvents()
'''


import pytest


@pytest.mark.parametrize('case', ['font-apply', 'stale-and-failure', 'resource-change-and-picker-cancel', 'font-library', 'template-library', 'template-apply', 'template-revision', 'font-release', 'template-workflow'])
def test_resource_management_preserves_document(tmp_path, case):
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', PROGRAM, str(tmp_path), case],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONUTF8': '1',
                                 'PYTHONPATH': os.pathsep.join(['tests', os.environ.get('PYTHONPATH', '')])},
                            capture_output=True, text=True, encoding='utf-8', timeout=50, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
