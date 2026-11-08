"""Experimental GPU raster worker using the existing private pixel protocol."""
import bootstrap as b
import json
import math
import os
import sys
import time
from pathlib import Path
from PySide6 import QtCore,QtGui,QtSvg,QtOpenGL

app=QtGui.QGuiApplication([])
context=QtGui.QOpenGLContext();assert context.create()
surface=QtGui.QOffscreenSurface();surface.setFormat(context.format());surface.create()
assert context.makeCurrent(surface)
functions=context.functions()
directory=Path(sys.argv[1]).resolve(strict=True)
label=os.environ.get('INKSTRUCT_GPU_EXPERIMENT_LABEL','unknown')
for raw in iter(lambda:sys.stdin.buffer.readline(65537),b''):
    response={'token':None};record={}
    try:
        request=json.loads(raw);token=request['token'];response['token']=token
        assert type(token) is int and token>0
        width,height,dpr=request['spec'];pw,ph=math.ceil(width*dpr),math.ceil(height*dpr)
        source=directory/f'{token}.svg';assert source.stat().st_size<=32*1024**2
        t=time.perf_counter();renderer=QtSvg.QSvgRenderer(source.read_bytes());assert renderer.isValid()
        record['svg_read_parse_s']=time.perf_counter()-t
        start=time.perf_counter();images=[]
        for col,row in request['tiles']:
            x,y=(0,0) if (col,row)==(-1,-1) else (col*512,row*512)
            w,h=(pw,ph) if (col,row)==(-1,-1) else (min(512,pw-x),min(512,ph-y))
            assert 0<w*h*4<=40*1024**2
            t=time.perf_counter();fmt=QtOpenGL.QOpenGLFramebufferObjectFormat();fmt.setSamples(8)
            fbo=QtOpenGL.QOpenGLFramebufferObject(w,h,fmt);assert fbo.isValid() and fbo.bind()
            device=QtOpenGL.QOpenGLPaintDevice(w,h);device.setDevicePixelRatio(dpr)
            painter=QtGui.QPainter(device);painter.fillRect(QtCore.QRectF(0,0,w/dpr,h/dpr),QtCore.Qt.GlobalColor.white)
            painter.translate(-x/dpr,-y/dpr);renderer.render(painter,QtCore.QRectF(0,0,width,height));painter.end();functions.glFinish()
            record['raster_allocate_sync_s']=record.get('raster_allocate_sync_s',0)+time.perf_counter()-t
            t=time.perf_counter();image=fbo.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied);fbo.release()
            record['readback_s']=record.get('readback_s',0)+time.perf_counter()-t
            t=time.perf_counter();path=directory/f'{token}-{col}-{row}.argb';path.write_bytes(image.constBits())
            record['write_s']=record.get('write_s',0)+time.perf_counter()-t
            images.append({'tile':[col,row],'width':w,'height':h,'stride':image.bytesPerLine(),'bytes':image.sizeInBytes()})
        response.update(images=images,raster_seconds=time.perf_counter()-start)
        record.update(token=token,spec=request['spec'],tiles=request['tiles'],total_s=response['raster_seconds'],renderer=str(functions.glGetString(0x1F01)))
        with (b.OUT/f'raster-worker-{label}.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
    except Exception as e:response['error']=repr(e)
    print(json.dumps(response),flush=True)
