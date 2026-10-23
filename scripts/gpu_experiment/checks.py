import bootstrap as b
import os
import subprocess
import sys
import time

command=[str(b.ROOT/'.venv/Scripts/python.exe'),'-m','pytest',
    'tests/test_continuous_preview_qt.py','tests/test_preview_process.py',
    'tests/test_preview_serialization.py','tests/test_document_package.py',
    'tests/test_plotter.py','tests/test_v62_semantics.py',
    '-p','no:cacheprovider','--basetemp',str(b.OUT/'tmp/pytest-baseline')]
env={**os.environ,'QT_QPA_PLATFORM':'offscreen','PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
start=time.perf_counter()
with (b.OUT/'regression.log').open('w',encoding='utf-8') as f:r=subprocess.run(command,cwd=b.ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
b.save('regression.command.json',{'command':command,'exit_code':r.returncode,'seconds':time.perf_counter()-start})
print('regression',r.returncode,flush=True)
raise SystemExit(r.returncode)
