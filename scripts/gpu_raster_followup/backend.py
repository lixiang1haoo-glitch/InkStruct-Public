"""Same-resolution MSAA8 raster variants; all completion includes pixel readback."""
from collections import OrderedDict
import hashlib
import time
from PySide6 import QtCore,QtGui,QtSvg,QtOpenGL

class Raster:
    def __init__(self,variant):
        self.variant=variant;self.targets=OrderedDict();self.renderers=OrderedDict()
        self.target_budget=384*1024**2;self.target_bytes=0
        t=time.perf_counter();self.context=QtGui.QOpenGLContext();assert self.context.create()
        self.surface=QtGui.QOffscreenSurface();self.surface.setFormat(self.context.format());self.surface.create()
        assert self.context.makeCurrent(self.surface)
        self.functions=self.context.functions();self.context_s=time.perf_counter()-t
        self.renderer=str(self.functions.glGetString(0x1F01))
        self.cached=variant in ('cached','cached4','resolve','picture')
        self.pooled=variant in ('pooled','cached','cached4','resolve','picture')
        self.renderer_limit=4 if variant=='cached4' else 2
        self.resolved=variant=='resolve'
        self.stencil=variant!='old'

    def target(self,w,h):
        key=(w,h)
        if self.pooled and key in self.targets:
            self.targets.move_to_end(key);return self.targets[key],True
        # Colour MSAA + packed depth/stencil MSAA + resolve conservative budget.
        weight=w*h*4*(17 if self.stencil else 9)
        while self.targets and self.target_bytes+weight>self.target_budget:
            _,old=self.targets.popitem(last=False);self.target_bytes-=old['weight']
            del old
        fmt=QtOpenGL.QOpenGLFramebufferObjectFormat();fmt.setSamples(8)
        if self.stencil:fmt.setAttachment(QtOpenGL.QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
        fbo=QtOpenGL.QOpenGLFramebufferObject(w,h,fmt);assert fbo.isValid()
        resolve=QtOpenGL.QOpenGLFramebufferObject(w,h) if self.resolved else None
        item={'fbo':fbo,'resolve':resolve,'device':QtOpenGL.QOpenGLPaintDevice(w,h),'weight':weight}
        if self.pooled and weight<=self.target_budget:
            self.targets[key]=item;self.target_bytes+=weight
        return item,False

    def svg(self,raw,width,height):
        t=time.perf_counter();digest=hashlib.sha256(raw).hexdigest();hash_s=time.perf_counter()-t
        key=(digest,width,height) if self.variant=='picture' else digest
        if self.cached and key in self.renderers:
            self.renderers.move_to_end(key);return self.renderers[key],True,hash_s,0.,0.
        t=time.perf_counter();svg=QtSvg.QSvgRenderer(raw);assert svg.isValid();parse_s=time.perf_counter()-t
        picture=None;record_s=0.
        if self.variant=='picture':
            t=time.perf_counter();picture=QtGui.QPicture();p=QtGui.QPainter(picture)
            svg.render(p,QtCore.QRectF(0,0,width,height));p.end();record_s=time.perf_counter()-t
        item={'svg':svg,'picture':picture,'raw_bytes':len(raw)}
        if self.cached:
            self.renderers[key]=item
            while len(self.renderers)>self.renderer_limit or sum(x['raw_bytes'] for x in self.renderers.values())>32*1024**2:
                self.renderers.popitem(last=False)
        return item,False,hash_s,parse_s,record_s

    def render(self,raw,width,height,dpr,tiles=((-1,-1),)):
        import math
        start=time.perf_counter();assert self.context.makeCurrent(self.surface)
        record={'variant':self.variant,'stencil':self.stencil,'renderer':self.renderer}
        svg,hit,hash_s,parse_s,record_s=self.svg(raw,width,height)
        record.update(renderer_hit=hit,hash_s=hash_s,svg_parse_s=parse_s,picture_record_s=record_s)
        pw,ph=math.ceil(width*dpr),math.ceil(height*dpr);images=[];parts=[]
        for col,row in tiles:
            x,y=(0,0) if (col,row)==(-1,-1) else (col*512,row*512)
            w,h=(pw,ph) if (col,row)==(-1,-1) else (min(512,pw-x),min(512,ph-y))
            assert 0<w*h*4<=40*1024**2
            t=time.perf_counter();target,target_hit=self.target(w,h);fbo=target['fbo'];assert fbo.bind()
            device=target['device'];device.setDevicePixelRatio(dpr);alloc=time.perf_counter()-t
            t=time.perf_counter();p=QtGui.QPainter(device);engine=str(p.paintEngine().type())
            p.fillRect(QtCore.QRectF(0,0,w/dpr,h/dpr),QtCore.Qt.GlobalColor.white)
            p.translate(-x/dpr,-y/dpr)
            if svg['picture'] is None:svg['svg'].render(p,QtCore.QRectF(0,0,width,height))
            else:p.drawPicture(QtCore.QPointF(0,0),svg['picture'])
            p.end();submitted=time.perf_counter()-t
            t=time.perf_counter()
            # Original/correct controls use explicit glFinish. Optimized paths
            # synchronize through the compulsory completed image readback.
            if not self.pooled:self.functions.glFinish()
            barrier=time.perf_counter()-t;t=time.perf_counter()
            if self.resolved:
                QtOpenGL.QOpenGLFramebufferObject.blitFramebuffer(target['resolve'],fbo)
                image=target['resolve'].toImage()
            else:image=fbo.toImage()
            completed=time.perf_counter()-t;t=time.perf_counter()
            image=image.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr);conversion=time.perf_counter()-t;fbo.release()
            images.append(((col,row),image))
            parts.append({'target_hit':target_hit,'allocate_bind_s':alloc,'draw_submit_s':submitted,
                'explicit_barrier_s':barrier,'completed_readback_s':completed,'convert_s':conversion,
                'samples':fbo.format().samples(),'attachment':str(fbo.attachment()),'paint_engine':engine,'pixels':[w,h]})
        record.update(tiles=parts,total_to_completed_image_s=time.perf_counter()-start,
                      target_budget_estimate_bytes=self.target_bytes,renderer_entries=len(self.renderers))
        return images,record

    def warm(self):
        t=time.perf_counter()
        raw=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M1 1L19 19M1 19L19 1" stroke="black" fill="none"/></svg>'
        self.render(raw,20,20,1.)
        return time.perf_counter()-t

    def close(self):
        self.context.makeCurrent(self.surface);self.renderers.clear();self.targets.clear()
        self.context.doneCurrent()

class CpuRaster(Raster):
    """CPU renderer cache is a fair optimized control; no GL context exists."""
    def __init__(self,variant='cpu'):
        self.variant=variant;self.cached=True;self.renderers=OrderedDict()
        self.renderer_limit=4 if variant=='cpu4' else 2
        self.renderer='CPU QtSvg QImage';self.context_s=0.
    def render(self,raw,width,height,dpr,tiles=((-1,-1),)):
        import math
        start=time.perf_counter();svg,hit,hash_s,parse_s,record_s=self.svg(raw,width,height)
        pw,ph=math.ceil(width*dpr),math.ceil(height*dpr);images=[];parts=[]
        for col,row in tiles:
            x,y=(0,0) if (col,row)==(-1,-1) else (col*512,row*512)
            w,h=(pw,ph) if (col,row)==(-1,-1) else (min(512,pw-x),min(512,ph-y))
            assert 0<w*h*4<=40*1024**2
            t=time.perf_counter();image=QtGui.QImage(w,h,QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr);image.fill(QtCore.Qt.GlobalColor.white);alloc=time.perf_counter()-t
            t=time.perf_counter();p=QtGui.QPainter(image);engine=str(p.paintEngine().type());p.translate(-x/dpr,-y/dpr)
            svg['svg'].render(p,QtCore.QRectF(0,0,width,height));p.end();draw=time.perf_counter()-t
            images.append(((col,row),image));parts.append({'allocate_bind_s':alloc,'draw_submit_s':draw,'paint_engine':engine,'pixels':[w,h]})
        return images,{'variant':'cpu','renderer':self.renderer,'renderer_hit':hit,'hash_s':hash_s,'svg_parse_s':parse_s,
            'tiles':parts,'total_to_completed_image_s':time.perf_counter()-start,'renderer_entries':len(self.renderers)}
    def close(self):self.renderers.clear()
