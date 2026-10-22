"""Desktop method contract and readiness boundaries, independent of private archives."""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from inkstruct.generation_workflow import METHODS, VERSION, GenerationWorkflow, write
from inkstruct.samples import sha256_file


def test_missing_index_and_method_specific_state_do_not_enable_generation(tmp_path):
    source = tmp_path / 'samples'
    source.mkdir()
    db = tmp_path / 'structure'
    db.write_bytes(b'db')
    flow = GenerationWorkflow(tmp_path/'work', db)
    assert list(METHODS) == ['v62', 'v61', 'v4']
    ready = flow.readiness('alice', str(source), 'v4')
    assert ready['import'] and not ready['profile'] and not ready['generate']
    with pytest.raises(ValueError, match='导入'):
        flow.build_profile('alice', str(source), 'v4')
    assert not flow.readiness('../other', str(source), 'v4')['import']
    index = tmp_path/'index.jsonl'
    index.write_text('{}\n')
    profile = tmp_path/'profile.json'
    profile.write_text('{}')
    state = {'import': {'index': str(index), 'index_sha256': sha256_file(index), 'accepted_count': 1},
             'profiles': {'v4': {'path': str(profile), 'workflow_version': VERSION,
                                'index_sha256': sha256_file(index)}}}
    write(flow.state_path('alice', source), state)
    assert flow.readiness('alice', str(source), 'v4')['generate']
    assert not flow.readiness('alice', str(source), 'v61')['generate']
    index.unlink()
    assert not flow.readiness('alice', str(source), 'v4')['generate']
    assert not flow.readiness('alice', str(source), 'v4')['profile']


def test_import_is_immutable_and_invalidates_profiles(tmp_path):
    source = tmp_path/'samples'
    source.mkdir()
    sample = {'schema_version':'handwriting_single_v1', 'sample_id':'one', 'writer_id':'alice',
              'character':'一', 'capture':{'canvas_width':100,'canvas_height':100},
              'strokes':[{'points':[{'x':20,'y':30,'pressure':.4,'t_ms':0},
                                   {'x':80,'y':30,'pressure':.5,'t_ms':50}]}]}
    (source/'one.json').write_text(json.dumps(sample))
    flow = GenerationWorkflow(tmp_path/'work', tmp_path/'no-db')
    flow.import_samples('alice', str(source), 'v4')
    state = flow.state('alice', source)
    old = Path(state['import']['index'])
    before = old.read_bytes()
    state['profiles'] = {'v4': {'pretend': 'old'}}
    write(flow.state_path('alice', source), state)
    flow.import_samples('alice', str(source), 'v4')
    new = flow.state('alice', source)
    assert new['import']['index'] != str(old) and old.read_bytes() == before
    assert not new['profiles']


def test_verified_helpers_have_not_changed_algorithm():
    def functions(path):
        tree = ast.parse(Path(path).read_text(encoding='utf-8'))
        return {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)}
    app = functions('src/inkstruct/generation_v61_helpers.py')
    for path, names in [('scripts/run_v61_author_strokes.py',['plan_sources','hybrid','check_sources']),
                        ('scripts/generate_v61_corrected_library.py',['source_audit','compact_sources'])]:
        source = functions(path)
        for name in names:
            assert app[name] == source[name]


def test_ui_default_readiness_and_error_has_no_traceback(tmp_path):
    code = r'''
from pathlib import Path
import sys,time
from PySide6 import QtCore, QtWidgets
from inkstruct.desktop import main
app=QtWidgets.QApplication([])
w=main(['check'], create_only=True, workspace=Path(sys.argv[1]), database=Path(sys.argv[1])/'no-db')
f=w.centralWidget()
assert f.method.count()==3 and f.method.currentData()=='v62'
assert not f.import_button.isEnabled() and not f.profile_button.isEnabled() and not f.generate_button.isEnabled()
assert not hasattr(f,'trajectory_mode') and not hasattr(f,'source_profile')
assert 'CUDA' not in ''.join(x.text() for x in f.findChildren(QtWidgets.QLabel))
f.do_profile()
end=time.monotonic()+5
while f.busy and time.monotonic()<end:
    app.processEvents();time.sleep(.01)
assert not f.busy
assert 'Traceback' not in f.log.toPlainText()
assert '目录' in f.log.toPlainText()
assert not f.generate_button.isEnabled()
f.method.setCurrentIndex(1)
fresh=main(['check'], create_only=True, workspace=Path(sys.argv[1]))
assert fresh.centralWidget().method.currentData()=='v62'
QtCore.QThreadPool.globalInstance().waitForDone()
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], env={**os.environ,'QT_QPA_PLATFORM':'offscreen'}, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
