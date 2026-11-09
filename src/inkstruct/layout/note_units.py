"""Measured footnote units, preserving atomic figures and rowspan-connected rows."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

from ..document.schema import SourceSpan
from ..scene.schema import PaintOp
from .inline import check_cancel
from .table_pages import TableChunk, border_segments, group_span


@dataclass(frozen=True)
class AtomicBand:
    top: float
    end: float
    fragments: tuple
    ops: tuple
    images: tuple
    span: SourceSpan
    table: object = None
    x: float = 0


@dataclass(frozen=True)
class NoteUnit:
    top: float
    height: float
    fragments: tuple
    ops: tuple
    images: tuple = ()
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))
    table_id: str = ""
    join_mm: float = 0
    continuation: NoteUnit | None = None
    label_height: float = 0
    tail_gap_mm: float = 0


def unit_cost(units, index, start):
    unit = units[index]
    cost = unit.height
    if index == start and unit.continuation:
        cost += unit.continuation.height - unit.join_mm
    elif index > start and unit.table_id and units[index - 1].table_id == unit.table_id:
        cost -= unit.join_mm
    return cost


def allocation_height(units, start, count):
    if not count:
        return 0
    return (
        max(
            sum(unit_cost(units, index, start) for index in range(start, start + count)),
            units[start].label_height,
        )
        + units[start].tail_gap_mm
    )


def allocation_units(units, start, count):
    """Include a repeated header only when the page starts within its table."""
    previous = None
    if units[start].continuation:
        previous = units[start].continuation
        yield previous, True, 0
    for unit in units[start : start + count]:
        overlap = (
            unit.join_mm if previous and unit.table_id and unit.table_id == previous.table_id else 0
        )
        yield unit, False, overlap
        previous = unit


def _table_units(band, cancelled):
    table = band.table
    pen = table.style.stroke_width_mm
    header_count = table.model.header_rows
    groups = [(a, b) for a, b in table.model.row_groups if a >= header_count]
    if not groups:
        groups = [(0, table.model.rows)]
    else:
        groups[0] = (0, groups[0][1])  # Header cannot be separated from the first data group.

    def piece(a, b):
        check_cancel(cancelled)
        rows = tuple(range(a, b))
        selected = [cell for cell in table.cells if cell.cell.row in rows]
        node_ids = {n.node_id for cell in selected for n in cell.cell.node.walk()}
        fs = tuple(f for f in band.fragments if f.node_id in node_ids)
        ids = {f.occurrence_id for f in fs}
        ids.update(
            rule.occurrence_id
            for cell in selected
            for line in cell.lines
            for box in line
            if box.math
            for rule in box.math.rules
        )
        decoration_prefixes = tuple(cell.cell.node.node_id + ":" for cell in selected)
        ops = [
            op
            for op in band.ops
            if op.occurrence_id in ids or op.occurrence_id.startswith(decoration_prefixes)
        ]
        top = band.top + sum(table.row_heights[:a])
        height = sum(table.row_heights[a:b]) + pen
        borders, _, _ = border_segments(
            table, TableChunk(rows, False, False, height - pen), band.x, top + pen / 2
        )
        ops = [
            PaintOp(f"{table.model.node.node_id}:note-border:{i}", points, pen)
            for i, points in enumerate(borders)
        ] + ops
        for op in band.ops:
            if op.occurrence_id.startswith(table.model.node.node_id + ":quote:"):
                x = op.points[0][0]
                ops.append(
                    replace(
                        op, points=((x, top + op.width_mm / 2), (x, top + height - op.width_mm / 2))
                    )
                )
        return NoteUnit(
            top,
            height,
            fs,
            tuple(ops),
            span=group_span(table, a, b),
            table_id=table.model.node.node_id,
            join_mm=pen,
        )

    header = piece(0, header_count) if header_count and table.style.repeat_header else None
    return [
        replace(piece(a, b), continuation=header if index else None)
        for index, (a, b) in enumerate(groups)
    ]


def note_units(snapshot, bands=(), *, cancelled=None):
    """Retain the original text-line bands; replace atomic blocks by explicit units."""
    page = snapshot.pages[0]
    atomic_fragments = {id(f) for band in bands for f in band.fragments}
    atomic_ops = {id(op) for band in bands for op in band.ops}
    groups = {}
    for fragment in page.fragments:
        check_cancel(cancelled)
        if id(fragment) not in atomic_fragments:
            groups.setdefault(fragment.line_index, []).append(fragment)
    groups = [tuple(group) for _, group in sorted(groups.items())]
    ends = [max(f.logical_bounds[3] for f in group) for group in groups]
    assigned = [[] for _ in groups]
    for op in page.paint_ops:
        check_cancel(cancelled)
        if id(op) in atomic_ops:
            continue
        centre = (min(y for _, y in op.points) + max(y for _, y in op.points)) / 2
        index = min(bisect_left(ends, centre), len(groups) - 1)
        if index < 0:
            raise ValueError("Footnote has unassigned drawing content")
        assigned[index].append(op)
    entries = []
    for group, end, ops in zip(groups, ends, assigned):
        end = max([end] + [max(y for _, y in op.points) + op.width_mm / 2 for op in ops])
        top = min(f.logical_bounds[1] for f in group)
        entries.append(NoteUnit(top, end - top, group, tuple(ops), span=group[0].span))
    for band in bands:
        check_cancel(cancelled)
        if band.table:
            entries.extend(_table_units(band, cancelled))
        else:
            entries.append(
                NoteUnit(
                    band.top, band.end - band.top, band.fragments, band.ops, band.images, band.span
                )
            )
    entries.sort(key=lambda unit: unit.top)
    result, top = [], 0
    for unit in entries:
        # Adjacent row groups overlap by the shared border pen width. All other
        # leading whitespace belongs to the following unit, as in the text kernel.
        overlap = (
            unit.join_mm if result and unit.table_id and result[-1].table_id == unit.table_id else 0
        )
        start = top - overlap
        end = unit.top + unit.height
        result.append(replace(unit, top=start, height=end - start))
        top = end
    if Counter(f.occurrence_id for unit in result for f in unit.fragments) != Counter(
        f.occurrence_id for f in page.fragments
    ):
        raise RuntimeError("Footnote measurement lost or duplicated source instances")
    if Counter(image.occurrence_id for unit in result for image in unit.images) != Counter(
        image.occurrence_id for image in page.images
    ):
        raise RuntimeError("Footnote measurement lost or duplicated images")
    return tuple(result)


def merge_table_borders(ops):
    """Deduplicate shared edges and join collinear rule pieces within one page."""
    groups, other = defaultdict(list), []
    for op in ops:
        if ":note-border:" not in op.occurrence_id:
            other.append(op)
            continue
        (x0, y0), (x1, y1) = op.points
        horizontal = y0 == y1
        fixed, a, b = (y0, x0, x1) if horizontal else (x0, y0, y1)
        key = (
            op.occurrence_id.split(":note-border:")[0],
            horizontal,
            round(fixed, 9),
            op.width_mm,
            op.color,
            op.execution_domain,
        )
        groups[key].append((min(a, b), max(a, b), fixed, op))
    for (_, horizontal, _, _, _, _), spans in groups.items():
        merged = []
        for a, b, fixed, op in sorted(spans, key=lambda item: item[:2]):
            if merged and a <= merged[-1][1] + 1e-8:
                left, right, fixed0, old = merged[-1]
                merged[-1] = left, max(right, b), fixed0, old
            else:
                merged.append((a, b, fixed, op))
        for a, b, fixed, op in merged:
            points = ((a, fixed), (b, fixed)) if horizontal else ((fixed, a), (fixed, b))
            other.append(replace(op, points=points))
    return tuple(other)
