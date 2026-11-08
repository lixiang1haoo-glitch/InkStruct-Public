import os
import subprocess
import sys


def test_review_dialog_cancel_acknowledgement_and_workflow(tmp_path):
    code = r'''
from pathlib import Path
import sys
from PySide6 import QtCore,QtWidgets
from inkstruct.character_sets_ui import CharacterSetsDialog
from inkstruct.desktop import main
app=QtWidgets.QApplication([])
d=CharacterSetsDialog('孔正一井')
assert not d.accept_button.isEnabled() and d.result_manifest is None
d.checkboxes['cn-tgh-2013'].setChecked(True)
assert not d.accept_button.isEnabled() and not d.acknowledge.isChecked()
assert 'U+' in d.details.toPlainText() and '8105' in d.summary.text()
d.acknowledge.setChecked(True);assert d.accept_button.isEnabled()
d.checkboxes['tw-common-1982'].setChecked(True)
assert not d.acknowledge.isChecked() and not d.accept_button.isEnabled()
d.lookup.setText('发');assert '發' in d.relationship.toPlainText() and '髮' in d.relationship.toPlainText()
d.reject();assert d.result_manifest is None
d.checkboxes['tw-common-1982'].setChecked(False)
d.acknowledge.setChecked(True);d.accept()
assert set(d.result_manifest['requested'])==set('孔正一井')
assert len(d.result_manifest['source']['complete_requested'])==8105
w=main(['check'],create_only=True,workspace=Path(sys.argv[1]),database=Path('artifacts/structures/characters.sqlite3'))
f=w.centralWidget();before=f.target_summary.text()
original=CharacterSetsDialog.exec
CharacterSetsDialog.exec=lambda self:QtWidgets.QDialog.DialogCode.Rejected
f.choose_builtin_targets();assert f.target_summary.text()==before and f.target_manifest is None
def accept(self):
 self.checkboxes['cn-tgh-2013'].setChecked(True)
 self.acknowledge.setChecked(True)
 self.accept()
 return QtWidgets.QDialog.DialogCode.Accepted
CharacterSetsDialog.exec=accept
f.choose_builtin_targets()
assert f.target_manifest['source']['kind']=='builtin-character-sets'
assert f.target_manifest['source']['unsupported_in_structure_library']
assert '已确认排除' in f.target_summary.text()
assert f.target_details_button.isEnabled()
def all_structures(self):
 self.checkboxes['cn-tgh-2013'].setChecked(True)
 self.all_structures.setChecked(True)
 assert not self.selected_ids() and not self.acknowledge.isEnabled()
 assert not self.checkboxes['cn-tgh-2013'].isEnabled()
 self.accept()
 return QtWidgets.QDialog.DialogCode.Accepted
CharacterSetsDialog.exec=all_structures
f.choose_builtin_targets()
assert f.target_manifest['source']['kind']=='all-supported'
assert f.target_manifest['requested'] and not f.target_manifest['unsupported']
assert '结构库全部汉字' in f.target_summary.text()
assert not hasattr(f,'text') and not hasattr(f,'generate_all')
CharacterSetsDialog.exec=original
w.close()
'''
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code, str(tmp_path)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
