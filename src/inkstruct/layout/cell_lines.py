"""Compose ordinary measured handwriting into printed grid cells."""

from dataclasses import replace
from math import ceil

from ..document.cancellation import check_cancel


def cell_lines(boxes, grid, width, stroke_width, cancelled):
    lines, row, used = [], [], 0
    columns = max(1, int((width + 1e-8) / grid.cell_width))
    for box in boxes:
        check_cancel(cancelled)
        if box.status == "line-break":
            row.append(box)
            lines.append(row)
            row, used = [], 0
            continue
        if box.status == "break-hint":
            row.append(box)
            continue
        cells = max(1, ceil((box.advance - 1e-8) / grid.cell_width)) if box.math else 1
        tab = box.run.occurrence.text == "\t"
        if tab:
            cells = min(columns, 4 - used % 4)
        if used and used + cells > columns:
            lines.append(row)
            row, used = [], 0
            if tab:
                cells = min(columns, 4)
        advance = cells * grid.cell_width
        if box.glyph:
            left, top, right, bottom = box.glyph.bounds
            em = min(
                box.em,
                max(0.01, advance - stroke_width) / max(0.001, right - left),
                max(0.01, grid.cell_height - stroke_width) / max(0.001, bottom - top),
            )
            offset = (advance - (right + left) * em) / 2
            box = replace(
                box,
                natural=box,
                em=em,
                origin_offset=offset,
                advance=advance,
                ascent=(bottom - top) * em / 2,
                descent=(bottom - top) * em / 2,
            )
        else:
            box = replace(box, natural=box, advance=advance)
        row.append(box)
        used += cells
    if row or not lines or boxes[-1].status == "line-break":
        lines.append(row)
    return lines
