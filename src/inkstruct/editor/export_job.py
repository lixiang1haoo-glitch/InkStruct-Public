"""One immutable export in a background thread, with owned routing child processes."""
from __future__ import annotations

import time

from PySide6 import QtCore, QtWidgets

from ..plotter.export import export_plan
from ..plotter.parallel import ExportCancelled, ExportControl, PageRouter


class ExportJob(QtCore.QThread):
    progress = QtCore.Signal(str, int, int)

    def __init__(self, plan, output, *, optimize, export_scope, page_indices, route_cache, parent=None):
        super().__init__(parent)
        self.plan, self.output = plan, output
        self.arguments = {'optimize': optimize, 'export_scope': export_scope,
                          'page_indices': page_indices, 'route_cache': route_cache}
        self.control = ExportControl()
        self.router = PageRouter()

    def run(self):
        started = time.monotonic()
        result = {'output': str(self.output), 'snapshot_id': self.plan.snapshot_id,
                  'cancelled': False, 'error': None}
        try:
            export_plan(self.plan, self.output, **self.arguments, routing=self.router,
                        control=self.control, progress=self.progress.emit)
        except ExportCancelled:
            result['cancelled'] = True
        except Exception as error:  # noqa: BLE001 -- keep GUI alive and report all export failures.
            result['error'] = f'{type(error).__name__}: {error}'
        result.update(seconds=time.monotonic() - started, routing=dict(self.router.statistics))
        self.result = result
        # Delivered only by QThread.finished after run() has actually returned.


class ExportProgress(QtWidgets.QDialog):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self.setWindowTitle('正在导出 SVG')
        self.setMinimumWidth(440)
        self.setModal(False)
        layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel('正在导出已确认的冻结排版；可继续编辑和滚动。')
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 0)
        layout.addWidget(self.bar)
        self.cancel_button = QtWidgets.QPushButton('取消导出')
        self.cancel_button.clicked.connect(self.cancel)
        layout.addWidget(self.cancel_button)
        job.progress.connect(self.update_progress)

    def update_progress(self, stage, done, total):
        if self.job.control.cancelled.is_set():
            return
        names = {'route': '优化路径', 'write': '写出页面', 'fallback': '并行不可用，串行重算未完成页'}
        self.label.setText(f'{names[stage]}：{done}/{total} 页。使用已冻结排版，可继续编辑。')
        self.bar.setRange(0, max(1, total * 2))
        self.bar.setValue(done + (total if stage == 'write' else 0))

    def cancel(self):
        if self.job.control.cancel():
            self.label.setText('正在取消并清理临时输出；当前文档不会改变。')
            self.cancel_button.setEnabled(False)

    def reject(self):
        self.cancel()

    def closeEvent(self, event):
        if self.job.isRunning():
            self.cancel()
            event.ignore()
        else:
            event.accept()
