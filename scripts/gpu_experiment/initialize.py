import bootstrap as b
import hashlib
import json
import subprocess
import sys
import shutil
from pathlib import Path

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

manifest={}
for directory in ('src','tests','configs','packaging','workspaces'):
    for p in (b.ROOT/directory).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:
            try:manifest[str(p.relative_to(b.ROOT))]={'size':p.stat().st_size,'sha256':sha(p)}
            except OSError:pass
for rel in ('artifacts/v62_0.1.32_20261020/user-data-before.json',
            'artifacts/v62_0.1.32_20261020/user_001-v62-validation-full-symbols-20261020.inkfont',
            'artifacts/preview_performance_0.1.12_20261018/input.inkdoc',
            'artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json'):
    p=b.ROOT/rel;manifest[rel]={'size':p.stat().st_size,'sha256':sha(p)}
b.save('preservation-before.json',manifest)
commands={'git-status':['git','status','--short'], 'git-head':['git','rev-parse','HEAD'],
          'app-environment':[sys.executable,'-m','pip','freeze'],
          'gpu':['nvidia-smi','-q'], 'vulkan':['vulkaninfo','--summary'],
          'power':['powercfg','/getactivescheme']}
for name,cmd in commands.items():
    r=subprocess.run(cmd,capture_output=True)
    (b.OUT/(name+'-before.txt')).write_bytes(r.stdout+r.stderr)
b.save('host.json',{'python':sys.version,'disk':shutil.disk_usage(b.ROOT)._asdict(),
                    'path':str(b.ROOT),'app_version':__import__('inkstruct.fonts',fromlist=['APP_VERSION']).APP_VERSION})
print('baseline saved',len(manifest),flush=True)
