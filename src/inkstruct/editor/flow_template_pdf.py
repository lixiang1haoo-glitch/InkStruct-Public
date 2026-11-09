"""Multi-page PDF reference import with one immutable, cancellable PDF process."""

from dataclasses import replace
from uuid import uuid4

from PySide6 import QtCore, QtWidgets

from ..document.flow_template import PageLayout, TextFrame
from ..document.template import Region, TemplateBackground
from .template_pdf_process import PdfProcess


def selected_pages(text, count):
    values = []
    for part in text.replace("，", ",").split(","):
        if "-" in part:
            a, b = part.strip().split("-")
            a, b = int(a), int(b)
            if a > b or b - a >= 64:
                raise ValueError("页码范围无效或超过 64 页")
            values.extend(range(a, b + 1))
        else:
            values.append(int(part.strip()))
    if not values or len(values) > 64 or min(values) < 1 or max(values) > count:
        raise ValueError("请选择 PDF 范围内的 1–64 个页面")
    if len(set(values)) != len(values):
        raise ValueError("导入页码不能重复；重复使用可在页组中配置")
    return values


def imported_template(template, results, source_hash, *, adopt_size=False, group="loop_pages",
                      mode="append", initial_blank=None):
    if not results:
        raise ValueError("没有可导入页面")
    if group not in {"start_pages", "loop_pages"} or mode not in {"append", "replace"}:
        raise ValueError("PDF 导入的页组或操作无效")
    width, height = results[0]["size_mm"] if adopt_size else (template.width_mm, template.height_mm)
    layouts = []
    for r in results:
        key = "pdf-" + uuid4().hex[:16]
        margin = min(20, width / 8, height / 8)
        frame = TextFrame(
            "body",
            "正文框 1",
            Region("body", margin, margin, width - 2 * margin, height - 2 * margin),
        )
        layouts.append(
            PageLayout(
                key,
                f"PDF 第 {r['index'] + 1} 页",
                (frame,),
                background=TemplateBackground(**r["background"]),
                source_page=r["index"] + 1,
                source_sha256=source_hash,
                source_size_mm=tuple(r["size_mm"]),
            )
        )
    new_ids = tuple(p.layout_id for p in layouts)
    sequence = (*getattr(template, group), *new_ids) if mode == "append" else new_ids
    other = "start_pages" if group == "loop_pages" else "loop_pages"
    referenced = {*sequence, *getattr(template, other)}
    retained = tuple(p for p in template.layouts if not (
        mode == "replace" and p == initial_blank and p.layout_id not in referenced
        and not (p.frames or p.rules or p.background)
    ))
    return replace(
        template,
        kind="custom",
        width_mm=width,
        height_mm=height,
        layouts=(*retained, *layouts),
        **{group: sequence},
    )


class PdfPagesDialog(QtWidgets.QDialog):
    def __init__(self, path, template, parent=None, *, initial_blank=None):
        super().__init__(parent)
        self.template = template
        self.initial_blank = initial_blank
        self.candidate = None
        self.results = []
        self.queue = []
        self.count = 0
        self.source_hash = ""
        self.pdf = PdfProcess(self)
        self.pdf.completed.connect(self.receive)
        self.pdf.failed.connect(self.fail)
        self.setWindowTitle("导入 PDF 页面版式")
        self.resize(670, 450)
        form = QtWidgets.QFormLayout(self)
        self.summary = QtWidgets.QLabel("正在读取 PDF，可取消…")
        self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.pages = QtWidgets.QLineEdit("1")
        self.pages.setPlaceholderText("例如 1-4 或 1,3,4；顺序保留")
        form.addRow("页码与顺序", self.pages)
        self.adopt = QtWidgets.QCheckBox("采用首个所选 PDF 页的物理纸张尺寸")
        self.adopt.setChecked(initial_blank is not None)
        form.addRow(self.adopt)
        self.group = QtWidgets.QComboBox()
        self.group.addItem("循环页组", "loop_pages")
        self.group.addItem("起始页组", "start_pages")
        form.addRow("目标页组", self.group)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("追加到页组", "append")
        self.mode.addItem("替换整个页组", "replace")
        self.mode.setCurrentIndex(1 if initial_blank is not None else 0)
        form.addRow("导入方式", self.mode)
        note = QtWidgets.QLabel(
            "采用新尺寸会调整整份模板的纸张。背景按宽高铺满，已有框仍按原毫米坐标定位，越界会阻止确认。PDF 底图只用于参考。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.load = QtWidgets.QPushButton("读取所选页面")
        self.load.clicked.connect(self.start_render)
        form.addRow(self.load)
        self.error = QtWidgets.QLabel()
        self.error.setTextFormat(QtCore.Qt.PlainText)
        self.error.setWordWrap(True)
        form.addRow(self.error)
        self.impact = QtWidgets.QPlainTextEdit()
        self.impact.setReadOnly(True)
        self.impact.setMinimumHeight(100)
        self.impact.setAccessibleName("PDF 导入影响")
        form.addRow(self.impact)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.pages.textChanged.connect(self.invalidate)
        self.adopt.toggled.connect(self.invalidate)
        self.group.currentIndexChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self.invalidate)
        self.set_busy(True)
        self.pdf.request({"action": "open", "path": str(path)})

    def set_busy(self, busy):
        for w in (self.pages, self.adopt, self.group, self.mode, self.load):
            w.setEnabled(not busy)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(
            not busy and self.candidate is not None
        )

    def invalidate(self, *_):
        self.candidate = None
        self.impact.clear()
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def start_render(self):
        try:
            self.queue = selected_pages(self.pages.text(), self.count)
            self.results = []
            self.candidate = None
            self.invalidate()
            self.set_busy(True)
            self.error.setText("正在渲染所选页面，可随时取消…")
            self.next_page()
        except (ValueError, TypeError) as error:
            self.fail(str(error))

    def next_page(self):
        if self.queue:
            self.pdf.request({"action": "render", "index": self.queue.pop(0) - 1})
        else:
            try:
                group, mode = self.group.currentData(), self.mode.currentData()
                old_sequence = getattr(self.template, group)
                self.candidate = imported_template(
                    self.template,
                    self.results,
                    self.source_hash,
                    adopt_size=self.adopt.isChecked(), group=group, mode=mode,
                    initial_blank=self.initial_blank,
                )
                names = {p.layout_id: p.label for p in self.template.layouts}
                removed = " → ".join(names[key] for key in old_sequence) if mode == "replace" else ""
                self.impact.setPlainText(
                    f"目标：{self.group.currentText()} · {self.mode.currentText()}\n"
                    f"导入顺序：{' → '.join(str(r['index'] + 1) for r in self.results)}\n"
                    f"从目标页组移出：{removed or '无'}\n"
                    f"整份模板纸张：{self.template.width_mm:.4g} × {self.template.height_mm:.4g} mm → "
                    f"{self.candidate.width_mm:.4g} × {self.candidate.height_mm:.4g} mm"
                )
                if self.initial_blank is not None and self.initial_blank not in self.candidate.layouts:
                    self.impact.appendPlainText("自动清理：未编辑且已无引用的初始空白版式。")
                self.error.setText("页面已读取。确定后应用，可在工作台撤销。")
                self.set_busy(False)
            except (ValueError, TypeError) as error:
                self.fail(str(error))

    def receive(self, result):
        if result["action"] == "open":
            self.count = result["page_count"]
            self.source_hash = result["source_sha256"]
            self.summary.setText(f"PDF 共 {self.count} 页。请明确选择页码，最多 64 页。")
            self.pages.setText("1-" + str(min(4, self.count)) if self.count > 1 else "1")
            self.set_busy(False)
        else:
            self.results.append(result)
            self.next_page()

    def fail(self, message):
        self.candidate = None
        self.impact.clear()
        self.error.setText(message)
        self.set_busy(False)
        if self.pdf.closed:
            self.load.setEnabled(False)

    def close_worker(self):
        self.pdf.close()

    def accept(self):
        if self.candidate is not None and not self.pdf.pending:
            self.close_worker()
            super().accept()

    def reject(self):
        self.close_worker()
        super().reject()

    def closeEvent(self, event):
        self.close_worker()
        super().closeEvent(event)
