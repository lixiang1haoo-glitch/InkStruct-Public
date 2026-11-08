"""Isolated experiment bootstrap; never imported by the default application."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import copyreg
from types import MappingProxyType

def restore_proxy(value):return MappingProxyType(value)
copyreg.pickle(type(MappingProxyType({})),lambda value:(restore_proxy,(dict(value),)))

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('INKSTRUCT_EDITOR_EXPERIMENT_OUT', ROOT/'artifacts/editor_architecture_20261020'))
if not OUT.is_absolute(): OUT = ROOT/OUT
OUT = OUT.resolve()
OUT.relative_to((ROOT/'artifacts').resolve())
sys.path.insert(0, str(ROOT/'src'))
sys.path.append(str(ROOT/'.venv/Lib/site-packages'))
os.environ['PYTHONPATH'] = os.pathsep.join((str(ROOT/'src'), str(ROOT/'.venv/Lib/site-packages')))
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
os.environ['PYTHONUTF8'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
for key, folder in [('TEMP','tmp'), ('TMP','tmp'), ('MPLCONFIGDIR','mpl-cache')]:
    path = OUT/folder
    path.mkdir(parents=True, exist_ok=True)
    os.environ[key] = str(path)

INPUT = ROOT/'artifacts/preview_performance_0.1.12_20261018/input.inkdoc'
REAL = ROOT/'artifacts/integration_0.1.33_20261020/native-input.inkdoc'

def sha(path):
    with Path(path).open('rb') as file: return hashlib.file_digest(file,'sha256').hexdigest()

def sha_bytes(raw):return hashlib.sha256(raw).hexdigest()

def save(name, value):
    with (OUT/name).open('x',encoding='utf-8') as file:
        json.dump(value,file,ensure_ascii=False,indent=2)

def summary(values):
    import numpy as np
    if not values: return {'n':0}
    a=np.asarray(values,dtype=float)
    return {'n':len(a),'median':float(np.median(a)),'p95':float(np.percentile(a,95)),
            'max':float(a.max()),'min':float(a.min())}

class Timings:
    def __init__(self): self.rows=[]
    def wrap(self, module, name, label=None):
        function=getattr(module,name)
        def measured(*args,**kwargs):
            start=time.perf_counter()
            try:return function(*args,**kwargs)
            finally:self.rows.append({'name':label or module.__name__+'.'+name,
                                      'start':start,'ms':(time.perf_counter()-start)*1000})
        setattr(module,name,measured)
        return function
    def aggregate(self, start=0):
        labels=sorted({r['name'] for r in self.rows[start:]})
        return {label:{'calls':len(v),'inclusive_ms':sum(v)} for label in labels
                if (v:=[r['ms'] for r in self.rows[start:] if r['name']==label])}

def instrument():
    from inkstruct.editor import mixed
    from inkstruct.layout import blocks, continuation
    from inkstruct.document import limits
    from inkstruct.assets.resolver import AssetResolver
    t=Timings()
    for module,names in [(mixed,['parse_markdown','layout_markdown','layout_key','source_key','validate_nodes','validate_snapshot']),
                         (blocks,['body_blocks','measure_runs','measure_table','break_lines','prepare','publish']),
                         (limits,['validate_snapshot'])]:
        for name in names:t.wrap(module,name)
    t.wrap(AssetResolver,'__init__','resource_resolver_init')
    return t

def build_inputs(loaded):
    return dict(session=loaded.session,revision=loaded.session.revision,resolver=loaded.resolver,
                run='',symbols='',page=loaded.page,style=loaded.style,flow=loaded.flow,cancelled=None)
