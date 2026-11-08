import os
import subprocess
import sys


def test_crashed_optional_process_retries_same_request_on_cpu(tmp_path):
    program = r'''
import sys,time,threading
from pathlib import Path
from PySide6 import QtWidgets,QtCore,QtTest
from inkstruct.global_defaults import GlobalDefaultsStore
from inkstruct.editor import preview_process as module
app=QtWidgets.QApplication([]);root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
s=GlobalDefaultsStore.make_settings();s.setValue('preview_backend_v1','gpu');s.sync()
original=module.worker_command;calls=[]
def command(directory):
 calls.append(1)
 return [sys.executable,'-c','raise SystemExit(9)'] if len(calls)==1 else original(directory)
module.worker_command=command
p=module.PreviewProcess();token,path=p.prepare_path()
path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M1 1L9 9" stroke="black"/></svg>')
done=[];p.completed.connect(done.append)
request={'token':token,'spec':(20,20,1.5),'tiles':((-1,-1),),'cancel_event':threading.Event(),'images':[]}
p.render(request,request['tiles'])
end=time.monotonic()+15
while not done and time.monotonic()<end:app.processEvents();QtTest.QTest.qWait(10)
assert len(done)==1 and 'error' not in done[0],done
assert p.backend=='cpu' and p.retried and p.fallback_reason and len(done[0]['images'])==1
assert done[0]['images'][0][1].size()==QtCore.QSize(30,30)
p.close()
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', program, str(tmp_path)],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True,
                            timeout=25, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
