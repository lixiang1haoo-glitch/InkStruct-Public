"""Render a PDF with Windows.Data.Pdf inside the dedicated PDF worker."""

from io import BytesIO

from PIL import Image
from winrt.runtime import ApartmentType, init_apartment, uninit_apartment
from winrt.windows.data.pdf import PdfDocument, PdfPageRenderOptions
from winrt.windows.storage.streams import DataReader, DataWriter, InMemoryRandomAccessStream


class WindowsPdfDocument:
    def __init__(self, raw):
        self.stream = self.document = None
        init_apartment(ApartmentType.MULTI_THREADED)
        try:
            self.stream = InMemoryRandomAccessStream()
            with DataWriter(self.stream) as writer:
                writer.write_bytes(raw)
                if writer.store_async().get() != len(raw):
                    raise ValueError("PDF 数据读取不完整")
                writer.detach_stream()
            self.stream.seek(0)
            self.document = PdfDocument.load_from_stream_async(self.stream).get()
            if self.document.is_password_protected:
                raise ValueError("暂不支持需要密码或特殊加密方式的 PDF")
            self.page_count = self.document.page_count
        except OSError as error:
            self.close()
            if getattr(error, "winerror", None) in {5, -2147024891}:
                raise ValueError("暂不支持需要密码或特殊加密方式的 PDF") from error
            raise ValueError(f"无法读取 PDF：{error}") from error
        except BaseException:
            self.close()
            raise

    def close(self):
        self.document = None
        try:
            if self.stream is not None:
                stream, self.stream = self.stream, None
                stream.close()
        finally:
            uninit_apartment()

    def page_size_mm(self, index):
        with self.document.get_page(index) as page:
            size = page.size  # Windows reports DIPs (96 per inch).
            return size.width * 25.4 / 96, size.height * 25.4 / 96

    def render(self, index, width, height):
        with self.document.get_page(index) as page, InMemoryRandomAccessStream() as target:
            options = PdfPageRenderOptions()
            options.destination_width = width
            options.destination_height = height
            options.is_ignoring_high_contrast = True
            page.render_to_stream_async(target, options).get()
            target.seek(0)
            data = bytearray(target.size)
            with DataReader(target) as reader:
                if reader.load_async(len(data)).get() != len(data):
                    raise ValueError("PDF 页面渲染不完整")
                reader.read_bytes(data)
                reader.detach_stream()
        with Image.open(BytesIO(data)) as decoded:
            image = decoded.convert("RGBA")
        # WinRT may apply the Windows display scale to the requested dimensions.
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        return image
