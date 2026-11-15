"""Bounded asynchronous preview process and private pixel hand-off files."""
import json
import math
import sys
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

from PySide6 import QtCore, QtGui

from .preview_wire import VERSION

PAGE_FILES = 8
PAGE_BYTES = 96 * 1024**2


def worker_command(directory):
    if getattr(sys, 'frozen', False):
        tool = Path(sys.executable).with_name('InkStructTool.exe' if sys.platform == 'win32'
                                              else 'InkStructTool')
        if not tool.is_file():
            raise ValueError('预览工作进程缺失，请重新解压完整应用包')
        return [str(tool), '--inkstruct-preview-worker', str(directory)]
    return [sys.executable, '-m', 'inkstruct.editor.preview_raster_worker', str(directory)]


class PreviewProcess(QtCore.QObject):
    completed = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.temporary = tempfile.TemporaryDirectory(prefix='inkstruct-preview-')
        self.directory = Path(self.temporary.name)
        self.token = 0
        self.pending = None
        self.pages = OrderedDict()
        self.page_bytes = 0
        self.buffer = bytearray()
        self.closed = False
        from ..global_defaults import GlobalDefaultsStore
        self.backend = GlobalDefaultsStore.make_settings().value('preview_backend_v1', 'cpu', str)
        if self.backend not in ('cpu', 'gpu'):
            self.backend = 'cpu'
        self.fallback_reason = None
        self.retried = False
        self.process = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert('QT_QPA_PLATFORM', 'windows' if self.backend == 'gpu' and sys.platform == 'win32' else 'offscreen')
        env.insert('INKSTRUCT_PREVIEW_BACKEND', self.backend)
        self.process.setProcessEnvironment(env)
        self.process.readyReadStandardOutput.connect(self.read_result)
        self.process.readyReadStandardError.connect(self.process.readAllStandardError)
        self.process.errorOccurred.connect(lambda *_: self.fail('页面预览进程无法启动'))
        self.process.finished.connect(lambda *_: self.fail('页面预览进程意外退出'))
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(lambda: self.fail('页面预览绘制超时'))

    def prewarm(self):
        if not self.closed and self.process.state() == QtCore.QProcess.ProcessState.NotRunning:
            try:
                command = worker_command(self.directory)
                self.process.start(command[0], command[1:])
            except (ValueError, OSError) as error:
                self.fail(str(error))

    def prepare_path(self, page_id):
        self.token += 1
        size = self.pages.get(page_id, 0)
        if size:
            self.pages.move_to_end(page_id)
        return self.token, self.directory / f'page-{page_id}.bin', size

    def remember_page(self, page_id, size):
        self.page_bytes += size
        self.pages[page_id] = size
        while self.page_bytes > PAGE_BYTES or len(self.pages) > PAGE_FILES:
            evicted, old_size = self.pages.popitem(last=False)
            self.page_bytes -= old_size
            (self.directory / f'page-{evicted}.bin').unlink(missing_ok=True)

    def cancel(self, token):
        if self.pending is not None and self.pending['token'] == token:
            try:
                (self.directory / f'{token}.cancel').touch(exist_ok=True)
            except OSError:
                pass  # The receiving canvas still rejects the cancelled result.

    def render(self, result, tiles):
        self.pending = result
        self.timer.start()
        try:
            if self.process.state() == QtCore.QProcess.ProcessState.NotRunning:
                self.prewarm()
            result['sent_at'] = time.perf_counter()
            request = {'version': VERSION, 'token': result['token'], 'page': result['page_id'],
                       'spec': result['spec'], 'accelerate': result['render_key'][2], 'tiles': tiles}
            if self.process.write(json.dumps(request).encode() + b'\n') < 0:
                raise OSError('无法发送页面预览请求')
        except (ValueError, OSError) as error:
            self.fail(str(error))

    def read_result(self):
        if self.closed:
            return
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > 65536:
            self.fail('页面预览进程返回超限数据')
            return
        if b'\n' not in self.buffer or not self.pending:
            return
        received = time.perf_counter()
        raw, _, rest = self.buffer.partition(b'\n')
        self.buffer = bytearray(rest)
        result = self.pending
        try:
            response = json.loads(raw)
            if type(response['token']) is not int or response['token'] != result['token']:
                raise ValueError('页面预览进程返回过期标识')
            if result['cancel_event'].is_set():
                self._finish(result)
                return
            if response.get('cancelled'):
                raise ValueError('页面预览进程意外取消')
            if 'error' in response:
                raise ValueError(response['error'])
            images = response['images']
            if not isinstance(images, list) or not 1 <= len(images) <= 32:
                raise ValueError('页面预览图像数量无效')
            returned = [tuple(item['tile']) for item in images]
            if len(set(returned)) != len(returned) or set(returned) != set(result['tiles']):
                raise ValueError('页面预览分块结果不完整')
            for item in images:
                col, row = item['tile']
                if (col, row) not in result['tiles']:
                    raise ValueError('页面预览分块不属于当前请求')
                w, h, stride = item['width'], item['height'], item['stride']
                pw, ph = (math.ceil(v * result['spec'][2]) for v in result['spec'][:2])
                expected = (pw, ph) if (col, row) == (-1, -1) else (
                    min(512, pw - col * 512), min(512, ph - row * 512))
                if (w, h) != expected:
                    raise ValueError('页面预览图像与当前缩放不符')
                if any(type(v) is not int or v < 1 for v in (w, h, stride)):
                    raise ValueError('页面预览图像尺寸无效')
                if stride != w * 4 or stride * h != item['bytes'] or item['bytes'] > 40 * 1024**2:
                    raise ValueError('页面预览图像字节数无效')
                path = self.directory / f"{result['token']}-{col}-{row}.argb"
                if path.stat().st_size != item['bytes']:
                    raise ValueError('页面预览图像不完整')
                pixels = path.read_bytes()
                image = QtGui.QImage(pixels, w, h, stride,
                                     QtGui.QImage.Format.Format_ARGB32_Premultiplied).copy()
                image.setDevicePixelRatio(result['spec'][2])
                result['images'].append(((col, row), image))
                path.unlink()
            for key in ('decode_seconds', 'svg_seconds', 'raster_seconds'):
                elapsed = response[key]
                if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                    raise ValueError('页面预览进程返回无效计时')
                result[key] = elapsed
            result['page_reused'] = response['page_reused'] is True
            result['receive_seconds'] = time.perf_counter() - received
            result['ipc_seconds'] = max(0.0, time.perf_counter() - result['sent_at']
                                        - sum(result[key] for key in ('decode_seconds', 'svg_seconds', 'raster_seconds')))
            self.backend = response.get('backend', 'cpu')
            self.fallback_reason = response.get('gpu_fallback') or self.fallback_reason
        except (ValueError, OSError, KeyError, TypeError) as error:
            result['error'] = str(error)
        self._finish(result)

    def _finish(self, result):
        self.timer.stop()
        self.pending = None
        token = result['token']
        (self.directory / f'{token}.cancel').unlink(missing_ok=True)
        for col, row in result['tiles']:
            (self.directory / f'{token}-{col}-{row}.argb').unlink(missing_ok=True)
        self.completed.emit(result)

    def fail(self, message):
        if self.closed:
            return
        self.timer.stop()
        # Prevent kill/finished signals from delivering a second failure.
        result, self.pending = self.pending, None
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.process.blockSignals(True)
            self.process.kill()
            self.process.waitForFinished(1000)
            self.process.blockSignals(False)
        self.buffer.clear()
        if self.backend == 'gpu' and not self.retried:
            self.retried = True
            self.backend, self.fallback_reason = 'cpu', message
            env = self.process.processEnvironment()
            env.insert('QT_QPA_PLATFORM', 'offscreen')
            env.insert('INKSTRUCT_PREVIEW_BACKEND', 'cpu')
            self.process.setProcessEnvironment(env)
            if result and not result['cancel_event'].is_set():
                result['images'].clear()
                self.render(result, result['tiles'])
            else:
                if result is not None:
                    self._finish(result)
                self.prewarm()
            return
        if result:
            result['error'] = message
            self._finish(result)

    def close(self):
        self.closed = True
        self.timer.stop()
        self.pending = None
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        try:
            self.temporary.cleanup()
        except OSError:
            pass  # A cancelled page preparer will release its file shortly.
