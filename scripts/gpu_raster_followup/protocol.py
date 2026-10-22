"""Validate the unchanged private image transport at valid/invalid boundaries."""
import bootstrap as b
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

with TemporaryDirectory(prefix='raster-protocol-',dir=b.OUT/'tmp') as temporary:
    directory=Path(temporary)
    raw=(b.ROOT/'artifacts/gpu_benefit_20261020/page-6.svg').read_bytes()
    requests=[{'token':1,'spec':[630,891,1.5],'tiles':[[-1,-1]]},
        {'token':2,'spec':[630,891,1.5],'tiles':[[1,1]]},
        {'token':3,'spec':[630,891,1.5],'tiles':[[-1,-1],[0,0]]},
        {'token':4,'spec':[630,891,1.5],'tiles':[[-2,0]]},
        {'token':5,'spec':[630,891,1.5],'tiles':[[0,0],[0,0]]},
        {'token':6,'spec':[630,891,17],'tiles':[[-1,-1]]},
        {'token':7,'spec':[7000,7000,1],'tiles':[[-1,-1]]}]
    for request in requests:(directory/f"{request['token']}.svg").write_bytes(raw)
    env={**os.environ,'QT_QPA_PLATFORM':'offscreen','INKSTRUCT_RASTER_VARIANT':'cpu',
         'INKSTRUCT_GPU_EXPERIMENT_LABEL':'protocol'}
    result=subprocess.run([sys.executable,'scripts/gpu_raster_followup/worker.py',str(directory)],cwd=b.ROOT,env=env,
        input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stderr
    responses=[json.loads(row) for row in result.stdout.splitlines()]
    assert [r['token'] for r in responses]==list(range(1,8))
    assert all('images' in r and 'error' not in r for r in responses[:2])
    assert all('error' in r and 'images' not in r for r in responses[2:])
    assert responses[1]['images'][0]['width']==433 and responses[1]['images'][0]['height']==512
    for response in responses[:2]:
        for image in response['images']:
            col,row=image['tile'];path=directory/f"{response['token']}-{col}-{row}.argb"
            assert path.stat().st_size==image['bytes']==image['width']*image['height']*4
    b.save('protocol-validation.json',{'requests':requests,'responses':responses,'passed':7,
        'strict_image_dimensions_stride_and_byte_count':True,'worker_survives_rejected_requests':True})
print('7 protocol boundary cases passed',flush=True)
