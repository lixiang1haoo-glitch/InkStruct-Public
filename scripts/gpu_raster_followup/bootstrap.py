"""Second, isolated raster experiment; no original measurements are overwritten."""
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('INKSTRUCT_GPU_EXPERIMENT_OUT',str(ROOT/'artifacts/gpu_raster_followup_20261020')))
if not OUT.is_absolute():OUT=ROOT/OUT
OUT=OUT.resolve();OUT.relative_to((ROOT/'artifacts').resolve());OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'src'));sys.path.append(str(ROOT/'.venv/Lib/site-packages'))
sys.path.append(str(ROOT/'scripts/gpu_experiment'))
os.environ['INKSTRUCT_GPU_EXPERIMENT_OUT']=str(OUT)
os.environ['PYTHONPATH']=os.pathsep.join((str(ROOT/'src'),str(ROOT/'.venv/Lib/site-packages')))
os.environ['PYTHONUTF8']='1';os.environ['PYTHONIOENCODING']='utf-8'
os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True
for key,directory in [('TEMP','tmp'),('TMP','tmp'),('MPLCONFIGDIR','mpl-cache')]:
    path=OUT/directory;path.mkdir(exist_ok=True);os.environ[key]=str(path)
sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')

def save(name,value):
    import json
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def summary(values):
    import numpy as np
    a=np.asarray(values,dtype=float)
    return {'n':len(a),'median':float(np.median(a)),'p95':float(np.percentile(a,95)),
            'minimum':float(a.min()),'maximum':float(a.max())}
