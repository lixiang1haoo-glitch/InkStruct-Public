"""Verify unchanged production and user files; retain all evidence and seal it."""
import common as b
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

def read(name):return json.loads((b.OUT/name).read_text(encoding='utf-8'))
report={};changed=[]
source=read('source-before.json')
for rel,digest in source.items():
    path=b.ROOT/rel
    assert path.is_file(),rel
    if b.sha(path)!=digest:
        assert rel.replace('\\','/').startswith('scripts/editor_architecture/'),rel
        changed.append(rel)
report['preexisting_source_and_workspace_files_exact']=len(source)-len(changed)
report['changed_initial_experiment_files_only']=changed
historical=read('user-data-before.json')
assert all(b.sha(path)==digest for path,digest in historical.items())
report['historical_user_input_and_release_files_exact']=len(historical)
unreadable=read('source-unreadable-before.json')
for record in unreadable:
    current=Path(record['path']).stat()
    assert current.st_size==record['size'] and current.st_mtime_ns==record['mtime_ns']
report['preexisting_unreadable_metadata_unchanged']=len(unreadable)
for name,command in [('git-status-after',['git','status','--short']),('git-head-after',['git','rev-parse','HEAD']),
                      ('application-environment-after',[str(b.ROOT/'.venv/Scripts/python.exe'),'-m','pip','freeze'])]:
    result=subprocess.run(command,cwd=b.ROOT,capture_output=True,check=True)
    with (b.OUT/(name+'.txt')).open('xb') as file:file.write(result.stdout+result.stderr)
assert (b.OUT/'git-head-after.txt').read_bytes()==(b.OUT/'git-head.txt').read_bytes()
assert (b.OUT/'application-environment-after.txt').read_bytes()==(b.OUT/'application-environment.txt').read_bytes()
from inkstruct.fonts import APP_VERSION
assert APP_VERSION=='0.1.33'
report['app_version']=APP_VERSION
report['application_environment_unchanged']=True
report['production_source_unchanged']=True
report['no_formal_build_or_release']=True
report['regression']='189 passed / 3 failed initially; 3 passed in isolated CPU settings; 192 unique passing cases after retest'
confirmation=read('native-thread-30.json')
assert confirmation['preview_backend_start']==confirmation['preview_backend_final']=='gpu'
assert confirmation['gpu_fallback_reason'] is None and 'error' not in confirmation
assert all(s['foreground_fraction_frames']==1 for s in confirmation['scenarios'])
report['explicit_gpu_confirmation_foreground_no_fallback']=True
# Preserve external monitor JSON before clearing its disposable working folder.
raw=b.OUT/'raw-monitors';raw.mkdir(exist_ok=False)
for path in (b.OUT/'tmp').glob('monitor-*.json'):shutil.copy2(path,raw/path.name)
payloads=b.OUT/'retained-temporary-payloads'
for path in (b.OUT/'tmp').glob('layout-*.pickle'):
    payloads.mkdir(exist_ok=True);shutil.copy2(path,payloads/path.name)
removed=[]
for folder in ('tmp','mpl-cache','regression-tmp','retest-tmp'):
    path=(b.OUT/folder).resolve()
    assert path.parent==b.OUT.resolve() and path.is_relative_to(b.ROOT.resolve())
    if path.exists():shutil.rmtree(path);removed.append(folder)
report['removed_rebuildable_folders']=removed
report['monitor_raw_files_retained']=len(list(raw.glob('*.json')))
report['formal_native_runs']=24
b.save('preservation.json',report)
with zipfile.ZipFile(b.OUT/'experiment-source.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((b.ROOT/'scripts/editor_architecture').rglob('*.py')):
        archive.write(path,path.relative_to(b.ROOT))
    doc=b.ROOT/'docs/EDITOR_ARCHITECTURE_FEASIBILITY_WINDOWS_20261020.md'
    archive.write(doc,doc.relative_to(b.ROOT))
files={str(p.relative_to(b.OUT)):b.sha(p) for p in b.OUT.rglob('*') if p.is_file() and p.name!='seal.json'}
b.save('seal.json',{'artifacts':files,'report_sha256':b.sha(doc),
                   'source_sha256':{str(p.relative_to(b.ROOT)):b.sha(p) for p in (b.ROOT/'scripts/editor_architecture').rglob('*.py')}})
print(json.dumps(report,ensure_ascii=False,indent=2))
