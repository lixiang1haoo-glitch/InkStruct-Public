import common as b
import pickle
from PySide6 import QtCore,QtGui
from inkstruct.editor.preview_backend import CpuRaster
from inkstruct.renderers.pages import page_svg

app=QtGui.QGuiApplication([])
with (b.OUT/'baseline-result-v2.pickle').open('rb') as file:result=pickle.load(file)
raster=CpuRaster();rows=[]
for index in (0,5,10):
    raw=page_svg(result['snapshot'],index,debug=True).encode();svg=raster.svg(raw)
    for width,height,dpr in ((630,891,1.5),(945,1337,1.5)):
        import math
        w,h=math.ceil(width*dpr),math.ceil(height*dpr)
        control=raster.image(svg,width,height,dpr,0,0,w,h)
        tiled=QtGui.QImage(w,h,QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        tiled.fill(QtCore.Qt.GlobalColor.white)
        # Native compositor works in logical pixels at DPR; this comparison uses
        # device-pixel coordinates to avoid adding an extra scaling operation.
        painter=QtGui.QPainter(tiled)
        for y in range(0,h,512):
            for x in range(0,w,512):
                image=raster.image(svg,width,height,dpr,x,y,min(512,w-x),min(512,h-y))
                image.setDevicePixelRatio(1);painter.drawImage(x,y,image)
        painter.end()
        assert bytes(control.constBits())==bytes(tiled.constBits())
        rows.append({'page':index+1,'size':[width,height],'dpr':dpr,'pixels_exact':True})
b.save('tiling-validation.json',rows)
print('Six current CPU full-page / visible tile image comparisons exact')
