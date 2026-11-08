"""Font browser presentation must not retain another resource's details."""
import os
import subprocess
import sys

import pytest

PROGRAM = r'''
import hashlib,sys,time,shutil
from pathlib import Path
from PySide6 import QtCore,QtWidgets,QtTest
from inkstruct.fonts.ui import FontLibrary
from inkstruct.theme import use_light_theme
from inkstruct.fonts.importer import build_font
from test_font_packages import recorded
app=QtWidgets.QApplication([]);use_light_theme(app)
root=Path(sys.argv[1]);case=sys.argv[2]
def wait(predicate):
    deadline=time.monotonic()+20
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    assert predicate(),'timeout'
def settle():
    wait(lambda:b.metadata_job is None and b.inspection_job is None and not b.preview_timer.isActive())
library=root/'fonts';library.mkdir()
if case!='empty':
    source=root/'original.inkfont'
    symbols=recorded(root)
    build_font(source,writer='fixture',name='真实样本测试',symbols=symbols)
    original=source.read_bytes()
    shutil.copyfile(source,library/'valid.inkfont')
if case=='preview-cache':
    from inkstruct.fonts import management_ui
    inspect=management_ui.inspect_font
    calls=[]
    def counted(path,*args,**kwargs):
        calls.append((path,args,kwargs))
        return inspect(path,*args,**kwargs)
    management_ui.inspect_font=counted
    build_font(library/'second.inkfont',writer='fixture',name='Second',symbols=symbols)
b=FontLibrary(library);b.resize(1000,720);b.show();settle()
if case=='empty':
    assert b.empty_title.text()=='还没有字体'
    assert b.detail_stack.currentWidget() is b.empty_page
    assert not b.use_button.isEnabled() and not b.rename_action.isEnabled()
    assert b.import_button.property('inkRole')=='primary'
    assert b.library_count.text()=='显示 0 / 0 项'
elif case=='filter-and-clear':
    assert b.detail_stack.currentWidget() is b.details_tabs
    assert b.use_button.property('inkRole')=='primary'
    assert b.create_button.property('inkRole')!='primary'
    b.character_search.setText('A');settle()
    assert b.sample_count.text() and b.version_info.toPlainText() and b.file_info.toPlainText()
    old_epoch=b.inspection_epoch
    b.search.setText('不存在的字体');app.processEvents()
    assert b.empty_title.text()=='没有匹配的字体'
    assert b.inspection_epoch>old_epoch and not b.use_button.isEnabled()
    assert not b.preview_timer.isActive()
    assert not b.sample_count.text() and not b.resource_state.text()
    assert not b.version_info.toPlainText() and not b.file_info.toPlainText()
    assert b.character_list.count()==b.version_list.count()==0
    # A result or failure from the old choice must not fill the empty panel.
    b.inspected((str(library/'valid.inkfont'),old_epoch,{}))
    b.inspection_failed('旧任务报错',str(library/'valid.inkfont'),old_epoch)
    assert not b.preview_state.text() and b.empty_title.text()=='没有匹配的字体'
    b.search.clear();b.list.setCurrentRow(0);settle()
    assert b.detail_stack.currentWidget() is b.details_tabs and b.use_button.isEnabled()
    (library/'valid.inkfont').unlink();b.refresh();settle()
    assert b.detail_stack.currentWidget() is b.empty_page
    assert not b.use_button.isEnabled() and not b.file_info.toPlainText()
elif case=='broken-and-stale':
    path=library/'valid.inkfont';old_epoch=b.inspection_epoch
    path.write_bytes(b'not a font');b.refresh();settle()
    assert b.empty_title.text()=='字体暂不可读取'
    assert b.empty_text.text() and not b.use_button.isEnabled()
    assert not b.sample_count.text() and not b.file_info.toPlainText()
    b.inspected((str(path),old_epoch,{}))
    b.inspection_failed('迟到结果',str(path),old_epoch)
    assert b.empty_title.text()=='字体暂不可读取' and not b.preview_state.text()
elif case=='keyboard-and-picker':
    from inkstruct.resources_ui import FontPicker
    # The browser's local focus chain begins with creation, then search/filter/list.
    b.import_button.setFocus();QtTest.QTest.keyClick(b.import_button,QtCore.Qt.Key_Tab)
    assert app.focusWidget() is b.create_button
    QtTest.QTest.keyClick(b.create_button,QtCore.Qt.Key_Tab)
    assert app.focusWidget() is b.search
    QtTest.QTest.keyClick(b.search,QtCore.Qt.Key_Tab)
    assert app.focusWidget() is b.writer_filter
    assert b.search.accessibleName()=='搜索字体'
    assert b.list.accessibleName()=='字体列表'
    picker=FontPicker(b);picker.show();app.processEvents()
    assert picker.browser.create_button.isHidden() and picker.browser.default_button.isHidden()
    assert [x.text() for x in picker.browser.selection_buttons if not x.isHidden()]==['选择此字体']
    picker.reject();assert picker.path is None
    QtCore.QThreadPool.globalInstance().waitForDone();app.processEvents();picker.deleteLater()
elif case=='compact-preview':
    item=b.list.currentItem()
    assert item.text()=='真实样本测试' and '\n' not in item.text()
    assert 'fixture' in item.toolTip() and '内容版本' in item.toolTip()
    assert '书写者：fixture' in b.detail.text() and '内容版本' in b.detail.text()
    assert b.preview_mode.currentData()=='mixed'
    assert '\n' in b.preview_text.toPlainText()
    # Formula rendering must report absent resources, never use invented digits.
    b.preview_mode.setCurrentIndex(1);settle()
    assert '\\frac' in b.preview_text.toPlainText()
    assert '非成品导出' in b.preview_state.text()
    assert b.preview_state.toolTip() and 'missing' in b.preview_state.toolTip()
    b.preview_text.setPlainText('A A');settle()
    assert b.preview_mode.currentData()=='custom'
    assert b.preview_text.toPlainText()=='A A'
    # Details remain searchable after removing them from the visible row.
    b.search.setText('fixture');app.processEvents()
    assert not b.list.item(0).isHidden()
elif case=='visual-hierarchy':
    assert b.font_title.text()=='真实样本测试' and b.font_header.isVisible()
    assert 'fixture' in b.font_meta.text()
    assert not b.preview_text.isVisible() and b.edit_preview_button.isVisible()
    b.edit_preview_button.click();app.processEvents()
    assert b.preview_mode.currentData()=='custom' and b.preview_text.isVisible()
    assert app.focusWidget() is b.preview_text
    b.preview_text.setPlainText('A A A');settle()
    b.preview_mode.setCurrentIndex(0);settle()
    assert not b.preview_text.isVisible()
    b.preview_mode.setCurrentIndex(2);settle()
    assert b.preview_text.toPlainText()=='A A A'
    b.preview_mode.setCurrentIndex(1);settle()
    assert not b.preview_text.isVisible() and 'missing' in b.preview_state.toolTip()
    assert b.resource_state.isVisible() and '来源提示' in b.resource_state.text()
    contents=[]
    def inspect_dialog():
        d=app.activeModalWidget()
        assert isinstance(d,QtWidgets.QDialog)
        contents.append(d.findChild(QtWidgets.QPlainTextEdit).toPlainText())
        d.reject()
    QtCore.QTimer.singleShot(0,inspect_dialog)
    b.preview_details_button.click()
    assert contents and 'missing' in contents[0] and 'fixture' in contents[0]
    path=b.selected();summary=b.catalog[path.name]['summary']
    original_detail=summary['detail'];summary['detail']=''
    b.update_management(path)
    assert '字体摘要无详细统计' in b.resource_state.text()
    summary['detail']=original_detail
    original_stamp=summary['stamp'];summary['stamp']=[]
    b.update_management(path)
    assert not b.font_title.text() and not b.font_meta.text() and not b.font_header.isVisible()
    summary['stamp']=original_stamp;b.update_management(path);settle()
    b.search.setText('not-found');app.processEvents()
    assert not b.font_header.isVisible() and not b.font_title.text()
elif case=='preview-cache':
    first=b.list.currentRow()
    first_path=b.selected()
    first_state=b.preview_state.text()
    before=len(calls)
    b.list.setCurrentRow(1-first)
    assert b.preview_display.currentWidget() is b.preview_message
    assert b.preview_message.text()=='正在加载预览…'
    assert b.preview_message.alignment()==QtCore.Qt.AlignCenter
    settle()
    assert len(calls)==before+1
    b.list.setCurrentRow(first)
    assert not b.preview_timer.isActive()
    assert b.preview_display.currentWidget() is b.ink_preview
    assert b.ink_preview.renderer().isValid() and b.preview_state.text()==first_state
    assert len(calls)==before+1
    b.preview_mode.setCurrentIndex(1);settle()
    notes=b.preview_state.toolTip()
    assert 'missing' in notes
    b.preview_mode.setCurrentIndex(0)
    b.preview_mode.setCurrentIndex(1)
    assert len(calls)==before+2 and b.preview_state.toolTip()==notes
    import os
    stamp=first_path.stat()
    os.utime(first_path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1000000000))
    b.queue_inspection()
    assert b.preview_display.currentWidget() is b.preview_message
    settle()
    assert len(calls)==before+3 and b.preview_display.currentWidget() is b.ink_preview
else:
    raise AssertionError(case)
if case!='empty':
    assert source.read_bytes()==original
QtCore.QThreadPool.globalInstance().waitForDone();app.processEvents()
b.close();app.processEvents()
'''


@pytest.mark.parametrize('dpi', ['1', '1.5', '2'])
@pytest.mark.parametrize('case', ['empty', 'filter-and-clear', 'broken-and-stale', 'keyboard-and-picker', 'compact-preview', 'visual-hierarchy', 'preview-cache'])
def test_font_library_presentation(tmp_path, dpi, case):
    result = subprocess.run(
        [sys.executable, '-B', '-X', 'utf8', '-c', PROGRAM, str(tmp_path), case],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_SCALE_FACTOR': dpi,
             'PYTHONPATH': os.pathsep.join(['tests', os.environ.get('PYTHONPATH', '')])},
        capture_output=True, text=True, encoding='utf8', timeout=50, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
