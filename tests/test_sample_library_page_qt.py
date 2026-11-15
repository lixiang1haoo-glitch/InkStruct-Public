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

        from PySide6 import QtCore, QtWidgets

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
            write(catalog, 'symbol', 'a', {**specimen(char, identity), 'writer_id': 'a',
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
        assert page.table.topLevelItem(0).text(1) == '2 份'
        assert page.variants.count() == 2 and page.preview.value['sample_id'] == 'one'
        page.variants.setCurrentIndex(1)
        assert page.preview.value['sample_id'] == 'two'
        assert '原始任务 later' in page.details.toPlainText()
        assert '原书写者 a' in page.details.toPlainText()
        assert '录制时间 2026-01-01' in page.details.toPlainText()

        page.category.setCurrentIndex(page.category.findData('punctuation'))
        assert page.table.topLevelItemCount() == 0
        page.category.setCurrentIndex(0)
        page.task.setText('earlier')
        assert page.table.topLevelItem(0).text(1) == '1 份'
        page.task.clear()
        page.character.setText('U+0031')
        assert page.table.topLevelItemCount() == 1
        group = page.table.topLevelItem(0)
        group.setExpanded(True)
        group.child(1).setSelected(True)
        page.variants.setCurrentIndex(0)
        assert [row.sample_id for row in page.selected_samples()] == ['two']
        output = root / 'one.inkcapture'
        QtWidgets.QFileDialog.getSaveFileName = lambda *_: (str(output), '')
        page.export_button.click()
        wait(lambda: page.job is None)
        assert [item.row.sample_id for item in open_bundle(output).samples] == ['two']
        page.table.collapseAll()
        page.select_button.click()
        assert {row.sample_id for row in page.selected_samples()} == {'one', 'two'}
        all_output = root / 'both.inkcapture'
        QtWidgets.QFileDialog.getSaveFileName = lambda *_: (str(all_output), '')
        page.export_button.click()
        wait(lambda: page.job is None)
        assert len(open_bundle(all_output).samples) == 2

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
        assert '库内书写者 b' in page.details.toPlainText()
        assert '原书写者 a' in page.details.toPlainText()
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
