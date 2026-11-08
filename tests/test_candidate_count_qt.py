"""User candidate counts persist privately and are captured before worker dispatch."""
import os
import subprocess
import sys

PROGRAM = r'''
import os, sys
from pathlib import Path
root = Path(sys.argv[1])
os.environ['INKSTRUCT_LAYOUT_PREVIEW_HOME'] = str(root / 'private')
sys.path.insert(0, str(Path.cwd() / 'packaging'))
from inkstruct_layout_launcher import configure_preview
configure_preview()
os.environ.pop('INKSTRUCT_LAYOUT_PREVIEW', None)
from PySide6 import QtCore, QtTest, QtWidgets
from inkstruct.desktop import main
from inkstruct.generation_variants import DEFAULT_CANDIDATES, MAX_CANDIDATES
from inkstruct.generation_workflow import GenerationWorkflow

GenerationWorkflow.readiness = lambda *args: {
    'start': True, 'message': 'private fixture ready'}
calls = []
def generate(*args, **kwargs):
    calls.append((args, kwargs))
    return {'completed_count': 0, 'failed_count': 0}
GenerationWorkflow.generate = generate
app = QtWidgets.QApplication([])
if sys.argv[2] == 'invalid':
    settings = QtCore.QSettings('InkStruct', 'Generation')
    settings.setValue('candidate_limit', 'invalid')
    settings.sync()
w = main(['check'], create_only=True, workspace=root / 'workspace', database=root / 'no-db')
w.show()
app.processEvents()
f = w.centralWidget()
count = f.candidate_limit
assert count.minimum() == 1 and count.maximum() == MAX_CANDIDATES == 64
assert count.objectName() == 'generation_candidate_limit'
if sys.argv[2] == 'restore':
    assert count.value() == 8 and '32' in f.candidate_hint.text()
elif sys.argv[2] == 'invalid':
    assert count.value() == DEFAULT_CANDIDATES == 4
else:
    assert count.value() == DEFAULT_CANDIDATES == 4
    # A free integer is editable, including a value outside the example choices.
    count.setValue(23)
    assert '92' in f.candidate_hint.text()
    count.setFocus()
    count.lineEdit().selectAll()
    QtTest.QTest.keyClicks(count.lineEdit(), '8')
    QtTest.QTest.keyClick(count, QtCore.Qt.Key_Tab)
    app.processEvents()
    assert count.value() == 8 and '32' in f.candidate_hint.text()
    f.busy = True
    f.refresh()
    assert not count.isEnabled() and count.value() == 8
    f.busy = False
    f.refresh()
    assert count.isEnabled()
    for method in ('v61', 'v4'):
        f.method.setCurrentIndex(f.method.findData(method))
        assert not count.isEnabled() and count.value() == 1
        assert '只保留 1 份' in f.candidate_hint.text()
    f.method.setCurrentIndex(f.method.findData('v62'))
    assert count.isEnabled() and count.value() == 8
    from inkstruct.generation_targets import target_manifest
    f.completed({'message':'已选字表','target_manifest':target_manifest('孔正','孔正')})
    pending = []
    f.submit = lambda function, **kwargs: pending.append(function)
    f.do_generate()
    count.setValue(12)
    pending.pop()()
    assert calls[-1][1]['candidate_limit'] == 8
    for method in ('v61', 'v4'):
        f.method.setCurrentIndex(f.method.findData(method))
        f.do_generate()
        pending.pop()()
        assert calls[-1][1]['candidate_limit'] == 1
    f.method.setCurrentIndex(f.method.findData('v62'))
    count.setValue(1)
    assert '不尝试额外成品' in f.candidate_hint.text()
    count.setValue(MAX_CANDIDATES)
    assert '256' in f.candidate_hint.text()
    count.setValue(8)
    f.candidate_preferences.sync()
w.close()
app.processEvents()
QtCore.QThreadPool.globalInstance().waitForDone()
'''


def test_candidate_count_input_preferences_method_lock_and_dispatch(tmp_path):
    for stage in ("write", "restore", "invalid"):
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", PROGRAM, str(tmp_path), stage],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        assert result.returncode == 0, stage + "\n" + result.stdout + result.stderr
