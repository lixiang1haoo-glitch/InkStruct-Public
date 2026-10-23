"""All timed native trials are sequential, logged and never overwritten."""
import bootstrap as b
import os
import json
import subprocess
import sys
import time

def run(variant,backend,rep,flags=()):
    suffix='-open' if '--open-only' in flags else '-edit' if '--edit-only' in flags else ''
    name=f'{variant}-{backend}{suffix}-{rep}';path=b.OUT/(name+'.log')
    if path.exists():raise FileExistsError(path)
    command=[sys.executable,'scripts/gpu_raster_followup/preview.py',variant,backend,str(rep),*flags]
    started=time.perf_counter()
    with path.open('w',encoding='utf-8') as f:p=subprocess.run(command,cwd=b.ROOT,env=os.environ.copy(),stdout=f,stderr=subprocess.STDOUT)
    b.save(name+'.command.json',{'command':command,'exit_code':p.returncode,'wall_s':time.perf_counter()-started})
    print(name,p.returncode,flush=True)
    if p.returncode:raise RuntimeError(name)
    measured=json.loads((b.OUT/f'preview-{name}.json').read_text(encoding='utf-8'))
    if 'error' in measured or measured['foreground_fraction']!=1:
        raise RuntimeError('invalid native foreground trial: '+name)

if sys.argv[1]=='pilot':
    for variant,backend in [('old-external-steady','cpu'),('cached-external-prewarm-steady','gpu-raster')]:run(variant,backend,2)
elif sys.argv[1]=='native':
    pairs=[('old-external','cpu'),('old-external-steady','cpu'),('cpu-external-prewarm-steady','gpu-raster'),('correct-external-prewarm-steady','gpu-raster'),('cached-external-prewarm-steady','gpu-raster')]
    for rep in (3,4,5):
        for variant,backend in (pairs if rep%2 else list(reversed(pairs))):run(variant,backend,rep)
elif sys.argv[1]=='open':
    pairs=[('old-external','cpu'),('old-external-prewarm','cpu'),('cpu-external-prewarm-steady','gpu-raster'),('correct-external-prewarm-steady','gpu-raster'),('cached-external-prewarm-steady','gpu-raster')]
    for rep in (6,7,8):
        for variant,backend in (pairs if rep%2 else list(reversed(pairs))):run(variant,backend,rep,('--open-only',))
elif sys.argv[1]=='edit':
    pairs=[('old-external-steady','cpu'),('cpu4-external-prewarm-steady','gpu-raster'),('cached4-external-prewarm-steady','gpu-raster')]
    for rep in (9,10,11):
        for variant,backend in (pairs if rep%2 else list(reversed(pairs))):run(variant,backend,rep,('--edit-only',))
elif sys.argv[1]=='scheduler':
    pairs=[('old-external','gpu-raster'),('old-external-steady','gpu-raster')]
    for rep in (12,13,14):
        for variant,backend in (pairs if rep%2 else list(reversed(pairs))):run(variant,backend,rep)
elif sys.argv[1]=='capacity':
    pairs=[('cpu4-external-prewarm-steady','gpu-raster'),('cached-external-prewarm-steady','gpu-raster'),('cached4-external-prewarm-steady','gpu-raster')]
    for rep in (15,16,17):
        for variant,backend in (pairs if rep%2 else list(reversed(pairs))):run(variant,backend,rep)
elif sys.argv[1]=='foreground-followup':
    pairs=[('cpu4-external-prewarm-steady','gpu-raster'),('cached-external-prewarm-steady','gpu-raster'),('cached4-external-prewarm-steady','gpu-raster')]
    for rep in (18,19,20):
        for variant,backend in (pairs if rep%2 else list(reversed(pairs))):run(variant,backend,rep)
    pairs=[('old-external-steady','cpu'),('cpu4-external-prewarm-steady','gpu-raster'),('cached4-external-prewarm-steady','gpu-raster')]
    for rep in (21,22,23):
        for variant,backend in (pairs if rep%2 else list(reversed(pairs))):run(variant,backend,rep,('--edit-only',))
