"""Sequential measured trials: never overlap our preview and candidate workloads."""
import bootstrap as b
import os
import subprocess
import sys
import time

def run(args,name):
    path=b.OUT/(name+'.log')
    if path.exists():raise FileExistsError(path)
    command=[sys.executable,*args];start=time.perf_counter()
    with path.open('w',encoding='utf-8') as f:
        p=subprocess.run(command,cwd=b.ROOT,env=os.environ.copy(),stdout=f,stderr=subprocess.STDOUT)
    b.save(name+'.command.json',{'command':command,'exit_code':p.returncode,'elapsed_s':time.perf_counter()-start})
    print(name,p.returncode,flush=True)
    if p.returncode:raise RuntimeError(name)

if sys.argv[1]=='edit':
    for rep in (1,2,3):
        for backend in (('cpu','gpu-raster') if rep%2 else ('gpu-raster','cpu')):
            run(['scripts/gpu_experiment/preview.py',backend,str(rep),'--edit-only'],f'preview-{backend}-edit-{rep}')
elif sys.argv[1]=='engine':
    run(['scripts/gpu_experiment/preview.py','gpu','11'],'preview-gpu-11')
elif sys.argv[1]=='open':
    for rep in (4,5,6):
        for backend in (('cpu','gpu-raster') if rep%2 else ('gpu-raster','cpu')):
            run(['scripts/gpu_experiment/preview.py',backend,str(rep),'--open-only'],f'preview-{backend}-open-{rep}')
elif sys.argv[1]=='cold':
    for rep in (1,2,3):run(['scripts/gpu_experiment/cold_fit.py',str(rep)],f'cold-fit-{rep}')
elif sys.argv[1]=='preview':
    for rep in (8,9,10):
        order=('cpu','gpu','gpu-raster') if rep%2==0 else ('gpu-raster','gpu','cpu')
        for backend in order:run(['scripts/gpu_experiment/preview.py',backend,str(rep)],f'preview-{backend}-{rep}')
elif sys.argv[1]=='pipeline':
    for rep in (1,2,3):
        for backend in (('cpu','gpu') if rep%2 else ('gpu','cpu')):
            run(['scripts/gpu_experiment/candidates.py',backend,str(rep)],f'pipeline-{backend}-{rep}')
