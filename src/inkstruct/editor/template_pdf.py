"""Select a PDF page as a bounded, read-only template reference."""

import io
import math
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

from ..document.template import PageTemplate, Region, TemplateBackground, TemplateFace
from ..document.template_authoring import pack_reference_image, parse_template, template_json

MAX_PDF_BYTES = 50 * 1024 * 1024


class QtPdfDocument:
    def __init__(self, raw):
        from PySide6.QtPdf import QPdfDocument

        self.device = QtCore.QBuffer()
        self.device.setData(raw)
        self.device.open(QtCore.QIODevice.ReadOnly)
        self.document = QPdfDocument()
        self.document.load(self.device)
        if self.document.status() != QPdfDocument.Status.Ready:
            error = self.document.error()
            self.close()
            if error in {
                QPdfDocument.Error.IncorrectPassword,
                QPdfDocument.Error.UnsupportedSecurityScheme,
            }:
                raise ValueError("暂不支持需要密码或特殊加密方式的 PDF")
            raise ValueError(f"无法读取 PDF：{error.name}")
        self.page_count = self.document.pageCount()

    def close(self):
        self.document.close()
        self.device.close()
        self.device.setData(QtCore.QByteArray())

    def page_size_mm(self, index):
        size = self.document.pagePointSize(index)
        return size.width() * 25.4 / 72, size.height() * 25.4 / 72

    def render(self, index, width, height):
        image = self.document.render(index, QtCore.QSize(width, height))
        if image.isNull():
            raise ValueError("PDF 页面渲染失败")
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("PDF 页面无法转换为参考 PNG")
        buffer.close()
        with Image.open(io.BytesIO(bytes(data))) as decoded:
            return decoded.convert("RGBA")


class PdfReference:
    def __init__(self, path):
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_PDF_BYTES + 1)
        if len(raw) > MAX_PDF_BYTES:
            raise ValueError("PDF 不能超过 50 MiB")
        self.source_sha256 = sha256(raw).hexdigest()
        if sys.platform == "win32":
            from .pdf_windows import WindowsPdfDocument

            self.document = WindowsPdfDocument(raw)
        else:
            self.document = QtPdfDocument(raw)
        self.cached_page = self.cached_background = None
        self.page_count = self.document.page_count
        if not 1 <= self.page_count <= 1000:
            self.close()
            raise ValueError("PDF 须包含 1–1000 页")

    def close(self):
        if self.document is not None:
            document, self.document = self.document, None
            self.cached_page = self.cached_background = None
            document.close()

    def page_size_mm(self, index):
        if self.document is None or not isinstance(index, int) or not 0 <= index < self.page_count:
            raise ValueError("PDF 页码无效或文件已关闭")
        size = self.document.page_size_mm(index)
        if not all(math.isfinite(v) and 0 < v <= 10000 for v in size):
            raise ValueError("PDF 页面尺寸无效或超过 10000 mm 的导入范围")
        return size

    def background(self, index):
        width, height = self.page_size_mm(index)
        if self.cached_page == index:
            return self.cached_background
        scale = 1600 / max(width, height)
        pixels = max(1, round(width * scale)), max(1, round(height * scale))
        background = pack_reference_image(self.document.render(index, *pixels))
        self.cached_page, self.cached_background = index, background
        return background

    def apply(self, template, face_name, index, *, mode="background"):
        return apply_pdf_background(
            template,
            face_name,
            self.page_size_mm(index),
            self.background(index),
            self.source_sha256,
            mode=mode,
        )


def apply_pdf_background(
    template, face_name, size, background, source_sha256, *, mode="background"
):
    width, height = size
    if face_name not in {"first", "continuation"} or mode not in {"background", "new"}:
        raise ValueError("Unknown PDF import mode or face")
    if mode == "new":
        margin = min(10, width / 10, height / 10)
        face = TemplateFace(Region("body", margin, margin, width - 2 * margin, height - 2 * margin))
        template = PageTemplate("PDF 参考版式", width, height, face, face)
    other = "continuation" if face_name == "first" else "first"
    source_hash = (
        source_sha256
        if (getattr(template, other).background is None or template.source_sha256 == source_sha256)
        else ""
    )
    template = replace(
        template,
        **{face_name: replace(getattr(template, face_name), background=background)},
        source_sha256=source_hash,
        calibration="unreviewed",
    )
    # Both images and all geometry must still fit the portable JSON budget.
    return parse_template(template_json(template))


class PdfReferenceDialog(QtWidgets.QDialog):
    def __init__(self, path, template, face_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("从 PDF 导入参考底图")
        self.resize(660, 780)
        self.template, self.face_name = template, face_name
        from .template_pdf_process import PdfProcess

        self.pdf = PdfProcess(self)
        self.path = str(Path(path).resolve())
        self.page_count = 0
        self.pdf.completed.connect(self.receive)
        self.pdf.failed.connect(self.failed)
        self.candidate = None
        self.image = QtGui.QImage()
        form = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel(
            f"{Path(path).name} · 导入到" + ("首页" if face_name == "first" else "续页")
        )
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(QtCore.Qt.PlainText)
        form.addWidget(self.summary)
        row = QtWidgets.QFormLayout()
        self.page = QtWidgets.QSpinBox(self)
        self.page.setRange(1, 1)
        row.addRow("PDF 页码", self.page)
        self.mode = QtWidgets.QComboBox(self)
        self.mode.addItem("仅替换当前页底图，保留纸张与页面版式", "background")
        self.mode.addItem("按本页纸张尺寸新建页面版式", "new")
        row.addRow("导入方式", self.mode)
        self.dimensions = QtWidgets.QLabel(self)
        self.dimensions.setWordWrap(True)
        row.addRow(self.dimensions)
        form.addLayout(row)
        self.preview = QtWidgets.QLabel(self)
        self.preview.setMinimumSize(280, 300)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.preview.setStyleSheet("background: white; border: 1px solid #cbd5e1;")
        form.addWidget(self.preview, 1)
        self.note = QtWidgets.QLabel(self)
        self.note.setWordWrap(True)
        self.note.setTextFormat(QtCore.Qt.PlainText)
        form.addWidget(self.note)
        self.error = QtWidgets.QLabel(self)
        self.error.setWordWrap(True)
        self.error.setTextFormat(QtCore.Qt.PlainText)
        form.addWidget(self.error)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addWidget(self.buttons)
        self.page.valueChanged.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.set_busy(True)
        self.error.setText("正在读取 PDF，可随时取消…")
        self.pdf.request({"action": "open", "path": self.path})

    def set_busy(self, busy):
        self.page.setEnabled(not busy)
        self.mode.setEnabled(not busy)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(
            not busy and self.candidate is not None
        )

    def failed(self, message):
        self.candidate = None
        self.image = QtGui.QImage()
        self.preview.clear()
        self.error.setText(message)
        self.set_busy(False)
        self.page.setEnabled(False)
        self.mode.setEnabled(False)

    def receive(self, result):
        if result["action"] == "open":
            self.page_count = result["page_count"]
            self.source_sha256 = result["source_sha256"]
            self.summary.setText(self.summary.text() + f" · 共 {self.page_count} 页")
            self.page.setRange(1, self.page_count)
            self.refresh()
        elif result["index"] != self.page.value() - 1:
            self.refresh()
        else:
            self.apply_result(result)

    def refresh(self):
        self.candidate = None
        self.image = QtGui.QImage()
        self.preview.clear()
        self.dimensions.clear()
        self.set_busy(True)
        self.error.setText("正在渲染所选页，可随时取消…")
        self.pdf.request({"action": "render", "index": self.page.value() - 1})

    def apply_result(self, result):
        self.candidate = None
        try:
            width, height = result["size_mm"]
            self.dimensions.setText(
                f"PDF 本页：{width:.3f} × {height:.3f} mm；当前纸张：{self.template.width_mm:.3f} × {self.template.height_mm:.3f} mm"
            )
            self.candidate = apply_pdf_background(
                self.template,
                self.face_name,
                (width, height),
                TemplateBackground(**result["background"]),
                self.source_sha256,
                mode=self.mode.currentData(),
            )
            self.image = QtGui.QImage.fromData(
                getattr(self.candidate, self.face_name).background.png_bytes(), "PNG"
            )
            self.update_preview()
            if self.mode.currentData() == "new":
                note = "将新建一个通用正文区，替换原几何、两页底图及校准偏移；可在外层撤销。已有文档绑定需要重新检查。"
            else:
                note = "保留全部几何与纸张尺寸，只替换所选页型底图。"
                if (
                    abs(width - self.template.width_mm) > 0.01
                    or abs(height - self.template.height_mm) > 0.01
                ):
                    note += " 当前纸张与 PDF 尺寸不同，底图将按当前纸张铺满；如需原始尺寸，请选择新建页面版式或先调整纸张。"
            self.note.setText(note + " PDF 仅作为参考，不会自动生成栏位、文字或机器轨迹。")
            self.error.clear()
        except (ValueError, TypeError, OSError) as error:
            self.error.setText(str(error))
            self.preview.clear()
            self.image = QtGui.QImage()
        self.set_busy(False)

    def update_preview(self):
        if not self.image.isNull():
            self.preview.setPixmap(
                QtGui.QPixmap.fromImage(self.image).scaled(
                    self.preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                )
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview"):
            self.update_preview()

    def configuration(self):
        if self.candidate is None:
            raise ValueError("PDF 页面尚未成功导入")
        return self.candidate

    def accept(self):
        if self.candidate is not None:
            super().accept()

    def done(self, result):
        self.pdf.close()
        super().done(result)
