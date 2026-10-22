"""Final closed-log seal. Keep initial seal and its self-log timing discrepancy."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/editor_architecture_20261020'
def sha(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()
initial=json.loads((OUT/'seal.json').read_text(encoding='utf-8'))
changed=[name for name,digest in initial['artifacts'].items() if sha(OUT/name)!=digest]
assert changed==['finalize.log'],changed
doc=ROOT/'docs/EDITOR_ARCHITECTURE_FEASIBILITY_WINDOWS_20261020.md'
doc.write_text(doc.read_text(encoding='utf-8').replace('`seal.json`','`seal-final.json`'),encoding='utf-8')
with (OUT/'seal-correction.json').open('x',encoding='utf-8') as file:
    json.dump({'initial_seal_preserved':True,'only_changed_file':changed,
               'reason':'Initial seal hashed the redirected finalization log before the final print completed. All measurement data unchanged; final seal covers the now-closed log.',
               'formal_native_runs':24,'additional_explicit_backend_confirmation_runs':1},file,indent=2)
sources=sorted((ROOT/'scripts/editor_architecture').rglob('*.py'))
with zipfile.ZipFile(OUT/'experiment-source-final.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
    for path in [*sources,doc]:archive.write(path,path.relative_to(ROOT))
record={'artifacts':{str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='seal-final.json'},
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sources},'report_sha256':sha(doc)}
with (OUT/'seal-final.json').open('x',encoding='utf-8') as file:json.dump(record,file,indent=2)
assert all(sha(OUT/name)==digest for name,digest in record['artifacts'].items())
print('Closed-log final seal verified:',len(record['artifacts']),'artifacts;',len(sources),'experiment source files.')
