"""Multi-page PDF reference import with one immutable, cancellable PDF process."""

from dataclasses import replace
from uuid import uuid4

from PySide6 import QtWidgets

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


def imported_template(template, results, source_hash, *, adopt_size=True, group="loop_pages"):
    if not results:
        raise ValueError("没有可导入页面")
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
    return replace(
        template,
        kind="custom",
        width_mm=width,
        height_mm=height,
        layouts=(*template.layouts, *layouts),
        **{group: tuple(p.layout_id for p in layouts)},
    )


class PdfPagesDialog(QtWidgets.QDialog):
    def __init__(self, path, template, parent=None):
        super().__init__(parent)
        self.template = template
        self.candidate = None
        self.results = []
        self.queue = []
        self.count = 0
        self.source_hash = ""
        self.pdf = PdfProcess(self)
        self.pdf.completed.connect(self.receive)
        self.pdf.failed.connect(self.fail)
        self.setWindowTitle("导入 PDF 页面为布局背景")
        self.resize(650, 350)
        form = QtWidgets.QFormLayout(self)
        self.summary = QtWidgets.QLabel("正在读取 PDF，可取消…")
        self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.pages = QtWidgets.QLineEdit("1")
        self.pages.setPlaceholderText("例如 1-4 或 1,3,4；顺序保留")
        form.addRow("页码与顺序", self.pages)
        self.adopt = QtWidgets.QCheckBox("采用首个所选 PDF 页的物理纸张尺寸")
        self.adopt.setChecked(True)
        form.addRow(self.adopt)
        self.group = QtWidgets.QComboBox()
        self.group.addItem("将所选页设为循环页组", "loop_pages")
        self.group.addItem("将所选页设为起始页组", "start_pages")
        form.addRow("页面组织", self.group)
        note = QtWidgets.QLabel(
            "旧布局保留，页组顺序明确替换为此次选择。若纸张尺寸不同，所有背景拉伸铺满纸张，已有框保持毫米坐标；越界将报错。PDF 只作参考，不进入机器轨迹。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.load = QtWidgets.QPushButton("读取所选页面")
        self.load.clicked.connect(self.start_render)
        form.addRow(self.load)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.pages.textEdited.connect(self.invalidate)
        self.adopt.toggled.connect(self.invalidate)
        self.group.currentIndexChanged.connect(self.invalidate)
        self.set_busy(True)
        self.pdf.request({"action": "open", "path": str(path)})

    def set_busy(self, busy):
        for w in (self.pages, self.adopt, self.group, self.load):
            w.setEnabled(not busy)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(
            not busy and self.candidate is not None
        )

    def invalidate(self, *_):
        self.candidate = None
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def start_render(self):
        try:
            self.queue = selected_pages(self.pages.text(), self.count)
            self.results = []
            self.candidate = None
            self.adopt_selected = self.adopt.isChecked()
            self.group_selected = self.group.currentData()
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
                self.candidate = imported_template(
                    self.template,
                    self.results,
                    self.source_hash,
                    adopt_size=self.adopt_selected,
                    group=self.group_selected,
                )
                w, h = self.results[0]["size_mm"]
                self.error.setText(
                    f"已读取 {len(self.results)} 页。首个所选页物理尺寸 {w:.3f} × {h:.3f} mm；点击确定后应用，可在外层撤销。"
                )
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
