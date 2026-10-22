"""Run a diagnostic copy of the existing failing test, keep its assertion intact."""
import common as b
import ast
import os
import subprocess
import textwrap

tree=ast.parse((b.ROOT/'tests/test_continuous_preview_qt.py').read_text(encoding='utf-8'))
program=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROGRAM' for t in n.targets))
diagnostic='''
painter.end()
import json,os,hashlib,numpy as np
from pathlib import Path
directory=Path(os.environ['INKSTRUCT_EDITOR_DIAG_OUT']);scale=os.environ['QT_SCALE_FACTOR']+'-v2'
a=np.frombuffer(actual.constBits(),dtype=np.uint8).reshape(ph,pw,4)
r=np.frombuffer(reference.constBits(),dtype=np.uint8).reshape(ph,pw,4)
delta=np.abs(a.astype('i2')-r.astype('i2'));yy,xx=np.where(np.any(delta,axis=2))
data={'qimage_equal':actual==reference,'pixels_exact':bytes(actual.constBits())==bytes(reference.constBits()),
      'different_pixels':int(len(xx)),'max_channel':int(delta.max()),
      'bounds':None if not len(xx) else [int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())],
      'actual_meta':[actual.devicePixelRatio(),actual.dotsPerMeterX(),actual.dotsPerMeterY(),str(actual.colorSpace()),str(actual.format())],
      'reference_meta':[reference.devicePixelRatio(),reference.dotsPerMeterX(),reference.dotsPerMeterY(),str(reference.colorSpace()),str(reference.format())],
      'backend':c._process.backend,'fallback':c._process.fallback_reason,'spec':[width,height,dpr]}
(directory/f'unit-tiling-{scale}-diagnosis.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
actual.save(str(directory/f'unit-tiling-{scale}-actual.png'));reference.save(str(directory/f'unit-tiling-{scale}-reference.png'))
c.stop_rendering();scroll.close()
assert actual==reference
'''
program=program.replace('    painter.end();assert actual==reference',textwrap.indent(diagnostic.strip(),'    '))
for scale in ('1','1.5','2'):
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_SCALE_FACTOR=scale,INKSTRUCT_EDITOR_DIAG_OUT=str(b.OUT))
    with (b.OUT/f'unit-tiling-{scale}-v2-diagnosis.log').open('xb') as file:
        r=subprocess.run([str(b.ROOT/'.venv/Scripts/python.exe'),'-B','-X','utf8','-c',program,'tiling'],cwd=b.ROOT,env=env,stdout=file,stderr=subprocess.STDOUT)
    print(scale,'unchanged image assertion exit',r.returncode,flush=True)
