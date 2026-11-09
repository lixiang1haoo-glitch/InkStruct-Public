"""Forward-only region cursor; physical pages keep their continuous numbering."""

from ..document.schema import SourceSpan


class NoRegionProgress(ValueError):
    def __init__(self, span, message):
        self.span = span
        self.pages = ()
        self.diagnostics = ()
        super().__init__(message)


class RegionCursor:
    def __init__(self, template):
        self.template = template
        self.page_index = 0
        self.frame_index = 0
        self.span = SourceSpan(0, 0)
        self.capture_partial = None
        widths = [
            p.body_frames[-1].region.width_mm for p in template.effective_layouts if p.body_frames
        ]
        self.note_width = min(widths) if widths else template.width_mm
        if not template.layout(0).body_frames:
            found = self.candidates(include_current=False)
            if found:
                self.page_index, self.frame_index = found[0]

    def candidates(self, *, include_current=True):
        result = []
        # The remaining one-time layouts and a full loop are a finite fit probe.
        end = (
            max(self.page_index, len(self.template.start_pages))
            + len(self.template.effective_loop)
            + 1
        )
        for page in range(self.page_index, end):
            for i, _ in enumerate(self.template.layout(page).body_frames):
                if page == self.page_index and (
                    i < self.frame_index or (i == self.frame_index and not include_current)
                ):
                    continue
                result.append((page, i))
        return result

    @property
    def frame(self):
        frames = self.template.layout(self.page_index).body_frames
        return frames[self.frame_index] if frames else None

    def bounds(self, index=None):
        frame = self.frame
        if frame is None:
            self.stop("正文没有可用正文框；请在循环页组中配置正文框。")
        a, b, c, d = frame.region.bounds
        t = self.template
        return a + t.offset_x_mm, b + t.offset_y_mm, c + t.offset_x_mm, d + t.offset_y_mm

    def next(self):
        found = self.candidates(include_current=False)
        if not found:
            self.stop("后续布局没有正文框，未排完内容无法继续；请修正循环页组。")
        self.page_index, self.frame_index = found[0]

    def next_page(self):
        found = [(p, i) for p, i in self.candidates(include_current=False) if p > self.page_index]
        if not found:
            self.stop("后续页面没有正文框，未排完内容无法继续；请修正循环页组。")
        self.page_index, self.frame_index = found[0]

    def fits_later(self, width, height):
        for page, index in self.candidates(include_current=False):
            r = self.template.layout(page).body_frames[index].region
            if width <= r.width_mm + 1e-8 and height <= r.height_mm + 1e-8:
                return page, index
        self.stop(
            f"对象需要 {width:.2f} × {height:.2f} mm；完整循环页组仍无法容纳，排版已停止。"
            "请增大正文框、调整对象尺寸或在源码中拆分公式。"
        )

    def stop(self, message):
        error = NoRegionProgress(
            self.span, message + " 已保留此前排版；此处及后续正文尚未排版，成品导出不可用。"
        )
        if self.capture_partial is not None:
            error.pages, error.diagnostics = self.capture_partial()
        raise error

    def note_bounds(self, index):
        frames = self.template.layout(index).body_frames
        if not frames:
            return 0, 0, 0, 0
        a, b, _, d = frames[-1].region.bounds
        t = self.template
        return (
            a + t.offset_x_mm,
            b + t.offset_y_mm,
            a + self.note_width + t.offset_x_mm,
            d + t.offset_y_mm,
        )

    def note_bottom(self, index, bottom):
        if (
            index == self.page_index
            and self.frame_index < len(self.template.layout(index).body_frames) - 1
        ):
            return self.note_bounds(index)[1]
        return bottom
