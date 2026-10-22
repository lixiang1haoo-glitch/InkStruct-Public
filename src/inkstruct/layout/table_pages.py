"""Atomic row-group pagination and per-page table ink; no cross-page pen paths."""

from collections import defaultdict
from dataclasses import dataclass
from itertools import accumulate

from ..document.schema import Diagnostic, SourceSpan
from ..scene.schema import PaintOp
from .inline import check_cancel


@dataclass(frozen=True)
class TableChunk:
    rows: tuple[int, ...]
    new_page: bool
    repeated_header: bool
    height: float


def first_group_height(measured):
    headers = measured.model.header_rows
    first = next((g for g in measured.model.row_groups if g[0] >= headers), None)
    return sum(measured.row_heights[:headers]) + (
        sum(measured.row_heights[first[0] : first[1]]) if first else 0
    )


def group_span(measured, first, end):
    cells = [cell.cell for cell in measured.cells if first <= cell.cell.row < end]
    return (
        SourceSpan(min(c.node.span.start for c in cells), max(c.node.span.end for c in cells))
        if cells
        else measured.model.node.span
    )


def group_overflow(measured, first, end, required, available):
    """Point to the atomic source rows rather than the whole, possibly long table."""
    cells = [cell.cell for cell in measured.cells if first <= cell.cell.row < end]
    span = group_span(measured, first, end)
    merged = any(cell.rowspan > 1 for cell in cells)
    kind = "Header rows" if end <= measured.model.header_rows else "Atomic rows"
    reason = " linked by rowspan" if merged else ""
    return Diagnostic(
        "table-group-height-overflow",
        f"{kind} {first + 1}–{end}{reason}, including any required header, need {required:.3f} mm; "
        f"available page height is {available:.3f} mm. Cell contents are not split across pages. "
        "Increase usable page height, reduce table dimensions, or divide the source table while preserving merged cells.",
        span,
    )


def paginate_table(measured, available, full_height, *, cancelled=None):
    model, style = measured.model, measured.style
    headers = tuple(range(model.header_rows))
    groups = [g for g in model.row_groups if g[0] >= model.header_rows]
    if not groups:
        height = sum(measured.row_heights)
        issues = (
            [group_overflow(measured, 0, model.rows, height, full_height)]
            if height > full_height + 1e-7
            else []
        )
        return (
            TableChunk(
                tuple(range(model.rows)),
                height > available and available < full_height,
                False,
                height,
            ),
        ), tuple(issues)
    chunks, issues, position = [], [], 0
    while position < len(groups):
        check_cancel(cancelled)
        repeated = position > 0 and style.repeat_header and bool(headers)
        rows = list(headers if position == 0 or repeated else ())
        height = sum(measured.row_heights[r] for r in rows)
        group = groups[position]
        needed = height + sum(measured.row_heights[group[0] : group[1]])
        new_page = bool(chunks) or (needed > available + 1e-7 and available < full_height - 1e-7)
        capacity = full_height if new_page else available
        initial = position
        while position < len(groups):
            a, b = groups[position]
            group_height = sum(measured.row_heights[a:b])
            if height + group_height > capacity + 1e-7 and position > initial:
                break
            if height + group_height > full_height + 1e-7:
                issues.append(group_overflow(measured, a, b, height + group_height, full_height))
            rows.extend(range(a, b))
            height += group_height
            position += 1
            if height >= capacity - 1e-7:
                break
        if position <= initial:
            raise RuntimeError("Table pagination failed to consume a row group")
        chunks.append(TableChunk(tuple(rows), new_page, repeated, height))
    return tuple(chunks), tuple(issues)


def border_segments(measured, chunk, x, y):
    xs = list(accumulate(measured.column_widths, initial=x))
    ys = {
        r: value
        for r, value in zip(
            chunk.rows, accumulate((measured.row_heights[r] for r in chunk.rows), initial=y)
        )
    }
    intervals = defaultdict(list)
    for measured_cell in measured.cells:
        cell = measured_cell.cell
        if cell.row not in ys:
            continue
        left, right = xs[cell.column], xs[cell.column + cell.colspan]
        top = ys[cell.row]
        final_row = cell.row + cell.rowspan - 1
        bottom = ys[final_row] + measured.row_heights[final_row]
        for orientation, fixed, a, b in (
            ("h", top, left, right),
            ("h", bottom, left, right),
            ("v", left, top, bottom),
            ("v", right, top, bottom),
        ):
            intervals[orientation, fixed].append((a, b))
    segments = []
    for (orientation, fixed), spans in sorted(intervals.items()):
        merged = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] + 1e-9:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        for a, b in merged:
            segments.append(
                ((a, fixed), (b, fixed)) if orientation == "h" else ((fixed, a), (fixed, b))
            )
    return tuple(segments), xs, ys


def paint_table(measured, chunk, x, y, place_box, ops, line_index, *, cancelled=None):
    style, model = measured.style, measured.model
    borders, xs, ys = border_segments(measured, chunk, x, y)
    for index, points in enumerate(borders):
        ops.append(PaintOp(f"{model.node.node_id}:border:{index}", points, style.stroke_width_mm))
    for measured_cell in measured.cells:
        check_cancel(cancelled)
        cell = measured_cell.cell
        if cell.row not in ys:
            continue
        repeated = chunk.repeated_header and cell.row < model.header_rows
        left, right = xs[cell.column], xs[cell.column + cell.colspan]
        top = ys[cell.row]
        height = sum(measured.row_heights[cell.row : cell.row + cell.rowspan])
        inner_left = left + style.padding_left_mm + style.stroke_width_mm / 2
        inner_right = right - style.padding_right_mm - style.stroke_width_mm / 2
        free_height = (
            height
            - style.padding_top_mm
            - style.padding_bottom_mm
            - style.stroke_width_mm
            - measured_cell.content_height
        )
        valign = cell.valign
        if valign == "auto":
            valign = "top" if len(measured_cell.lines) > 1 else "middle"
        cursor_y = top + style.padding_top_mm + style.stroke_width_mm / 2
        cursor_y += max(0, free_height) * ({"top": 0, "middle": 0.5, "bottom": 1}[valign])
        for boxes, (ascent, descent, line_height) in zip(
            measured_cell.lines, measured_cell.metrics
        ):
            baseline = cursor_y + (line_height - ascent - descent) / 2 + ascent
            line_width = sum(b.advance for b in boxes)
            spare = inner_right - inner_left - line_width
            cursor_x = (
                inner_left
                + max(0, spare)
                * {"left": 0, "center": 0.5, "right": 1, "decimal": 0}[measured_cell.align]
            )
            if measured_cell.align == "decimal":
                before, after = measured.decimal_columns[cell.column]
                cursor_x = (
                    inner_left
                    + max(0, inner_right - inner_left - before - after) / 2
                    + before
                    - measured_cell.decimal_before
                )
            decorations = {"underline": [], "strike": []}
            for box in boxes:
                old_x = cursor_x
                cursor_x = place_box(
                    box,
                    cursor_x,
                    baseline,
                    line_index,
                    stroke_width=style.stroke_width_mm,
                    repeated=repeated,
                    container_id=model.node.node_id,
                )
                for name, spans in decorations.items():
                    if getattr(box.run, name):
                        if spans and abs(spans[-1][1] - old_x) < 1e-9:
                            spans[-1] = (spans[-1][0], cursor_x)
                        else:
                            spans.append((old_x, cursor_x))
            for name, spans in decorations.items():
                dy = (
                    descent - style.stroke_width_mm / 2 - 0.15
                    if name == "underline"
                    else -0.35 * style.text_em_mm
                )
                for index, (a, b) in enumerate(spans):
                    if b - a > style.stroke_width_mm:
                        ops.append(
                            PaintOp(
                                f"{cell.node.node_id}:{name}:{line_index}:{index}",
                                (
                                    (a + style.stroke_width_mm / 2, baseline + dy),
                                    (b - style.stroke_width_mm / 2, baseline + dy),
                                ),
                                style.stroke_width_mm,
                            )
                        )
            cursor_y += line_height
            line_index += 1
    return line_index


def table_boxes(measured, rows):
    """All cell boxes whose source row starts in this atomic row set."""
    return [
        box
        for cell in measured.cells
        if cell.cell.row in rows
        for line in cell.lines
        for box in line
    ]


def paginate_table_with_notes(
    measured, pager, position, new_page, full_height, diagnostics, *, cancelled=None
):
    """Yield one page chunk, reserving its reference heads before painting ink.

    The caller paints each yielded chunk and updates y before resuming. Moving
    pages invokes the same body/footnote finalization used by ordinary lines.
    """
    model, style = measured.model, measured.style
    headers = tuple(range(model.header_rows))
    groups = [g for g in model.row_groups if g[0] >= model.header_rows]
    if not groups:
        groups, headers = [(0, model.rows)], ()
    at = 0
    while at < len(groups):
        check_cancel(cancelled)
        y, top, bottom = position()
        repeated = at > 0 and style.repeat_header and bool(headers)
        rows = list(headers if at == 0 or repeated else ())
        height = sum(measured.row_heights[r] for r in rows)
        probe = pager.probe()
        initial = at
        moved = False
        while at < len(groups):
            a, b = groups[at]
            candidate_rows = [*rows, *range(a, b)]
            candidate_height = height + sum(measured.row_heights[a:b])
            boxes = table_boxes(measured, candidate_rows)
            end = y + candidate_height + style.stroke_width_mm
            fits = end <= bottom + 1e-7 and probe.can_fit([boxes], end)
            if not fits:
                if at > initial:
                    break
                if (
                    y > top
                    or pager.can_advance()
                    or (
                        bottom - top < full_height - 1e-7
                        and candidate_height + style.stroke_width_mm <= full_height + 1e-7
                    )
                ):
                    new_page()
                    moved = True
                    break
                if candidate_height + style.stroke_width_mm > bottom - top + 1e-7:
                    diagnostics.append(
                        group_overflow(
                            measured, a, b, candidate_height + style.stroke_width_mm, bottom - top
                        )
                    )
                # An impossible empty-page anchor is diagnosed by accept; keep
                # the group and its sources once in debug geometry, then advance.
            if fits:
                probe.accept(boxes, end)
            rows, height = candidate_rows, candidate_height
            at += 1
            if not fits:
                break
        if moved:
            continue
        if at <= initial:
            raise RuntimeError("Footnote table paginator did not consume a row group")
        pager.accept(table_boxes(measured, rows), y + height + style.stroke_width_mm)
        yield TableChunk(tuple(rows), False, repeated, height)
        if at < len(groups):
            new_page()
