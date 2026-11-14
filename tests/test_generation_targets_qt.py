import os
import subprocess
import sys


def test_target_controls_load_and_capture_without_modifying_document(tmp_path):
    code = r'''
from pathlib import Path
import sys,time
from PySide6 import QtWidgets
from inkstruct.desktop import main
from inkstruct.document.styles import FlowStyle
from inkstruct.generation_targets import target_manifest
app=QtWidgets.QApplication([])
w=main(['test'],create_only=True,workspace=Path(sys.argv[1]),database=Path('artifacts/structures/characters.sqlite3'))
f=w.centralWidget()
from inkstruct.generation_parallel import WORKER_PRESETS
assert f.parallelism.currentData()=='auto'
assert [f.parallelism.itemData(i) for i in range(f.parallelism.count())] == ['auto', 1, *WORKER_PRESETS, 'max']
f.method.setCurrentIndex(f.method.findData('v631'))
assert not f.same_character.isHidden() and f.same_character.isChecked()
assert f.candidate_limit.isEnabled()
assert not f.target_current_button.isEnabled()
source='孔正孔 $U_{正}=1$ [止](https://example.org/网址)'
f.current_document_provider=lambda:(source,FlowStyle(),{'document_id':'unchanged','revision':4})
f.refresh();assert f.target_current_button.isEnabled()
f.choose_current_document()
end=time.monotonic()+8
while f.busy and time.monotonic()<end:app.processEvents();time.sleep(.01)
assert not f.busy and f.target_manifest['requested']==list('孔正止'),f.log.toPlainText()
assert f.target_manifest['source']['identity']=={'document_id':'unchanged','revision':4}
assert f.current_document_provider()[0]==source
f.load_targets(lambda supported:target_manifest('孔正'*20000,['孔','正']))
end=time.monotonic()+8
while f.busy and time.monotonic()<end:app.processEvents();time.sleep(.01)
assert f.target_manifest['requested']==list('孔正')
assert '目标 2 字' in f.target_summary.text()
assert not hasattr(f,'text') and not hasattr(f,'generate_all')
f.method.setCurrentIndex(f.method.findData('v4'))
assert not f.parallelism.isEnabled() and f.same_character.isHidden()
QtWidgets.QFileDialog.getOpenFileName=lambda *a:('','')
before=f.target_manifest;f.choose_target_file();assert f.target_manifest is before
QtWidgets.QApplication.processEvents()
f.close();w.hide()
'''
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
