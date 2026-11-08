"""Bounded PDF subprocess lifecycle for desktop and command-line imports."""

import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6 import QtCore

MAX_MESSAGE_BYTES = 3 * 1024 * 1024
PDF_TIMEOUT_SECONDS = 30


def worker_command():
    if getattr(sys, "frozen", False):
        companion = Path(sys.executable).with_name(
            "InkStructTool.exe" if sys.platform == "win32" else "InkStructTool"
        )
        if not companion.is_file():
            raise ValueError("PDF 工作进程缺失，请重新解压完整应用包")
        return [str(companion), "--inkstruct-pdf-worker"]
    return [sys.executable, "-m", "inkstruct.editor.template_pdf_worker"]


def decode_response(raw):
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("PDF 导入结果超过限制")
    try:
        response = json.loads(raw)
        if not response["ok"]:
            raise ValueError(response["error"])
        return response["result"]
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("PDF 子进程返回无效结果") from error


def import_pdf(request, *, timeout=PDF_TIMEOUT_SECONDS):
    try:
        result = subprocess.run(
            worker_command(),
            input=json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n",
            capture_output=True,
            check=False,
            timeout=timeout,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("PDF 导入超时，已停止子进程；请尝试更简单的 PDF") from error
    if result.returncode:
        raise ValueError("PDF 子进程异常退出，未修改模板")
    return decode_response(result.stdout)


class PdfProcess(QtCore.QObject):
    completed = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, parent=None, *, timeout_ms=PDF_TIMEOUT_SECONDS * 1000):
        super().__init__(parent)
        self.closed = False
        self.pending = False
        self.buffer = bytearray()
        self.process = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("QT_QPA_PLATFORM", "offscreen")
        self.process.setProcessEnvironment(env)
        self.process.readyReadStandardOutput.connect(self.read_result)
        self.process.readyReadStandardError.connect(self.drain_error)
        self.process.errorOccurred.connect(self.process_error)
        self.process.finished.connect(self.finished)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(
            lambda: self.fail("PDF 导入超时，已停止子进程；请尝试更简单的 PDF")
        )

    def request(self, request):
        if self.closed or self.pending:
            return
        self.pending = True
        self.timer.start()
        try:
            if self.process.state() == QtCore.QProcess.NotRunning:
                command = worker_command()
                self.process.start(command[0], command[1:])
            self.process.write(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
        except (ValueError, OSError) as error:
            self.fail(str(error))

    def read_result(self):
        if self.closed:
            return
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > MAX_MESSAGE_BYTES:
            self.fail("PDF 导入结果超过限制")
            return
        if b"\n" not in self.buffer:
            return
        raw, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        try:
            result = decode_response(raw)
        except ValueError as error:
            self.fail(str(error))
            return
        self.timer.stop()
        self.pending = False
        self.completed.emit(result)

    def drain_error(self):
        self.process.readAllStandardError()

    def process_error(self, error):
        if not self.closed:
            self.fail("PDF 子进程无法启动或异常退出，未修改模板")

    def finished(self, *_):
        if not self.closed:
            self.fail("PDF 子进程提前退出，未修改模板")

    def fail(self, message):
        if not self.closed:
            self.close()
            self.failed.emit(message)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pending = False
        self.timer.stop()
        self.buffer.clear()
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.process.kill()
            # Kill is unconditional; bounded reap also prevents Qt ownership teardown races.
            self.process.waitForFinished(1000)
