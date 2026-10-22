"""Bounded QtSvg screen renderers; never own authoritative document geometry."""
import hashlib
from collections import OrderedDict

from PySide6 import QtCore, QtGui, QtSvg


class CpuRaster:
    backend = 'cpu'

    def __init__(self):
        self.renderers = OrderedDict()

    def svg(self, raw):
        key = hashlib.sha256(raw).digest()
        if key in self.renderers:
            self.renderers.move_to_end(key)
            return self.renderers[key][0]
        renderer = QtSvg.QSvgRenderer(raw)
        if not renderer.isValid():
            raise ValueError('无法读取页面预览')
        self.renderers[key] = (renderer, len(raw))
        while len(self.renderers) > 4 or sum(v[1] for v in self.renderers.values()) > 32 * 1024**2:
            self.renderers.popitem(last=False)
        return renderer

    def image(self, renderer, width, height, dpr, x, y, w, h):
        image = QtGui.QImage(w, h, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        if image.isNull():
            raise ValueError('页面预览图像分配失败')
        image.setDevicePixelRatio(dpr)
        image.fill(QtCore.Qt.GlobalColor.white)
        painter = QtGui.QPainter(image)
        try:
            painter.translate(-x / dpr, -y / dpr)
            renderer.render(painter, QtCore.QRectF(0, 0, width, height))
        finally:
            painter.end()
        return image

    def close(self):
        self.renderers.clear()


class GpuRaster(CpuRaster):
    backend = 'gpu'

    def __init__(self):
        super().__init__()
        from PySide6 import QtOpenGL
        self.gl = QtOpenGL
        self.targets = OrderedDict()
        self.target_bytes = 0
        self.context = QtGui.QOpenGLContext()
        if not self.context.create():
            raise ValueError('GPU 预览上下文不可用')
        self.surface = QtGui.QOffscreenSurface()
        self.surface.setFormat(self.context.format())
        self.surface.create()
        self.current()
        self.functions = self.context.functions()
        self.renderer_name = str(self.functions.glGetString(0x1F01))
        if any(s in self.renderer_name.lower() for s in ('llvmpipe', 'softpipe', 'software', 'gdi generic')):
            raise ValueError('当前 OpenGL 为软件实现')
        self.max_size = self.functions.glGetIntegerv(0x84E8)  # GL_MAX_RENDERBUFFER_SIZE
        # Warm shaders before the first page, while document loading runs in GUI.
        self.image(self.svg(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M1 1L19 19" stroke="black"/></svg>'),
                   20, 20, 1, 0, 0, 20, 20)

    def current(self):
        if not self.context.isValid() or not self.context.makeCurrent(self.surface):
            raise ValueError('GPU 预览设备不可用')

    def image(self, renderer, width, height, dpr, x, y, w, h):
        self.current()
        if max(w, h) > self.max_size:
            raise ValueError('GPU 预览尺寸超出设备能力')
        key = (w, h)
        # Count colour + depth/stencil MSAA8 + resolved image conservatively.
        weight = w * h * 4 * 17
        if weight > 384 * 1024**2:
            raise ValueError('GPU 预览显存预算不足')
        if key not in self.targets:
            while self.targets and self.target_bytes + weight > 384 * 1024**2:
                _, old = self.targets.popitem(last=False)
                self.target_bytes -= old[2]
                del old
            fmt = self.gl.QOpenGLFramebufferObjectFormat()
            fmt.setSamples(8)
            fmt.setAttachment(self.gl.QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            fbo = self.gl.QOpenGLFramebufferObject(w, h, fmt)
            if (not fbo.isValid() or fbo.format().samples() != 8
                    or fbo.attachment() != self.gl.QOpenGLFramebufferObject.Attachment.CombinedDepthStencil):
                raise ValueError('GPU 预览不支持所需抗锯齿或模板缓冲')
            self.targets[key] = (fbo, self.gl.QOpenGLPaintDevice(w, h), weight)
            self.target_bytes += weight
        self.targets.move_to_end(key)
        fbo, device, _ = self.targets[key]
        if not fbo.bind():
            raise ValueError('GPU 预览目标不可用')
        device.setDevicePixelRatio(dpr)
        painter = QtGui.QPainter(device)
        try:
            if not painter.isActive():
                raise ValueError('GPU 预览绘制器不可用')
            painter.fillRect(QtCore.QRectF(0, 0, w / dpr, h / dpr), QtCore.Qt.GlobalColor.white)
            painter.translate(-x / dpr, -y / dpr)
            renderer.render(painter, QtCore.QRectF(0, 0, width, height))
        finally:
            painter.end()
        # toImage is compulsory completed readback, not asynchronous submission.
        image = fbo.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        fbo.release()
        if image.isNull() or image.size() != QtCore.QSize(w, h):
            raise ValueError('GPU 预览像素读回失败')
        image.setDevicePixelRatio(dpr)
        return image

    def close(self):
        if self.context.isValid() and self.context.makeCurrent(self.surface):
            self.targets.clear()
            self.context.doneCurrent()
        super().close()
