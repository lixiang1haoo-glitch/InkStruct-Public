import common as b
import os
import subprocess

tests=['test_source_identity.py','test_continuation.py','test_suffix_continuation.py',
       'test_footnote_continuation.py','test_flow_templates.py','test_continuous_preview_qt.py',
       'test_glyph_corrections.py','test_document_package.py','test_preview_process.py',
       'test_preview_gpu_recovery_qt.py','test_document_limits.py']
command=[str(b.ROOT/'.venv/Scripts/python.exe'),'-B','-X','utf8','-m','pytest',
         *['tests/'+name for name in tests],'-ra','--basetemp',str(b.OUT/'regression-tmp')]
env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
with (b.OUT/'regression.log').open('xb') as file:
    result=subprocess.run(command,cwd=b.ROOT,stdout=file,stderr=subprocess.STDOUT,env=env)
b.save('regression-command.json',{'command':command,'exit_code':result.returncode,'qt_platform':'offscreen'})
raise SystemExit(result.returncode)
