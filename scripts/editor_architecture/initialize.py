import common as b
import json
import platform
import subprocess
import sys
import psutil

if (b.OUT/'source-before.json').exists():raise SystemExit('Choose a new experiment directory')
paths=[]
for directory in ('src','tests','scripts','docs','packaging','configs','workspaces','profiles'):
    paths += [p for p in (b.ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
paths += [b.ROOT/name for name in ('AGENTS.md','README.md','pyproject.toml')]
source_hashes={}
source_unreadable=[]
for p in paths:
    try:source_hashes[str(p.relative_to(b.ROOT))]=b.sha(p)
    except OSError as e:
        s=p.stat()
        source_unreadable.append({'path':str(p),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'error':str(e)})
b.save('source-before.json',source_hashes)
b.save('source-unreadable-before.json',source_unreadable)
old=json.loads((b.ROOT/'artifacts/v62_0.1.32_20261020/user-data-before.json').read_text(encoding='utf-8'))
preserve={}
unreadable=[]
for name in [*old,str(b.INPUT),str(b.REAL),str(b.ROOT/'artifacts/integration_0.1.33_20261020/delivery-seal.json')]:
    try:preserve[name]=b.sha(name)
    except OSError as e:unreadable.append({'path':name,'error':str(e)})
library=b.ROOT/'artifacts/windows_release_0.1.33'
for p in library.iterdir():
    if p.is_file():preserve[str(p)]=b.sha(p)
b.save('user-data-before.json',preserve)
b.save('unreadable-before.json',unreadable)
env={
    'python':sys.version,'platform':platform.platform(),'cpu':platform.processor(),
    'logical_cpus':psutil.cpu_count(),'physical_cpus':psutil.cpu_count(logical=False),
    'ram_bytes':psutil.virtual_memory().total,'disk_free':psutil.disk_usage(str(b.ROOT)).free,
    'cpu_total_percent_1s':psutil.cpu_percent(interval=1),
    'processes':[{'pid':p.pid,'name':p.info['name'],'rss':p.info['memory_info'].rss}
                 for p in psutil.process_iter(['name','memory_info']) if p.info['memory_info']],
}
for name,cmd in [('git-status',['git','status','--short']),('git-head',['git','rev-parse','HEAD']),
                 ('nvidia-smi',['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,power.draw','--format=csv']),
                 ('power-plan',['powercfg','/getactivescheme']),
                 ('application-environment',[str(b.ROOT/'.venv/Scripts/python.exe'),'-m','pip','freeze'])]:
    r=subprocess.run(cmd,cwd=b.ROOT,capture_output=True)
    (b.OUT/(name+'.txt')).write_bytes(r.stdout+r.stderr)
    env[name+'_exit']=r.returncode
b.save('environment.json',env)
print('Preserved',len(paths),'source/workspace files and',len(preserve),'historical/input/release files',flush=True)
