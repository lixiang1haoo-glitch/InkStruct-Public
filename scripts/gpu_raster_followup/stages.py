"""Paired raster stages, exact MSAA8 control, cache hits/misses and clip quality."""
import bootstrap as b
import hashlib
import json
import time
import numpy as np
from PIL import Image,ImageFilter
from PySide6 import QtCore,QtGui,QtSvg
from backend import Raster

app=QtGui.QGuiApplication([]);dpr=1.5
raws={'dense':(b.ROOT/'artifacts/gpu_benefit_20261020/page-6.svg').read_bytes(),
      'other':(b.ROOT/'artifacts/gpu_benefit_20261020/page-7.svg').read_bytes(),
      'clip':b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 96">
      <defs><clipPath id="c"><circle cx="64" cy="48" r="36"/></clipPath></defs>
      <g clip-path="url(#c)"><rect x="0" y="0" width="128" height="96" fill="#6688dd"/>
      <path d="M20 15H108V81H20Z M40 30H88V66H40Z" fill="#bb2233" fill-rule="evenodd"/>
      <g transform="translate(12 6) rotate(12 50 40)"><path d="M0 0L100 70M10 60L105 0" stroke="#000" stroke-width="1.1"/>
      <path d="M0 50Q35 0 100 55" stroke="white" stroke-width=".7" fill="none"/></g></g></svg>'''}
for name,raw in raws.items():(b.OUT/f'input-{name}.svg').write_bytes(raw)
sequence=[('dense',1.),('dense',1.),('dense',1.5),('dense',1.),('other',1.),('dense',1.),('clip',1.),('dense',1.)]
def dimensions(name,zoom):return (round(630*zoom),round(891*zoom)) if name!='clip' else (512,384)
def hash_image(image):return hashlib.sha256(image.constBits()).hexdigest()

control=Raster('correct');gold={};quality=[]
for name,zoom in list(dict.fromkeys(sequence)):
    w,h=dimensions(name,zoom);images,_=control.render(raws[name],w,h,dpr);image=images[0][1]
    gold[name,zoom]=hash_image(image);image.save(str(b.OUT/f'quality-correct-{name}-{zoom}.png'))
    renderer=QtSvg.QSvgRenderer(raws[name]);cpu=QtGui.QImage(image.width(),image.height(),image.format());cpu.setDevicePixelRatio(dpr);cpu.fill(QtCore.Qt.GlobalColor.white)
    p=QtGui.QPainter(cpu);renderer.render(p,QtCore.QRectF(0,0,w,h));p.end();cpu.save(str(b.OUT/f'quality-cpu-{name}-{zoom}.png'))
    arrays=[np.asarray(Image.open(b.OUT/f'quality-{backend}-{name}-{zoom}.png').convert('RGB')).astype(int) for backend in ('cpu','correct')]
    masks=[np.min(a,axis=2)<180 for a in arrays];near=[np.asarray(Image.fromarray(m.astype('uint8')*255).filter(ImageFilter.MaxFilter(5)))>0 for m in masks]
    quality.append({'name':name,'zoom':zoom,'mean_abs_rgb':float(np.mean(abs(arrays[0]-arrays[1]))),
        'cpu_ink_unmatched_beyond_2px':int(np.count_nonzero(masks[0]&~near[1])),
        'gpu_ink_unmatched_beyond_2px':int(np.count_nonzero(masks[1]&~near[0]))})
control.close();records=[];startup=[]
variants=('old','correct','pooled','cached','resolve','picture')
for rep in range(5):
    order=variants if rep%2==0 else tuple(reversed(variants))
    for variant in order:
        t=time.perf_counter();raster=Raster(variant);warm=raster.warm()
        startup.append({'variant':variant,'repeat':rep,'context_s':raster.context_s,'warm_s':warm,'all_s':time.perf_counter()-t})
        for position,(name,zoom) in enumerate(sequence):
            w,h=dimensions(name,zoom)
            images,record=raster.render(raws[name],w,h,dpr);image=images[0][1]
            t=time.perf_counter();path=b.OUT/'tmp/stage.argb';path.write_bytes(image.constBits());write=time.perf_counter()-t
            t=time.perf_counter();pixels=path.read_bytes();received=QtGui.QImage(pixels,image.width(),image.height(),image.bytesPerLine(),image.format()).copy();receive=time.perf_counter()-t
            record.update(repeat=rep,position=position,scene=name,zoom=zoom,pixel_write_s=write,receive_copy_s=receive,
                end_to_end_s=record['total_to_completed_image_s']+write+receive,
                exact_stencil_control_pixels=hash_image(received)==gold[name,zoom])
            if not record['exact_stencil_control_pixels']:
                image.save(str(b.OUT/f'mismatch-{variant}-{rep}-{position}.png'))
            records.append(record)
        raster.close()
        print(rep,variant,'ms',[round(r['end_to_end_s']*1000,2) for r in records[-len(sequence):]],flush=True)
        b.save('stages-progress.json',{'records':records,'startup':startup,'quality':quality})
b.save('stages.json',{'records':records,'startup':startup,'quality':quality,'variants':variants,
    'dpr':dpr,'sequence':sequence,'completion':'every result includes synchronous image readback, file IPC and receiving copy',
    'notes':'old has no stencil, correct/optimized MSAA8 use CombinedDepthStencil; QPicture rejected if pixels change'})
