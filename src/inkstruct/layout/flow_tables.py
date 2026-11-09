"""Existing atomic row groups, admitted against each actual text-frame capacity."""

from .inline import check_cancel
from .table_pages import TableChunk, table_boxes


def paginate_regions(
    table, capacity, seek, new_region, cursor, *, cancelled=None, pager=None, position=None
):
    model = table.model
    headers = tuple(range(model.header_rows))
    groups = [g for g in model.row_groups if g[0] >= model.header_rows]
    if not groups:
        groups = [(0, model.rows)]
        headers = ()
    n = 0
    first = True
    visited = set()
    while n < len(groups):
        check_cancel(cancelled)
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
            tuple(round(v, 8) for v in capacity()),
            tuple(pager.cursors.items()) if pager else (),
        )
        if state in visited:
            cursor.stop("完整循环未能放入表格行组及其脚注，排版已停止。")
        visited.add(state)
        rows = list(headers if first or table.style.repeat_header else ())
        height = sum(table.row_heights[r] for r in rows)
        start, end = groups[n]
        need = height + sum(table.row_heights[start:end]) + table.style.stroke_width_mm
        width = table.width + table.style.stroke_width_mm
        cw, ch = capacity()
        if width > cw + 1e-8 or need > ch + 1e-8:
            seek(width, need)
            cw, ch = capacity()
        while n < len(groups):
            start, end = groups[n]
            required = height + sum(table.row_heights[start:end])
            boxes = table_boxes(table, (*rows, *range(start, end)))
            if required + table.style.stroke_width_mm > ch + 1e-8:
                break
            if pager and not pager.can_fit(
                [boxes], position() + required + table.style.stroke_width_mm
            ):
                if len(rows) > len(headers):
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
        has_data = any(r >= model.header_rows for r in rows) if headers else bool(rows)
        if not has_data:
            continue
        if pager:
            pager.accept(
                table_boxes(table, rows), position() + height + table.style.stroke_width_mm
            )
        yield TableChunk(
            tuple(rows), False, not first and bool(headers) and table.style.repeat_header, height
        )
        first = False
        if n < len(groups):
            new_region()
