import os
import subprocess
import sys
import textwrap

import pytest


def test_capture_shortcut_and_sample_page_exchange(tmp_path):
    pytest.importorskip('PySide6')
    code = r'''
        import sys
        from pathlib import Path
        from time import monotonic, sleep

        sys.path.insert(0, 'tests')

        from PySide6 import QtCore, QtTest, QtWidgets

        from inkstruct.application import InkStructWindow
        from inkstruct.sample_library import open_bundle
        from test_sample_library import write
        from test_symbol_provider import specimen

        root = Path(sys.argv[1])
        app = QtWidgets.QApplication([])
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
        QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root))
        window = InkStructWindow(workspace=root / 'w')
        window.show()
        capture = window.collector.symbol_widget
        catalog = capture._capture_catalog
        for key in ('a', 'b'):
            (catalog.root / 'samples' / key).mkdir(parents=True)
            catalog.rename_writer(key, key)
        for char, identity in (('1', 'one'), ('1', 'two'), ('2', 'three')):
            write(catalog, 'symbol', 'a', {**specimen(char, identity, height=25 if identity == 'two' else 10), 'writer_id': 'a',
                   'task': {'task_id': 'earlier' if identity == 'one' else 'later'},
                   'capture': {'coordinate_space': 'logical_px', 'created_at': '2026-01-01T00:00:00Z'}})
        page = window.sample_library
        resources = window.shell_sidebar.layout()
        assert [item.widget().text() for n in range(resources.count())
                if isinstance((item := resources.itemAt(n)).widget(), QtWidgets.QToolButton)] == [
                    '采集', '生成', '排版', '样本库', '字体库', '模板库', '设置']

        def wait(condition):
            deadline = monotonic() + 15
            while not condition():
                app.processEvents()
                sleep(.01)
                assert monotonic() < deadline, page.status.text()

        button = window.findChild(QtWidgets.QToolButton, 'navigate_samples')
        button.click()
        assert window.tabs.currentWidget() is page and button.isChecked()
        window.navigation_buttons[0].click()
        capture.writer_picker.reload('a')
        capture.findChild(QtWidgets.QPushButton, 'capture_sample_library').click()
        wait(lambda: page.job is None)
        assert window.tabs.currentWidget() is page and page.writer.text() == 'a'
        assert page.table.topLevelItemCount() == 2
        first, second = (page.table.topLevelItem(i) for i in range(2))
        assert [first.text(i) for i in (1, 2)] == ['1', '2']
        assert first.childCount() == 0 and first.isSelected()
        assert page.catalog_count.text() == '2 字 · 3 份'
        assert page.variants.count() == 2 and page.preview.value['sample_id'] == 'one'
        page.variants.setCurrentRow(1)
        assert page.preview.value['sample_id'] == 'two'
        assert page.source_fields['task'].text() == 'later'
        assert '2026-01-01' in page.source_fields['time'].text() or '2025-12-31' in page.source_fields['time'].text()
        assert not page.technical_panel.isVisible()
        page.technical_button.click()
        assert page.technical_panel.isVisible() and page.technical_fields['writer'].text() == 'a'
        page.technical_button.click()
        assert not page.selected_samples()
        page.compare_button.click()
        assert page.compare_preview.value['sample_id'] == 'one'
        assert page.preview.size() == page.compare_preview.size()
        assert page.preview.fit_span == page.compare_preview.fit_span == (20, 70)
        page.guides.click()
        assert not page.preview.guides and not page.compare_preview.guides
        page.compare_button.click()

        QtTest.QTest.mouseClick(page.table.viewport(), QtCore.Qt.LeftButton, pos=page.table.visualRect(page.table.indexFromItem(second, 0)).center())
        assert page.table.currentItem() is first
        assert [row.sample_id for row in page.selected_samples()] == ['three']
        page.clear_button.click()
        app.processEvents()
        alternate = page.variants.model().index(0, 0)
        check = page.variants.itemDelegate().check_rect(page.variants, alternate)
        assert check.isValid()
        QtTest.QTest.mouseClick(page.variants.viewport(), QtCore.Qt.LeftButton, pos=check.center())
        assert page.preview.value['sample_id'] == 'two'
        assert [row.sample_id for row in page.selected_samples()] == ['one']
        page.clear_button.click()

        page.category.setCurrentIndex(page.category.findData('punctuation'))
        assert page.table.topLevelItemCount() == 0
        page.category.setCurrentIndex(0)
        page.task.setText('earlier')
        assert page.table.topLevelItem(0).text(2) == '1'
        page.task.clear()
        page.character.setText('U+0031')
        assert page.table.topLevelItemCount() == 1
        page.variants.setCurrentRow(1)
        QtTest.QTest.keyClick(page.variants, QtCore.Qt.Key_Space)
        page.variants.setCurrentRow(0)
        assert [row.sample_id for row in page.selected_samples()] == ['two']
        page.task.setText('earlier')
        assert page.selection_summary() == (1, 1)
        assert '当前筛选之外' in page.selection_count.text()
        assert page.single_check.isVisible()
        assert not page.compare_button.isVisible()
        output = root / 'one.inkcapture'
        QtWidgets.QFileDialog.getSaveFileName = lambda *_: (str(output), '')
        export_prompts = []
        def export_question(_, title, message, *_args):
            export_prompts.append((title, message))
            return QtWidgets.QMessageBox.Yes
        QtWidgets.QMessageBox.question = export_question
        page.export_button.click()
        wait(lambda: page.job is None)
        assert '1 份在当前筛选之外' in export_prompts[0][1]
        assert [item.row.sample_id for item in open_bundle(output).samples] == ['two']
        page.task.clear()
        assert page.select_button.checkState() == QtCore.Qt.PartiallyChecked
        page.select_button.click()
        assert {row.sample_id for row in page.selected_samples()} == {'one', 'two'}
        all_output = root / 'both.inkcapture'
        QtWidgets.QFileDialog.getSaveFileName = lambda *_: (str(all_output), '')
        page.export_button.click()
        wait(lambda: page.job is None)
        assert len(open_bundle(all_output).samples) == 2

        page.writer.setText('b')
        wait(lambda: page.job is None)
        assert not page.selected_samples() and not page.export_button.isEnabled()
        page.writer.setText('a')
        wait(lambda: page.job is None)
        assert len(page.selected_samples()) == 2
        page.writer.setText('b')
        wait(lambda: page.job is None)
        confirmations = []
        def confirm(box):
            confirmations.append(box.text())
            buttons = QtWidgets.QMessageBox.StandardButton
            return buttons.Yes if box.button(buttons.Yes) else buttons.Close
        QtWidgets.QMessageBox.exec = confirm
        QtWidgets.QFileDialog.getOpenFileName = lambda *_: (str(output), '')
        page.pick_import(False)
        wait(lambda: page.job is None and len(confirmations) == 1)
        assert '新增 1 · 重复 0 · 冲突 0' in confirmations[0]
        assert '目标书写者 b（b）' in confirmations[0]
        assert page.preview.value['sample_id'] == 'two'
        assert page.source_fields['writer'].text() == 'b'
        assert page.source_fields['origin'].text() == '导入样本'
        assert page.technical_fields['writer'].text() == 'a'
        page.pick_import(False)
        wait(lambda: page.job is None and len(confirmations) == 2)
        assert '新增 0 · 重复 1 · 冲突 0' in confirmations[1]
        window.editor.dirty = False
        assert window.close()
    '''
    proc = subprocess.run([sys.executable, '-B', '-c', textwrap.dedent(code), str(tmp_path)],
                          env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
    assert proc.returncode == 0, proc.stdout + proc.stderr
