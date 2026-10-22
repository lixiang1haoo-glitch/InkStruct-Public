import os
import subprocess
import sys


def test_cpu_cache_pixel_identity_and_whole_request_gpu_fallback(tmp_path):
    program = r'''
from PySide6 import QtGui,QtCore,QtSvg
from inkstruct.editor.preview_backend import CpuRaster
from inkstruct.editor.preview_raster_worker import RasterService
a=QtGui.QGuiApplication([])
raw=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M2 2L18 18" stroke="black" fill="none"/></svg>'
cpu=CpuRaster();svg=cpu.svg(raw);assert cpu.svg(raw) is svg
expected=cpu.image(svg,100,100,1.5,0,0,150,150)
legacy=QtGui.QImage(150,150,expected.format());legacy.setDevicePixelRatio(1.5);legacy.fill(QtCore.Qt.white)
p=QtGui.QPainter(legacy);QtSvg.QSvgRenderer(raw).render(p,QtCore.QRectF(0,0,100,100));p.end()
assert bytes(expected.constBits())==bytes(legacy.constBits())
for i in range(8):cpu.svg(raw.replace(b'black',str(i).encode()))
assert len(cpu.renderers)==4
class Failing:
 def __init__(self):self.calls=0;self.closed=False
 def svg(self,raw):return cpu.svg(raw)
 def image(self,*args):
  self.calls+=1
  if self.calls==2:raise RuntimeError('device lost')
  result=expected.copy();result.fill(QtCore.Qt.red);return result
 def close(self):self.closed=True
service=RasterService();fake=Failing();service.gpu=fake
images=service.images(raw,(100,100,1.5),[(0,0,150,150),(0,0,150,150)])
assert service.gpu is None and fake.closed and service.fallback=='device lost'
assert all(bytes(i.constBits())==bytes(expected.constBits()) for i in images)
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', program],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
