"""Seal experiment code/environment, check preservation, remove only own caches."""
import bootstrap as b
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

before=json.loads((b.OUT/'preservation-before.json').read_text(encoding='utf-8'))
changes=[name for name,value in before.items() if not (b.ROOT/name).is_file() or sha(b.ROOT/name)!=value['sha256']]
assert not changes,changes
historical=json.loads((b.ROOT/'artifacts/v62_0.1.32_20261020/user-data-before.json').read_text(encoding='utf-8'))
history_changes=[name for name,expected in historical.items() if not Path(name).is_file() or sha(Path(name))!=expected]
assert not history_changes,history_changes
old=(b.OUT/'app-environment-before.txt').read_bytes()
current=subprocess.run([str(b.ROOT/'.venv/Scripts/python.exe'),'-m','pip','freeze'],capture_output=True,check=True)
(b.OUT/'app-environment-after.txt').write_bytes(current.stdout+current.stderr)
assert current.stdout+current.stderr==old
experiment=subprocess.run([str(b.ROOT/'.venv-gpu-experiment/Scripts/python.exe'),'-m','pip','freeze'],capture_output=True,check=True)
(b.OUT/'experiment-environment.txt').write_bytes(experiment.stdout+experiment.stderr)
status=subprocess.run(['git','status','--short'],capture_output=True,check=True)
(b.OUT/'git-status-after.txt').write_bytes(status.stdout)
files=sorted((b.ROOT/'scripts/gpu_experiment').glob('*.py'))+[b.ROOT/'docs/GPU_BENEFIT_WINDOWS_20261020.md']
b.save('experiment-code-sha256.json',{str(p.relative_to(b.ROOT)):sha(p) for p in files})
with zipfile.ZipFile(b.OUT/'experiment-source.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
    for p in files:archive.write(p,str(p.relative_to(b.ROOT)))
b.save('excluded-pilots.json',{'cpu-0':'experimental child process dependency path missing; failed worker, only own matching processes terminated; no performance claim',
    'preview-1-4':'pilots; warm range not fully prewarmed and frame-list capture corrected',
    'preview-5-7':'prewarmed pilots; closed-loop input pace was backend dependent; excluded from final fixed-60-Hz comparison',
    'open-1-3':'earlier theme pilot, final open-4-6 uses production light theme',
    'cuda-probe':'show_config scans optional libraries; excluded from initialization benchmark; cold-fit records are authoritative'})
removed=[]
for path in [b.OUT/'tmp',b.OUT/'mpl-cache',b.OUT/'cupy-cache',*(b.OUT/f'cold-kernel-cache-{i}' for i in (1,2,3)),b.ROOT/'scripts/gpu_experiment/__pycache__']:
    resolved=path.resolve()
    if path==b.ROOT/'scripts/gpu_experiment/__pycache__':resolved.relative_to((b.ROOT/'scripts/gpu_experiment').resolve())
    else:resolved.relative_to(b.OUT.resolve())
    if path.exists():shutil.rmtree(path);removed.append(str(path))
b.save('final-seal.json',{'app_version':'0.1.32','default_source_and_workspace_files_unchanged':len(before),
    'historical_user_data_files_rechecked_unchanged':len(historical),
    'app_environment_freeze_unchanged':True,'new_formal_application_build':False,
    'cleanup_removed_only_owned_rebuildable_caches':removed,'independent_experiment_environment_retained':str(b.ROOT/'.venv-gpu-experiment')})
print('sealed',len(files),'source/report files; app environment and baseline unchanged',flush=True)
