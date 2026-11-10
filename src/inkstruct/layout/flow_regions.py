"""Forward-only region cursor; physical pages keep their continuous numbering."""

from math import ceil

from ..document.schema import SourceSpan


class GridBands:
    """Bind template-relative baselines to the physical frame."""

    def __init__(self, frame, offset):
        grid = frame.paper_grid
        _, top, _, bottom = frame.region.bounds
        self.first = top + offset + grid.first_mm
        self.pitch = grid.pitch
        if self.pitch:
            last = top + offset + grid.last_mm
            self.tail = min(self.pitch / 4, bottom + offset - last)
            self.top = max(top + offset, self.first + self.tail - self.pitch)
            self.bottom = last + self.tail
        else:
            self.top = top + offset
            self.bottom = bottom + offset

    def block_end(self, required):
        if not self.pitch:
            return max(self.bottom, required)
        first_end = self.first + self.tail
        return first_end + max(0, ceil((required - first_end - 1e-9) / self.pitch)) * self.pitch

    def line(self, start, ascent, descent, height):
        if not self.pitch:
            if self.first - ascent < start - 1e-9:
                return self.first, float('inf')
            return self.first, self.block_end(max(start + height, self.first + descent))
        index = max(0, ceil((start + ascent - self.first - 1e-9) / self.pitch))
        baseline = self.first + index * self.pitch
        end = self.block_end(max(start + height, baseline + descent, baseline + self.tail))
        return baseline, end


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
        grid = self.grid
        return (a + t.offset_x_mm, grid.top if grid else b + t.offset_y_mm,
                c + t.offset_x_mm, grid.bottom if grid else d + t.offset_y_mm)

    @property
    def grid(self):
        return self._grid(self.frame)

    def _grid(self, frame):
        return GridBands(frame, self.template.offset_y_mm) if frame and frame.paper_grid else None

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

    def fits_later(self, width, height, *, line=None, padding=0):
        for page, index in self.candidates(include_current=False):
            frame = self.template.layout(page).body_frames[index]
            grid = self._grid(frame)
            fits = height <= frame.region.height_mm + 1e-8
            if grid:
                end = (grid.line(grid.top, *line)[1] if line else
                       grid.block_end(grid.top + height + 2 * padding))
                fits = end <= grid.bottom + 1e-8
            if width <= frame.region.width_mm + 1e-8 and fits:
                return page, index
        required = height + 2 * padding
        self.stop(
            f"对象需要 {width:.2f} × {required:.2f} mm；完整循环页组仍无法容纳，排版已停止。"
            "请增大正文框、调整对象尺寸或在源码中拆分公式。"
        )

    def stop(self, message):
        if self.frame:
            label = self.template.layout(self.page_index).label
            message = f"第 {self.page_index + 1} 页「{label}」的「{self.frame.label}」：{message}"
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
