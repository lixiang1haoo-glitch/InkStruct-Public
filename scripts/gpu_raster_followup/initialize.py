import bootstrap as b
import hashlib
import json
import runpy

runpy.run_path(str(b.ROOT/'scripts/gpu_experiment/initialize.py'),run_name='__main__')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()
old=b.ROOT/'artifacts/gpu_benefit_20261020'
extra={}
for directory in ('docs','scripts/gpu_experiment','artifacts/gpu_benefit_20261020'):
    for p in (b.ROOT/directory).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:extra[str(p.relative_to(b.ROOT))]=sha(p)
for p in b.ROOT.iterdir():
    if p.is_file():extra[p.name]=sha(p)
b.save('previous-work-before.json',extra)
print('previous work protected',len(extra),flush=True)
