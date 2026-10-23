"""PDF deadlines and cancellation terminate actual child processes, not just stale jobs."""

import os
import subprocess
import sys

import pytest
from test_template_pdf import make_pdf


def run_program(tmp_path, program):
    pytest.importorskip("PySide6.QtPdf")
    path = tmp_path / "参考.pdf"
    make_pdf(path)
    setup = r"""
import sys,time,json,os
from pathlib import Path
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.editor import template_pdf_process as module
from inkstruct.editor.template_pdf import PdfReferenceDialog
from inkstruct.document.template_authoring import new_template
app=QtWidgets.QApplication([])
path=Path(sys.argv[1]);original=path.read_bytes()
def wait(predicate):
    end=time.monotonic()+8
    while not predicate() and time.monotonic()<end:
        app.processEvents();QtTest.QTest.qWait(5)
    assert predicate()
"""
    result = subprocess.run(
        [sys.executable, "-c", setup + program, str(path)],
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_gui_open_and_render_cancel_are_responsive_and_reaped(tmp_path):
    run_program(
        tmp_path,
        r"""
real=module.worker_command
# The service answers open, then deliberately stalls rendering.
code="import sys,json,time; r=json.loads(sys.stdin.readline()); print(json.dumps({'ok':True,'result':{'action':'open','page_count':2,'source_sha256':'a'*64}}),flush=True); sys.stdin.readline(); time.sleep(20)"
module.worker_command=lambda:[sys.executable,'-c',code]
ticks=[]
clock=QtCore.QTimer();clock.setInterval(10);clock.timeout.connect(lambda:ticks.append(1));clock.start()
d=PdfReferenceDialog(path,new_template(),'first');d.show()
wait(lambda:d.page_count==2 and len(ticks)>5)
assert d.pdf.pending and d.candidate is None
assert not d.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
assert d.pdf.process.processId()>0
start=time.monotonic();d.reject()
assert time.monotonic()-start<1.5 and d.pdf.closed
assert d.pdf.process.state()==QtCore.QProcess.NotRunning
assert d.result()==QtWidgets.QDialog.Rejected
# Cancel immediately during process startup also cleans up.
e=PdfReferenceDialog(path,new_template(),'first');e.reject()
assert e.pdf.process.state()==QtCore.QProcess.NotRunning
d.deleteLater();e.deleteLater();clock.stop()
assert path.read_bytes()==original
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
""",
    )


@pytest.mark.parametrize("failure", ["timeout", "crash", "oversize", "bad-json"])
def test_process_failure_clears_pending_and_terminates_child(tmp_path, failure):
    programs = {
        "timeout": "import time; time.sleep(20)",
        "crash": "import os; os._exit(9)",
        "oversize": "import sys,time; sys.stdout.write('x'*(4*1024*1024));sys.stdout.flush();time.sleep(20)",
        "bad-json": "import time;print('bad-json',flush=True);time.sleep(20)",
    }
    run_program(
        tmp_path,
        f"module.worker_command=lambda:[sys.executable,'-c',{programs[failure]!r}]\n"
        + r"""
p=module.PdfProcess(timeout_ms=300)
errors=[];results=[]
p.failed.connect(errors.append);p.completed.connect(results.append)
p.request({'action':'open','path':str(path)})
wait(lambda:bool(errors))
assert p.closed and not p.pending and not results
assert p.process.state()==QtCore.QProcess.NotRunning
p.close();assert len(errors)==1
assert path.read_bytes()==original
""",
    )


def test_real_child_uses_frozen_bytes_and_never_applies_stale_page(tmp_path):
    run_program(
        tmp_path,
        r"""
d=PdfReferenceDialog(path,new_template(),'first');d.show()
wait(lambda:d.candidate is not None)
first=d.configuration().first.background.sha256
path.write_bytes(b'changed after opening')
d.page.setValue(2)
assert d.candidate is None and not d.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
# Even a programmatic change while the control is disabled must not apply page 2 to page 1.
d.page.setValue(1)
wait(lambda:d.candidate is not None)
assert d.configuration().first.background.sha256==first
assert d.page.value()==1 and d.pdf.process.processId()>0
d.accept();assert d.pdf.process.state()==QtCore.QProcess.NotRunning
assert path.read_bytes()==b'changed after opening'
d.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
""",
    )


def test_cli_timeout_kills_child_without_creating_output(tmp_path):
    run_program(
        tmp_path,
        r"""
from inkstruct.cli import main
real=module.import_pdf
module.worker_command=lambda:[sys.executable,'-c','import time;time.sleep(20)']
module.import_pdf=lambda request:real(request,timeout=.15)
out=path.with_suffix('.json')
start=time.monotonic()
assert main(['document','template','from-pdf',str(path),'--output',str(out)])==2
assert time.monotonic()-start<2
assert not out.exists() and path.read_bytes()==original
""",
    )
