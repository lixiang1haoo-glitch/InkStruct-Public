"""Exact-sample Qt path reuse; validated affine match, otherwise original paths."""
import common as b
from dataclasses import replace
import hashlib
import pickle
import sys
import time
from PySide6 import QtCore,QtGui,QtSvg
from inkstruct.editor.preview_backend import CpuRaster
from inkstruct.document.glyph_corrections import correction_for
from inkstruct.document.package import load_package
from inkstruct.renderers.pages import page_svg

def path_for(points):
    path=QtGui.QPainterPath()
    if len(points)==1:
        return None
    path.moveTo(*points[0])
    for point in points[1:]:path.lineTo(*point)
    return path

class Paths:
    def __init__(self,result,flow):
        self.cache={};self.hits=0;self.matched=0;self.fallback=0
        self.glyphs={(g.asset_id,g.metrics_key,g.sample_id):g for pool in result['resolver'].pools.values() for g in pool}
        self.selections=result['resolver'].selections
        self.keys={identity:(*identity,g.provider_version,b.sha_bytes(g.original_json),
                    hashlib.sha256(pickle.dumps(g.strokes,protocol=5)).digest()) for identity,g in self.glyphs.items()}
        self.flow=flow
    def prepare(self,page,reuse):
        fragments={}
        for f in page.fragments:fragments.setdefault(f.occurrence_id,[]).append(f)
        commands=[]
        for op in (*page.preview_ops,*page.paint_ops):
            command=None
            if reuse:
                for f in fragments.get(op.occurrence_id,[]):
                    selected=self.selections.get(f.occurrence_id)
                    identity=(selected.asset_id,selected.metrics_key,selected.sample_id) if selected else None
                    g=self.glyphs.get(identity)
                    if g is None or not f.glyph_em_mm:continue
                    em=f.glyph_em_mm;origin=f.x_mm+f.glyph_origin_offset_mm
                    rule=correction_for(self.flow.glyph_corrections,f)
                    sx=rule.scale_x if rule else 1;sy=rule.scale_y if rule else 1
                    dx=rule.dx_em*em if rule else 0;dy=rule.dy_em*em if rule else 0
                    for index,stroke in enumerate(g.strokes):
                        if len(stroke)!=len(op.points):continue
                        local=tuple((px*em*sx+dx,(py-g.metrics.baseline)*em*sy+dy) for px,py in stroke)
                        if not all(abs(x-(origin+px))<1e-9 and abs(y-(f.baseline_mm+py))<1e-9
                                   for (x,y),(px,py) in zip(op.points,local)):continue
                        key=(self.keys[identity],index,em,rule,op.width_mm,op.color)
                        if key in self.cache:self.hits+=1
                        else:self.cache[key]=(path_for(local),local)
                        path,points=self.cache[key]
                        command=(path,points,origin,f.baseline_mm,op.width_mm,op.color)
                        self.matched+=1;break
                    if command:break
            if command is None:
                self.fallback+=1
                command=(path_for(op.points),op.points,0,0,op.width_mm,op.color)
            commands.append(command)
        return commands

def draw(commands,base,width,height,dpr,physical):
    image=QtGui.QImage(*physical,QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr);image.fill(QtCore.Qt.GlobalColor.white)
    p=QtGui.QPainter(image);base.render(p,QtCore.QRectF(0,0,width,height))
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing,True)
    p.scale(width/210,height/297)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    for path,points,x,y,w,color in commands:
        pen=QtGui.QPen(QtGui.QColor(color),w,QtCore.Qt.PenStyle.SolidLine,
                       QtCore.Qt.PenCapStyle.RoundCap,QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen);p.save();p.translate(x,y)
        if path is None:
            p.setBrush(QtGui.QColor(color));p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.drawEllipse(QtCore.QPointF(*points[0]),w/2,w/2)
        else:p.drawPath(path)
        p.restore()
    p.end();return image

def main():
    tag='-'+sys.argv[1] if len(sys.argv)>1 else ''
    app=QtGui.QGuiApplication([])
    with (b.OUT/'baseline-result-v2.pickle').open('rb') as file:result=pickle.load(file)
    loaded=load_package(b.INPUT);snapshot=result['snapshot'];index=5
    assert snapshot.page_profile.width_mm==210 and snapshot.page_profile.height_mm==297
    page=snapshot.pages[index]
    base_snapshot=replace(snapshot,pages=tuple(replace(p,paint_ops=(),preview_ops=()) if i==index else p for i,p in enumerate(snapshot.pages)))
    base=QtSvg.QSvgRenderer(page_svg(base_snapshot,index,debug=not snapshot.exportable).encode())
    cpu=CpuRaster();rows=[];images={}
    init_start=time.perf_counter();paths=Paths(result,loaded.flow);identity_prepare_ms=(time.perf_counter()-init_start)*1000
    retained=None
    for repeat in range(5):
        for mode in ('svg','direct','sample','retained'):
            start=time.perf_counter()
            if mode=='svg':
                raw=page_svg(snapshot,index,debug=not snapshot.exportable).encode();prepared=time.perf_counter()
                renderer=cpu.svg(raw);parsed=time.perf_counter()
                image=cpu.image(renderer,630,891,1.5,0,0,945,1337)
            else:
                if mode=='retained':
                    if retained is None:retained=(page,paths.prepare(page,True))
                    assert retained[0] is page
                    commands=retained[1]
                else:commands=paths.prepare(page,mode=='sample')
                prepared=time.perf_counter();parsed=prepared
                image=draw(commands,base,630,891,1.5,(945,1337))
            end=time.perf_counter()
            rows.append({'mode':mode,'repeat':repeat,'prepare_ms':(prepared-start)*1000,
                         'parse_ms':(parsed-prepared)*1000,'draw_completed_ms':(end-parsed)*1000,
                         'total_ms':(end-start)*1000})
            images[mode]=image
    import numpy as np
    original=np.frombuffer(images['svg'].constBits(),dtype=np.uint8).reshape(1337,945,4)
    quality={}
    for mode in ('direct','sample','retained'):
        actual=np.frombuffer(images[mode].constBits(),dtype=np.uint8).reshape(1337,945,4)
        diff=np.abs(original[:,:,:3].astype('i2')-actual[:,:,:3].astype('i2'))
        quality[mode]={'mean_abs_rgb':float(diff.mean()),'different_pixels':int(np.any(diff,axis=2).sum()),'max_channel':int(diff.max())}
        images[mode].save(str(b.OUT/f'geometry{tag}-{mode}.png'))
    assert bytes(images['direct'].constBits())==bytes(images['sample'].constBits()),'Shared samples must match direct authoritative paths'
    images['svg'].save(str(b.OUT/f'geometry{tag}-svg.png'))
    b.save(f'geometry{tag}-samples.json',{'samples':rows,'quality_vs_svg':quality,'sample_matched_ops':paths.matched,
           'all_resource_identity_preparation_ms':identity_prepare_ms,
           'fallback_ops':paths.fallback,'sample_cache_hits':paths.hits,'sample_entries':len(paths.cache),
           'shared_vs_direct_pixels_exact':True,'authoritative_affine_tolerance_mm':1e-9,
           'limitation':'Display preparation only; layout still expands authoritative points. Not native frame timing.'})
    print('Geometry experiment complete',quality,flush=True)

if __name__=='__main__':main()
