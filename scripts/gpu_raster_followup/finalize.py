"""Verify preservation, archive new experiment, remove only its rebuildable caches."""
import bootstrap as b
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def read(path):return json.loads(path.read_text(encoding='utf-8'))

checks={};failures=[]
for name,manifest,absolute,structured in [
    ('source_workspace_inputs',b.OUT/'preservation-before.json',False,True),
    ('previous_experiments_and_docs',b.OUT/'previous-work-before.json',False,False),
    ('historical_user_data',b.ROOT/'artifacts/v62_0.1.32_20261020/user-data-before.json',True,False)]:
    records=read(manifest);bad=[]
    for rel,record in records.items():
        path=Path(rel) if absolute else b.ROOT/rel
        expected=record['sha256'] if structured else record
        try:
            if sha(path)!=expected:bad.append({'path':str(path),'reason':'hash changed'})
        except OSError as error:bad.append({'path':str(path),'reason':str(error)})
    checks[name]={'count':len(records),'unchanged':len(records)-len(bad),'failures':bad}
    failures.extend(bad);print(name,len(records),'failures',len(bad),flush=True)

for label,python,baseline in [
    ('application',b.ROOT/'.venv/Scripts/python.exe',b.ROOT/'artifacts/gpu_benefit_20261020/app-environment-before.txt'),
    ('experiment',Path(sys.executable),b.OUT/'app-environment-before.txt')]:
    r=subprocess.run([str(python),'-m','pip','freeze'],capture_output=True,env=os.environ.copy(),check=True)
    target=b.OUT/f'{label}-environment-after.txt';target.write_bytes(r.stdout+r.stderr)
    equal=target.read_bytes()==baseline.read_bytes();checks[label+'_environment_unchanged']=equal
    if not equal:failures.append({'path':str(python),'reason':'environment differs from baseline'})

version=__import__('inkstruct.fonts',fromlist=['APP_VERSION']).APP_VERSION
assert version=='0.1.32'
checks['app_version']=version
for label,command in [('status',['git','status','--short']),('head',['git','rev-parse','HEAD'])]:
    r=subprocess.run(command,cwd=b.ROOT,capture_output=True,check=True)
    (b.OUT/f'git-{label}-after.txt').write_bytes(r.stdout+r.stderr)
b.save('preservation-after.json',checks)
if failures:raise RuntimeError(f'{len(failures)} preservation discrepancies; see preservation-after.json')

archive=b.OUT/'gpu-raster-followup-source.zip'
sources=[p for p in (b.ROOT/'scripts/gpu_raster_followup').glob('*.py')]
sources.append(b.ROOT/'docs/GPU_RASTER_FOLLOWUP_WINDOWS_20261020.md')
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
    for p in sorted(sources):z.write(p,p.relative_to(b.ROOT))

removed=[]
for path in (b.OUT/'tmp',b.OUT/'mpl-cache',b.ROOT/'scripts/gpu_raster_followup/__pycache__'):
    resolved=path.resolve()
    assert resolved.is_relative_to(b.OUT.resolve()) or resolved==b.ROOT/'scripts/gpu_raster_followup/__pycache__'
    if resolved.exists():shutil.rmtree(resolved);removed.append(str(path.relative_to(b.ROOT)))

manifest={str(p.relative_to(b.OUT)):sha(p) for p in sorted(b.OUT.rglob('*')) if p.is_file() and p.name!='seal.json'}
b.save('seal.json',{'source_sha256':{str(p.relative_to(b.ROOT)):sha(p) for p in sources},
                   'artifact_sha256':manifest,'removed_rebuildable_caches':removed,
                   'application_version':version,'formal_build':False,'new_dependencies':False})
print('sealed',len(manifest),'artifacts; preserved all baseline hashes; no application build',flush=True)
