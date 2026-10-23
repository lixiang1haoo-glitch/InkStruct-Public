"""Cache, clipping, tiled GPU pixels, CPU control and scheduling safety checks."""
import bootstrap as b
import hashlib
import threading
from types import SimpleNamespace
from PySide6 import QtCore,QtGui,QtSvg
from backend import Raster,CpuRaster
from patches import stable_viewport_changed
from inkstruct.editor.continuous_preview import ContinuousPageCanvas

app=QtGui.QGuiApplication([]);fn=stable_viewport_changed(ContinuousPageCanvas.viewport_changed)
schedule=[]
for index,ready,expected in [(3,False,False),(2,True,False),(5,True,False),(1,True,True),(2,False,True),(8,True,True)]:
    event=threading.Event();state=SimpleNamespace(_job=SimpleNamespace(index=index,cancelled=event),_previous_top=0,
        viewport_rect=lambda:QtCore.QRectF(0,10,100,100),pages_in_rect=lambda r:range(3,5),viewport_ready=lambda:ready,
        _queue=lambda:None)
    fn(state);assert event.is_set()==expected
    schedule.append({'job_index':index,'visible':[3,4],'ready':ready,'cancelled':event.is_set()})
empty_event=threading.Event();empty=SimpleNamespace(_job=SimpleNamespace(index=1,cancelled=empty_event),_previous_top=0,
    viewport_rect=lambda:QtCore.QRectF(),pages_in_rect=lambda r:(),viewport_ready=lambda:True,_queue=lambda:None)
fn(empty);assert empty_event.is_set();schedule.append({'empty_viewport_cancelled':True})

raw=(b.ROOT/'artifacts/gpu_benefit_20261020/page-6.svg').read_bytes()
control=Raster('correct');candidates=[Raster('cached'),Raster('cached4')];rows=[]
def digest(image):return hashlib.sha256(image.constBits()).hexdigest()
for width,height,dpr,tiles in [(630,891,1.5,((-1,-1),)),(945,1337,1.5,((-1,-1),)),
        (2667,3667,1.5,((0,0),(1,0),(2,0),(2,3),(3,2))),
        (2667,3667,1.5,((3,2),(2,3),(1,0),(0,0))),
        (630,891,1.5,((-1,-1),))]:
    a,ar=control.render(raw,width,height,dpr,tiles)
    for candidate in candidates:
        c,cr=candidate.render(raw,width,height,dpr,tiles)
        assert len(a)==len(c)
        for (ta,ia),(tc,ic) in zip(a,c,strict=True):assert ta==tc and digest(ia)==digest(ic)
        rows.append({'variant':candidate.variant,'spec':[width,height,dpr],'tiles':tiles,'exact_pixels':True,'cache_record':cr})
control.close()
for candidate in candidates:candidate.close()
cpu=CpuRaster('cpu4');a,_=cpu.render(raw,630,891,1.5);c,_=cpu.render(raw,630,891,1.5)
reference=QtGui.QImage(a[0][1].width(),a[0][1].height(),a[0][1].format());reference.setDevicePixelRatio(1.5);reference.fill(QtCore.Qt.GlobalColor.white)
p=QtGui.QPainter(reference);QtSvg.QSvgRenderer(raw).render(p,QtCore.QRectF(0,0,630,891));p.end()
assert digest(a[0][1])==digest(reference)==digest(c[0][1]);cpu.close()
b.save('validation.json',{'scheduling_cases':schedule,'gpu_reused_vs_stencil_control':rows,
    'cpu_cached_pixels_exact_original_qtsvg':True,'completion':'all hashes after actual pixel readback',
    'production_source_mutated':False})
print('7 scheduling cases, 10 GPU sequences with tiled reuse, CPU cache pixel invariance passed',flush=True)
