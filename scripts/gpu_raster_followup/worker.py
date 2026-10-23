"""Private opt-in raster protocol; pixels and original validation are preserved."""
import time
worker_start=time.perf_counter()
import bootstrap as b
import json
import math
import os
import sys
from pathlib import Path
from PySide6 import QtGui
from backend import Raster,CpuRaster

app=QtGui.QGuiApplication([]);variant=os.environ['INKSTRUCT_RASTER_VARIANT']
raster=CpuRaster(variant) if variant in ('cpu','cpu4') else Raster(variant);warm=raster.warm()
label=os.environ.get('INKSTRUCT_GPU_EXPERIMENT_LABEL','unknown')
b.save(f'worker-start-{label}.json',{'variant':variant,'context_s':raster.context_s,'shader_warm_s':warm,
                                   'startup_s':time.perf_counter()-worker_start,'renderer':raster.renderer})
directory=Path(sys.argv[1]).resolve(strict=True)
for raw in iter(lambda:sys.stdin.buffer.readline(65537),b''):
    response={'token':None}
    try:
        assert len(raw)<=65536
        request=json.loads(raw);token=request['token'];response['token']=token
        assert type(token) is int and token>0
        width,height,dpr=request['spec']
        assert all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (width,height,dpr)) and dpr<=16
        path=directory/f'{token}.svg';assert path.stat().st_size<=32*1024**2
        t=time.perf_counter();data=path.read_bytes();read_s=time.perf_counter()-t
        tiles=request['tiles'];assert 1<=len(tiles)<=32
        assert [-1,-1] not in tiles or len(tiles)==1
        assert len({tuple(tile) for tile in tiles})==len(tiles)
        pw,ph=math.ceil(width*dpr),math.ceil(height*dpr)
        for col,row in tiles:
            assert type(col) is int and type(row) is int
            assert (col,row)==(-1,-1) or (0<=col<math.ceil(pw/512) and 0<=row<math.ceil(ph/512))
        images,record=raster.render(data,*request['spec'],tiles)
        start=time.perf_counter();meta=[]
        for tile,image in images:
            col,row=tile;path=directory/f'{token}-{col}-{row}.argb';path.write_bytes(image.constBits())
            meta.append({'tile':list(tile),'width':image.width(),'height':image.height(),
                         'stride':image.bytesPerLine(),'bytes':image.sizeInBytes()})
        record.update(source_read_s=read_s,pixel_write_s=time.perf_counter()-start,token=token,spec=request['spec'])
        response.update(images=meta,raster_seconds=record['total_to_completed_image_s']+record['pixel_write_s'])
        with (b.OUT/f'worker-{label}.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
    except Exception as error:response['error']=repr(error)
    print(json.dumps(response),flush=True)
raster.close()
