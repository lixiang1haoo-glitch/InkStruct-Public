"""Existing atomic row groups, admitted against each actual text-frame capacity."""

from dataclasses import replace
from functools import cache
from math import ceil

from .inline import check_cancel
from .table_pages import TableChunk, table_boxes


def paginate_regions(table, indent, position, seek, new_region, cursor, *, cancelled=None, pager=None):
    model = table.model
    headers = tuple(range(model.header_rows))
    groups = [g for g in model.row_groups if g[0] >= model.header_rows]
    if not groups:
        groups = [(0, model.rows)]
        headers = ()
    n = 0
    first = True
    visited = set()
    pen = table.style.stroke_width_mm
    width = table.width + pen + indent

    @cache
    def rounded_table(pitch):
        return replace(table, row_heights=tuple(
            max(1, ceil((height - 1e-9) / pitch)) * pitch for height in table.row_heights
        ))

    def geometry(grid, start, bottom):
        top = start + pen / 2
        if grid is None:
            return table, top, bottom - top - pen / 2
        if not grid.pitch:
            return table, top, 0
        top = grid.next_baseline(top)
        return rounded_table(grid.pitch), top, bottom - top - pen / 2

    while n < len(groups):
        check_cancel(cancelled)
        grid = cursor.grid
        left, _, right, bottom = cursor.bounds()
        active, top, capacity = geometry(grid, position(), bottom)
        phase = (
            cursor.page_index
            if cursor.page_index < len(cursor.template.start_pages)
            else len(cursor.template.start_pages)
            + (cursor.page_index - len(cursor.template.start_pages))
            % len(cursor.template.effective_loop)
        )
        state = (
            n,
            phase,
            cursor.frame_index,
            round(capacity, 8),
            tuple(pager.cursors.items()) if pager else (),
        )
        if state in visited:
            cursor.stop("完整循环未能放入表格行组及其脚注，排版已停止。")
        visited.add(state)
        rows = list(headers if first or table.style.repeat_header else ())
        header_count = len(rows)
        height = sum(active.row_heights[r] for r in rows)
        start, end = groups[n]
        first_rows = (*rows, *range(start, end))
        need = sum(active.row_heights[r] for r in first_rows)
        if width > right - left + 1e-8 or need > capacity + 1e-8:
            def fits_frame(frame, candidate_grid):
                lower, upper = ((candidate_grid.top, candidate_grid.bottom) if candidate_grid
                                else (0, frame.region.height_mm))
                candidate, _, available = geometry(candidate_grid, lower, upper)
                return sum(candidate.row_heights[r] for r in first_rows) <= available + 1e-8

            seek(width, need + pen, fits_frame=fits_frame)
            continue

        def occupied_end(row_height):
            required = top + row_height + pen / 2
            return grid.block_end(required) if grid else required

        while n < len(groups):
            start, end = groups[n]
            required = height + sum(active.row_heights[start:end])
            if required > capacity + 1e-8:
                break
            boxes = table_boxes(active, (*rows, *range(start, end)))
            if pager and not pager.can_fit(
                [boxes], occupied_end(required)
            ):
                if len(rows) > header_count:
                    break
                # Mandatory notes may require a new physical page; the next
                # frame/page still uses the same row-group cursor.
                previous = (cursor.page_index, cursor.frame_index)
                new_region()
                if (cursor.page_index, cursor.frame_index) == previous:
                    raise RuntimeError("Table region cursor failed to advance")
                break
            rows.extend(range(start, end))
            height = required
            n += 1
            visited.clear()
        if len(rows) == header_count:
            continue
        if pager:
            pager.accept(table_boxes(active, rows), occupied_end(height))
        chunk = TableChunk(
            tuple(rows), False, not first and bool(headers) and table.style.repeat_header, height
        )
        yield active, chunk, top, occupied_end(height)
        first = False
        if n < len(groups):
            new_region()
