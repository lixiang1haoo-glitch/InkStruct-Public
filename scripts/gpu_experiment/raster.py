"""Same SVG, physical pixel size and content: QImage vs OpenGL FBO/MSAA8."""
import bootstrap as b
import cProfile
import hashlib
import json
import pstats
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from PySide6 import QtCore,QtGui,QtSvg,QtOpenGL
from inkstruct.document.package import load_package
from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.renderers.pages import page_svg
from monitor import Monitor

app=QtGui.QGuiApplication([]);monitor=Monitor().start();report={}
prof=cProfile.Profile();prof.enable();start=time.perf_counter()
loaded=load_package(b.ROOT/'artifacts/preview_performance_0.1.12_20261018/input.inkdoc')
report['package_read_decompress_parse_validate_s']=time.perf_counter()-start
timings={}
for name in ('parse_markdown','layout_markdown'):
    old=getattr(mixed,name)
    def wrapper(*args,_old=old,_name=name,**kwargs):
        t=time.perf_counter()
        try:return _old(*args,**kwargs)
        finally:timings.setdefault(_name,[]).append(time.perf_counter()-t)
    setattr(mixed,name,wrapper)
cache=MarkdownBuildCache();t=time.perf_counter()
result=mixed.build_markdown(loaded.session,0,loaded.resolver,'','',loaded.page,loaded.style,loaded.flow,None,cache)
report['profiled_build_s']=time.perf_counter()-t;report['build_parts']=timings
prof.disable();prof.dump_stats(str(b.OUT/'preview-open.prof'))
with (b.OUT/'preview-open-profile.txt').open('w',encoding='utf-8') as f:pstats.Stats(prof,stream=f).sort_stats('cumulative').print_stats(90)
snapshot=result['snapshot'];report['pages']=len(snapshot.pages);report['diagnostics']=len(snapshot.diagnostics)
report['timing_note']='profiled initial build is attribution only, native preview JSON holds unprofiled totals'
svgs=[]
for p in range(len(snapshot.pages)):
    t=time.perf_counter();s=page_svg(snapshot,p,debug=not snapshot.exportable).encode();elapsed=time.perf_counter()-t
    svgs.append(s);(b.OUT/f'page-{p+1}.svg').write_bytes(s)
    report.setdefault('svg_build',[]).append({'page':p+1,'seconds':elapsed,'bytes':len(s),'sha256':hashlib.sha256(s).hexdigest()})

t=time.perf_counter();fmt=QtGui.QSurfaceFormat();fmt.setSamples(8)
context=QtGui.QOpenGLContext();context.setFormat(fmt);assert context.create()
surface=QtGui.QOffscreenSurface();surface.setFormat(context.format());surface.create();assert context.makeCurrent(surface)
functions=context.functions();report['gl_renderer']=str(functions.glGetString(0x1F01));report['gl_context_s']=time.perf_counter()-t
report['format']=str(context.format());records=[]

def render(backend,svg,width,height,dpr,save=None):
    start=time.perf_counter();renderer=QtSvg.QSvgRenderer(svg);assert renderer.isValid();parse=time.perf_counter()-start
    t=time.perf_counter();w=round(width*dpr);h=round(height*dpr)
    if backend=='cpu':
        image=QtGui.QImage(w,h,QtGui.QImage.Format.Format_ARGB32_Premultiplied);image.setDevicePixelRatio(dpr);image.fill(QtCore.Qt.GlobalColor.white);device=image
    else:
        format=QtOpenGL.QOpenGLFramebufferObjectFormat();format.setSamples(8)
        fbo=QtOpenGL.QOpenGLFramebufferObject(w,h,format);assert fbo.isValid();assert fbo.bind()
        device=QtOpenGL.QOpenGLPaintDevice(w,h);device.setDevicePixelRatio(dpr)
    alloc=time.perf_counter()-t;t=time.perf_counter()
    painter=QtGui.QPainter(device);engine=str(painter.paintEngine().type())
    painter.fillRect(QtCore.QRectF(0,0,width,height),QtCore.Qt.GlobalColor.white)
    renderer.render(painter,QtCore.QRectF(0,0,width,height));painter.end()
    if backend=='gpu':functions.glFinish()
    raster=time.perf_counter()-t;t=time.perf_counter()
    if backend=='gpu':
        image=fbo.toImage();image=image.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied);image.setDevicePixelRatio(dpr);fbo.release()
    readback=time.perf_counter()-t
    t=time.perf_counter();path=b.OUT/'tmp/raster.argb';path.write_bytes(image.constBits());write=time.perf_counter()-t
    t=time.perf_counter();raw=path.read_bytes();copy=QtGui.QImage(raw,w,h,image.bytesPerLine(),image.format()).copy();ipc=time.perf_counter()-t
    if save:image.save(str(b.OUT/save))
    return {'backend':backend,'svg_parse_s':parse,'allocate_s':alloc,'raster_sync_s':raster,
            'readback_s':readback,'pixel_write_s':write,'pixel_read_copy_s':ipc,
            'total_s':parse+alloc+raster+readback+write+ipc,'engine':engine,'pixels':[w,h],
            'samples':fbo.format().samples() if backend=='gpu' else None}

for zoom in (1.,1.5,2.):
    for rep in range(7):
        for backend in (('cpu','gpu') if rep%2==0 else ('gpu','cpu')):
            row=render(backend,svgs[5],round(snapshot.page_profile.width_mm*3*zoom),round(snapshot.page_profile.height_mm*3*zoom),app.devicePixelRatio(),f'raster-{backend}-zoom{zoom}.png' if rep==0 else None)
            records.append({**row,'zoom':zoom,'repeat':rep});print(backend,zoom,rep,round(row['total_s']*1000,2),flush=True)
    a=np.asarray(Image.open(b.OUT/f'raster-cpu-zoom{zoom}.png').convert('RGB')).astype(int)
    c=np.asarray(Image.open(b.OUT/f'raster-gpu-zoom{zoom}.png').convert('RGB')).astype(int)
    masks=[np.min(v,axis=2)<180 for v in (a,c)];near=[np.asarray(Image.fromarray(m.astype('uint8')*255).filter(ImageFilter.MaxFilter(5)))>0 for m in masks]
    report.setdefault('pixel_comparison',[]).append({'zoom':zoom,'mean_abs_rgb':float(np.mean(abs(a-c))),
        'different_pixel_fraction':float(np.mean(np.any(a!=c,axis=2))),
        'cpu_ink_unmatched_beyond_2px':int(np.count_nonzero(masks[0]&~near[1])),
        'gpu_ink_unmatched_beyond_2px':int(np.count_nonzero(masks[1]&~near[0])),
        'cpu_ink_pixels':int(masks[0].sum()),'gpu_ink_pixels':int(masks[1].sum())})
report['records']=records;report['monitor']=monitor.stop();b.save('raster.json',report)
context.doneCurrent()
