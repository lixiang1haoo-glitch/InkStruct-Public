import common as b
import os
import subprocess

scope=b.OUT/'cpu-test-scope';scope.mkdir(exist_ok=False)
env=dict(os.environ,QT_QPA_PLATFORM='offscreen',INKSTRUCT_TEST_CPU_SCOPE=str(scope),
         PYTHONPATH=os.pathsep.join((str(b.ROOT/'scripts/editor_architecture/cpu_scope'),os.environ['PYTHONPATH'])))
command=[str(b.ROOT/'.venv/Scripts/python.exe'),'-B','-X','utf8','-m','pytest',
         'tests/test_continuous_preview_qt.py','-k','tiling','-ra','--basetemp',str(b.OUT/'retest-tmp')]
with (b.OUT/'cpu-isolated-retest.log').open('xb') as file:
    result=subprocess.run(command,cwd=b.ROOT,env=env,stdout=file,stderr=subprocess.STDOUT)
b.save('cpu-isolated-retest-command.json',{'command':command,'settings_scope':str(scope),'exit_code':result.returncode})
raise SystemExit(result.returncode)
