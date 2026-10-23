"""Import completion reuses worker summaries; explicit Verify still reads disk."""

import os
import subprocess
import sys


def test_import_metadata_handoff_and_explicit_verification(tmp_path):
    program = r"""
import sys,time,zipfile
from pathlib import Path
from PySide6 import QtCore,QtWidgets
from inkstruct.fonts import ui
from inkstruct.fonts.importer import build_font
from test_font_packages import recorded
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
source=root/'original.inkfont'
build_font(source,writer='fixture',name='test',symbols=recorded(root))
w=ui.FontLibrary(root/'library');w.show();app.processEvents()
QtWidgets.QFileDialog.getOpenFileName=lambda *a,**k:(str(source),'')
errors=[]
QtWidgets.QMessageBox.warning=lambda *a:errors.append(str(a[-1]))
original=ui.FontPackage
def forbidden(*a,**k):raise AssertionError('Main thread re-read imported metadata')
ui.FontPackage=forbidden
w.import_font()
def wait():
    end=time.monotonic()+15
    while w.job is not None and time.monotonic()<end:
        app.processEvents();time.sleep(.002)
    assert w.job is None
    app.processEvents()
wait()
assert not errors,errors
assert w.list.count()==1 and '字体已导入' in w.progress.text()
assert w.selected().read_bytes()==source.read_bytes()
assert len(w.font_entries)==1
assert '斜体 1/52' in w.detail.text()
for _ in range(3):w.refresh();w.describe()
ui.FontPackage=original
destination=w.selected()
with zipfile.ZipFile(destination) as z:
    members={name:z.read(name) for name in z.namelist()}
name=next(n for n in members if n.startswith('glyphs/'))
members[name]+=b' '
with zipfile.ZipFile(destination,'w') as z:
    for name,raw in members.items():z.writestr(name,raw)
damaged=destination.read_bytes()
w.verify();wait()
assert len(errors)==1 and '成员损坏' in errors[0],errors
assert destination.read_bytes()==damaged
w.close();QtCore.QThreadPool.globalInstance().waitForDone()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONPATH": os.pathsep.join(
                filter(None, ["tests", os.environ.get("PYTHONPATH", "")])
            ),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
