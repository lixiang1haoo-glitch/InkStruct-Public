"""Sequential second-stage checks; never overlap measured generation loads."""
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from generation_parallel import OUT,ROOT,save


def run(script,args,label):
    command=[sys.executable,'-B','-X','utf8',str(ROOT/'scripts/experiments'/script),*args]
    tick=time.perf_counter()
    with (OUT/(label+'.native.log')).open('x',encoding='utf-8') as stream:
        process=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    save(OUT/(label+'.command.json'),{'command':command,'returncode':process.returncode,'wall_s':time.perf_counter()-tick})
    print(label,process.returncode,flush=True)
    if process.returncode:raise RuntimeError(label)


def main():
    deadline=time.monotonic()+1800
    # Windows restricted process metadata may hide even sibling command lines.
    # Use a completed-final-trial receipt rather than inferring an idle machine.
    while not (OUT/'attribution.command.json').is_file():
        if time.monotonic()>deadline:raise TimeoutError('first suite completion receipt')
        time.sleep(4)
    assert json.loads((OUT/'attribution.command.json').read_text('utf-8'))['returncode']==0
    time.sleep(2)
    assert (OUT/'attribution/measurement.json').is_file(),'first suite did not complete'
    run('generation_target_sets.py',[],'targets-final')
    run('generation_parallel.py',['trial','--label','reverse-order','--rounds','1','--reverse'],'reverse-order')
    for scope in ('mainland','traditional','custom','markdown'):
        for mode,workers in [('serial',1),('process',2)]:
            label=f'scope-{scope}-{mode}'
            run('generation_parallel.py',['trial','--mode',mode,'--workers',str(workers),'--set',scope,'--label',label,'--rounds','3'],label)
    run('generation_parallel.py',['faults'],'faults')
    run('generation_parallel.py',['compare'],'compare-final')
    save(OUT/'followup-complete.json',{'passed':True})


if __name__=='__main__':main()
