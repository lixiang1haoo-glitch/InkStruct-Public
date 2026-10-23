"""Read-only application imports and project-local experiment paths."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('INKSTRUCT_GPU_EXPERIMENT_OUT', str(ROOT / 'artifacts/gpu_benefit_20261020')))
if not OUT.is_absolute():OUT = ROOT / OUT
OUT = OUT.resolve()
OUT.relative_to((ROOT / 'artifacts').resolve())
OUT.mkdir(exist_ok=True, parents=True)
sys.path.insert(0, str(ROOT / 'src'))
sys.path.append(str(ROOT / '.venv/Lib/site-packages'))
os.environ['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src'), str(ROOT / '.venv/Lib/site-packages')))
os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
for key, directory in [('TEMP', 'tmp'), ('TMP', 'tmp'), ('MPLCONFIGDIR', 'mpl-cache'),
                       ('CUPY_CACHE_DIR', 'cupy-cache')]:
    path = OUT / directory
    path.mkdir(exist_ok=True)
    os.environ[key] = str(path)
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

def save(name, value):
    import json
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def summary(values):
    import numpy as np
    a = np.asarray(values, dtype=float)
    return dict(n=len(a), median=float(np.median(a)), p95=float(np.percentile(a, 95)),
                minimum=float(a.min()), maximum=float(a.max()))
