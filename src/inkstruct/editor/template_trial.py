"""Isolated asynchronous trial layout; never mutates document resources or choices."""

import copy
import threading
from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from ..assets.resolver import AssetResolver
from ..document.editing import SourceSession
from ..document.markdown import parse_markdown
from ..document.styles import FlowStyle
from ..layout.blocks import layout_markdown


class TrialSignals(QtCore.QObject):
    completed = QtCore.Signal(object)


class TrialWorker(QtCore.QRunnable):
    def __init__(self, template, editor=None):
        super().__init__()
        self.signals = TrialSignals()
        self.cancel = threading.Event()
        self.session = copy.copy(editor.source_session) if editor else SourceSession("123\n\n456")
        self.resolver = (
            AssetResolver(
                embedded=tuple(g for pool in editor.resolver.pools.values() for g in pool),
                seed=editor.resolver.seed,
                selections=tuple(editor.resolver.selections.values()),
            )
            if editor
            else AssetResolver(builtin_numbers=True)
        )
        self.flow = replace(editor.flow if editor else FlowStyle(), template=template)
        self.style = editor.style if editor else None
        self.page = editor.page if editor else None

    def run(self):
        try:
            document = parse_markdown(
                self.session, field_blocks=self.flow.named_fields, cancelled=self.cancel
            )
            snapshot = layout_markdown(
                document,
                self.resolver,
                flow=self.flow,
                style=self.style,
                page=self.page,
                cancelled=self.cancel,
            )
            self.signals.completed.emit((document, snapshot))
        except Exception as error:  # noqa: BLE001 -- report worker failures to the GUI, never publish a partial trial.
            self.signals.completed.emit(str(error))


class TemplateTrialDialog(QtWidgets.QDialog):
    def __init__(self, template, editor=None, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.selected_diagnostic = None
        self.snapshot = None
        self.setWindowTitle("当前文档试排" if editor else "示例预览 · 不代表当前文档适配")
        self.resize(1000, 740)
        col = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel(
            "正在使用当前文档的真实内容与冻结字体试排，可取消…"
            if editor
            else "使用内置数字演示页面版式。"
        )
        self.summary.setWordWrap(True)
        col.addWidget(self.summary)
        self.picker = QtWidgets.QComboBox()
        self.picker.currentIndexChanged.connect(self.show_page)
        col.addWidget(self.picker)
        splitter = QtWidgets.QSplitter()
        from .template_viewport import FitSvgPreview

        self.preview = FitSvgPreview()
        splitter.addWidget(self.preview)
        self.issues = QtWidgets.QTreeWidget()
        self.issues.setHeaderLabels(["级别", "问题"])
        self.issues.setColumnWidth(0, 55)
        splitter.addWidget(self.issues)
        splitter.setSizes([650, 330])
        col.addWidget(splitter, 1)
        row = QtWidgets.QHBoxLayout()
        self.locate = QtWidgets.QPushButton("定位所选问题")
        self.locate.setEnabled(False)
        self.locate.clicked.connect(self.locate_issue)
        row.addWidget(self.locate)
        row.addStretch()
        b = QtWidgets.QPushButton("返回编辑")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        col.addLayout(row)
        self.worker = TrialWorker(template, editor)
        self.worker.signals.completed.connect(self.receive)
        QtCore.QThreadPool.globalInstance().start(self.worker)

    def receive(self, result):
        if self.worker.cancel.is_set():
            return
        if isinstance(result, str):
            self.summary.setText("试排未完成：" + result)
            return
        document, self.snapshot = result
        from ..document.template_fit import template_fit_report

        report = template_fit_report(document, self.worker.flow, self.snapshot)
        counts = report["severity_counts"]
        self.summary.setText(
            ("当前文档真实试排" if self.editor else "示例预览")
            + f" · {len(self.snapshot.pages)} 页 · {counts.get('error', 0)} 项错误 · {counts.get('warning', 0)} 项提醒。"
        )
        for page in self.snapshot.pages:
            self.picker.addItem(f"第 {page.index + 1} 页 · {page.source_layout or '页面'}")
        for diagnostic in self.snapshot.diagnostics:
            item = QtWidgets.QTreeWidgetItem(
                ["错误" if diagnostic.severity == "error" else "提醒", diagnostic.message]
            )
            item.setData(0, QtCore.Qt.UserRole, diagnostic)
            item.setToolTip(1, diagnostic.code)
            self.issues.addTopLevelItem(item)
        self.locate.setEnabled(bool(self.snapshot.diagnostics))
        self.show_page(0)

    def show_page(self, index):
        if self.snapshot and 0 <= index < len(self.snapshot.pages):
            from ..renderers.pages import page_svg

            self.preview.show_svg(
                page_svg(self.snapshot, index, debug=not self.snapshot.exportable).encode()
            )

    def locate_issue(self):
        item = self.issues.currentItem()
        if item:
            self.selected_diagnostic = item.data(0, QtCore.Qt.UserRole)
            self.accept()

    def reject(self):
        self.worker.cancel.set()
        super().reject()
