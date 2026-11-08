"""Extra cold-start repetitions, regression, font and frozen harness checks."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from generation_parallel import OUT,ROOT,save
from generation_followup import run


def command(args,label,env=None):
    tick=time.perf_counter()
    with (OUT/(label+'.log')).open('x',encoding='utf-8') as stream:
        result=subprocess.run(args,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env=env)
    save(OUT/(label+'.command.json'),{'command':list(map(str,args)),'returncode':result.returncode,'wall_s':time.perf_counter()-tick})
    print(label,result.returncode,flush=True)
    if result.returncode:raise RuntimeError(label)


def main():
    start=time.monotonic()
    while not (OUT/'followup-complete.json').exists() or (OUT/'foreground-session.flag').exists():
        if time.monotonic()-start>1800:raise TimeoutError('prior measurements have not completed')
        time.sleep(3)
    for repeat in (2,3):
        for mode,workers in [('serial',1),('process',2),('process',4)]:
            label=f'quiet-representative-{mode}{workers}-{repeat}'
            run('generation_parallel.py',['trial','--mode',mode,'--workers',str(workers),'--set','representative','--label',label,'--rounds','2'],label)
    run('generation_parallel.py',['compare'],'comparison-sealed')
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')
    command([sys.executable,'-B','-X','utf8','-m','pytest','tests/test_v62_semantics.py','tests/test_generation_workflow.py',
             'tests/test_font_revisions.py','tests/test_parallel_font_verify.py','-q','-p','no:cacheprovider',
             '--basetemp',str(OUT/'pytest-temp'),'--junitxml',str(OUT/'regression.xml')],'regression',env)
    run('generation_font_check.py',[],'font-check')
    command([sys.executable,'-B','-X','utf8','-m','PyInstaller','--name','GenerationSpawnProbe','--onedir','--console',
             '--paths',str(ROOT/'src'),'--hidden-import','inkstruct.generation_workflow',
             '--hidden-import','statistics','--hidden-import','inspect','--hidden-import','sqlite3',
             '--distpath',str(OUT/'frozen-probe-dist'),'--workpath',str(OUT/'frozen-probe-work'),
             '--specpath',str(OUT/'frozen-probe-spec'),str(ROOT/'scripts/experiments/generation_spawn_probe.py')],'frozen-build')
    executable=OUT/'frozen-probe-dist/GenerationSpawnProbe/GenerationSpawnProbe.exe'
    command([str(executable),str(ROOT),str(OUT/'frozen-probe-run')],'frozen-run')
    save(OUT/'final-checks-complete.json',{'passed':True})


if __name__=='__main__':main()
