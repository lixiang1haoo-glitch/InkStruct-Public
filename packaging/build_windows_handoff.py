"""Freeze the selected desktop development workspace without copying caches or host Git config."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/windows_handoff_20261014'
META = OUT / 'metadata'
ARCHIVE = OUT / 'InkStruct-Windows-Dev-0.1.3-20261014.zip'
files = {}
skip_parts = {'.git', '.venv', '__pycache__', '.pytest_cache', '.ruff_cache', '__MACOSX'}

def add(path, relative=None):
    path = Path(path)
    if any(x in skip_parts for x in path.parts) or path.name in {'.DS_Store','.env'} or path.name.startswith('._'):
        return
    if path.is_symlink():
        raise ValueError('Unexpected symlink: ' + str(path))
    if path.is_dir():
        for base, dirs, names in os.walk(path):
            dirs[:] = [x for x in dirs if x not in skip_parts and not x.endswith('.app')]
            for name in names:
                p = Path(base)/name
                add(p, str(Path(relative)/p.relative_to(path)) if relative else None)
        return
    if not path.is_file():
        raise ValueError('Missing input: '+str(path))
    rel = str(relative or path.relative_to(ROOT)).replace('\\','/')
    if rel in files and files[rel] != path:
        raise ValueError('Duplicate destination: '+rel)
    files[rel] = path

for name in ('src','scripts','tests','packaging','docs','configs','examples','third_party','检查项目'):
    add(ROOT/name)
for p in ROOT.iterdir():
    if p.is_file() and p.name != '.DS_Store' and not p.name.startswith('.env'):
        add(p)
for name in ('artifacts/external/data_collection','artifacts/structures','artifacts/source_samples','artifacts/samples',
             'artifacts/v61_collection_acceptance_20261013/run_v3_with_validation',
             'artifacts/v61_corrected_library_20261014/full_v1'):
    add(ROOT/name)
protocol = json.loads((ROOT/'artifacts/v61_corrected_library_20261014/full_v1/protocol.json').read_text())
for name in protocol['inputs']:
    add(ROOT/name)
for writer in ('user_001','scx','mjb','wsq'):
    add(ROOT/'profiles'/writer)
    for suffix in ('.inkfont','-developer.inkfont'):
        add(ROOT/f'artifacts/inkstruct_0_1_20261014/fonts/{writer}-0.1{suffix}')
for p in (ROOT/'artifacts/inkstruct_0_1_20261014/fonts').glob('*.json'):
    add(p)
for p in (ROOT/'artifacts/inkstruct_0_1_20261014').glob('*.windows.diff'):
    add(p)
for folder in ('release_0_1_2','release_0_1_3','ui_cleanup_20261014','inkstruct_0_1_generation_update'):
    base=ROOT/'artifacts'/folder
    for p in base.iterdir():
        if p.is_file() and p.suffix in ('.md','.json','.log','.inkdoc') and p.stat().st_size<10*1024**2:
            add(p)
    for rel in ('bundle-check/verification.json','check/verification.json','check-0.1.1/verification.json',
                'source-check-offscreen/verification.json','e2e-final/verification.json','build/build-provenance.json'):
        if (base/rel).is_file():add(base/rel)
add(ROOT/'artifacts/release_0_1_3/release/InkStruct用户手册_0.1.3.pdf')
add(Path('/Users/kailee/Library/Application Support/InkStruct/workspace'), 'handoff/desktop_workspace_snapshot')
for p in [Path('/Volumes/A/AGENT/InkStruct/user_001.zip'),*Path('/Volumes/A/AGENT/InkStruct/20261013').glob('*.zip')]:
    add(p, 'handoff/raw_archives/'+p.name)
p=Path('/Volumes/A/user_001补录小数点.zip')
if p.is_file():add(p,'handoff/raw_archives/'+p.name)
for p in META.iterdir():add(p,'handoff/'+p.name)
add(ROOT/'docs/WINDOWS_DEVELOPMENT_HANDOFF.md','WINDOWS_START_HERE.md')
# Windows file names and case-insensitive extraction must be unambiguous.
seen={}
reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
for rel in files:
    key=unicodedata.normalize('NFC',rel).casefold()
    if key in seen and seen[key]!=rel:raise ValueError('Case collision: '+rel+' vs '+seen[key])
    seen[key]=rel
    for part in Path(rel).parts:
        if re.search(r'[<>:"|?*\x00-\x1f]',part) or part.endswith((' ','.')) or part.split('.')[0].upper() in reserved:
            raise ValueError('Windows-incompatible path: '+rel)
listing=[{'path':k,'bytes':p.stat().st_size} for k,p in sorted(files.items())]
(OUT/'selection.json').write_text(json.dumps({'files':len(files),'bytes':sum(x['bytes'] for x in listing),
    'max_relative_path_length':max(map(len,files)),'selection':listing},ensure_ascii=False,indent=2))
print('Selected',len(files),'files;',round(sum(x['bytes'] for x in listing)/1024**3,2),'GiB',flush=True)
if os.environ.get('INKSTRUCT_HANDOFF_PLAN_ONLY')=='1':raise SystemExit(0)
if ARCHIVE.exists():raise ValueError('Archive exists; never replace a delivery')
manifest=[];originals={};dependency_mismatches=[];start=time.monotonic()
with zipfile.ZipFile(ARCHIVE,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
    for n,(rel,p) in enumerate(sorted(files.items()),1):
        before=p.stat();h=hashlib.sha256()
        info=zipfile.ZipInfo.from_file(p,'InkStruct-Windows-Dev/'+rel)
        info.compress_type=zipfile.ZIP_STORED if p.suffix.lower() in ('.inkfont','.zip','.gz','.png','.jpg','.pdf') else zipfile.ZIP_DEFLATED
        info._compresslevel=3
        with p.open('rb') as source,z.open(info,'w',force_zip64=True) as target:
            for chunk in iter(lambda:source.read(1024*1024),b''):
                h.update(chunk);target.write(chunk)
        after=p.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Input changed: '+rel)
        digest=h.hexdigest();manifest.append({'path':rel,'bytes':after.st_size,'sha256':digest})
        originals[rel]=(after.st_size,after.st_mtime_ns)
        if rel in protocol['inputs'] and digest!=protocol['inputs'][rel]:dependency_mismatches.append(rel)
        if n%10000==0:print('Archived',n,'/',len(files),flush=True)
    # Detect changes made after an individual file was copied.
    for rel,p in files.items():
        st=p.stat()
        if (st.st_size,st.st_mtime_ns)!=originals[rel]:raise ValueError('Input changed during freeze: '+rel)
    body=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in manifest)
    z.writestr('InkStruct-Windows-Dev/handoff/manifest.jsonl',body)
    (OUT/'manifest.jsonl').write_text(body)
report={'files':len(manifest),'uncompressed_bytes':sum(x['bytes'] for x in manifest),'zip_bytes':ARCHIVE.stat().st_size,
    'seconds':round(time.monotonic()-start,1),'historical_dependency_hash_mismatches':dependency_mismatches,
    'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
    'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'application_version':'0.1.3','windows_executed':False}
(OUT/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False),flush=True)
