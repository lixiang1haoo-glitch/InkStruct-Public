"""Measure table containers and interval constraints before page fragmentation."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from itertools import accumulate, pairwise

from ..document.schema import Diagnostic, StyleProfile
from ..document.table_style import TableStyle
from ..document.tables import TableCell, TableModel
from .inline import InlineBox, break_lines, check_cancel, inline_runs, measure_runs
from .measurement_cache import cached_measurement

NUMERIC = re.compile(r"[+−-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")


@dataclass(frozen=True)
class MeasuredCell:
    cell: TableCell
    lines: tuple[tuple[InlineBox, ...], ...]
    metrics: tuple[tuple[float, float, float], ...]
    min_width: float
    preferred_width: float
    align: str
    decimal_before: float = 0
    decimal_after: float = 0

    @property
    def content_height(self):
        return sum(m[2] for m in self.metrics)


@dataclass(frozen=True)
class MeasuredTable:
    model: TableModel
    style: TableStyle
    cells: tuple[MeasuredCell, ...]
    column_widths: tuple[float, ...]
    row_heights: tuple[float, ...]
    decimal_columns: tuple[tuple[float, float], ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def width(self):
        return sum(self.column_widths)


def _interval_minimum(columns, constraints, base):
    """Longest paths on prefix coordinates give the minimum feasible total width.

    Constraint (i,j,w) is x[j] >= x[i]+w. All edges go forward, so one
    increasing-prefix pass is exact even when merged-cell intervals overlap.
    """
    prefixes = [0.0]
    for end in range(1, columns + 1):
        prefixes.append(
            max(
                [prefixes[-1] + base]
                + [prefixes[start] + width for start, stop, width in constraints if stop == end]
            )
        )
    return [b - a for a, b in pairwise(prefixes)]


def _widths(model, style, constraints, preferred, issues):
    count, width = model.columns, style.width_mm
    if style.columns and len(style.columns) != count:
        raise ValueError(f"Table needs {count} column sizes")
    if style.column_alignments and len(style.column_alignments) != count:
        raise ValueError(f"Table needs {count} column alignments")
    base = style.padding_left_mm + style.padding_right_mm + style.stroke_width_mm
    minimum = _interval_minimum(count, constraints, base)
    if style.width_mode == "equal":
        widths = [width / count] * count
    elif style.width_mode == "ratio":
        widths = [width * v / sum(style.columns) for v in style.columns]
    elif style.width_mode == "fixed":
        widths = list(style.columns)
        if abs(sum(widths) - width) > 1e-7:
            issues.append(
                Diagnostic(
                    "table-fixed-width-mismatch",
                    "Fixed columns must sum to the configured table width",
                    model.node.span,
                )
            )
    else:
        widths = minimum[:]
        remaining = max(0, width - sum(widths))
        wants = _interval_minimum(count, preferred, base)
        deficits = [max(0, p - m) for p, m in zip(wants, widths)]
        if sum(deficits) > 0:
            fraction = min(1, remaining / sum(deficits))
            widths = [m + fraction * d for m, d in zip(widths, deficits)]
        remaining = max(0, width - sum(widths))
        widths = [v + remaining / count for v in widths]
        if sum(minimum) <= width + 1e-7:
            widths = _balance(widths, constraints, preferred, base)
        if sum(minimum) > width + 1e-7:
            issues.append(
                Diagnostic(
                    "table-width-overflow",
                    f"Table needs at least {sum(minimum):.3f} mm; configured {width:.3f} mm. Increase width or reduce character size.",
                    model.node.span,
                )
            )
    for start, end, needed in constraints:
        if sum(widths[start:end]) < needed - 1e-7:
            issues.append(
                Diagnostic(
                    "table-column-overflow",
                    f"Columns {start + 1}–{end} need {needed:.3f} mm",
                    model.node.span,
                )
            )
    return tuple(widths)


def _balance(widths, constraints, preferred, base):
    # The minimum prefix solution may put an entire colspan deficit in its last
    # column. Move interior boundaries toward preferred proportions while every
    # interval constraint remains feasible, with a fixed iteration budget.
    count = len(widths)
    weights = [
        max([base] + [w / (b - a) for a, b, w in preferred if a <= c < b]) for c in range(count)
    ]
    nonempty = [v for v in weights if v > base + 1e-9]
    if nonempty:
        # An intentionally blank heading column still represents a grid column.
        # Give it a normal preferred width instead of collapsing it to a border.
        weights = [v if v > base + 1e-9 else sum(nonempty) / len(nonempty) for v in weights]
    desired = list(accumulate((sum(widths) * v / sum(weights) for v in weights), initial=0))
    prefixes = list(accumulate(widths, initial=0))
    incoming, outgoing = [[] for _ in prefixes], [[] for _ in prefixes]
    for a, b, w in [*constraints, *((i, i + 1, base) for i in range(count))]:
        incoming[b].append((a, w))
        outgoing[a].append((b, w))
    for _ in range(20):
        movement = 0.0
        for index in range(1, count):
            lower = max(prefixes[a] + w for a, w in incoming[index])
            upper = min(prefixes[b] - w for b, w in outgoing[index])
            value = min(upper, max(lower, desired[index]))
            movement = max(movement, abs(value - prefixes[index]))
            prefixes[index] = value
        if movement < 1e-8:
            break
    return [b - a for a, b in pairwise(prefixes)]


@cached_measurement
def measure_table(
    model: TableModel,
    resolver,
    style: TableStyle | None = None,
    *,
    cancelled=None,
    math_style=None,
    footnote_style=None,
    latin_spacing="capture",
    punctuation_spacing="capture",
    han_variation=None,
):
    style = style or TableStyle()
    check_cancel(cancelled)
    issues, raw, constraints, preferred = [], [], [], []
    clearance = style.padding_left_mm + style.padding_right_mm + style.stroke_width_mm
    vertical = style.padding_top_mm + style.padding_bottom_mm + style.stroke_width_mm
    text_style = StyleProfile(style.text_em_mm, style.line_height_mm, style.stroke_width_mm)
    decimal = [[0.0, 0.0] for _ in range(model.columns)]
    if style.column_alignments and len(style.column_alignments) != model.columns:
        raise ValueError(f"Table needs {model.columns} column alignments")
    for cell in model.cells:
        check_cancel(cancelled)
        runs = [r for child in cell.node.children for r in inline_runs(child)]
        boxes, diagnostics = measure_runs(
            runs,
            resolver,
            text_style,
            cancelled=cancelled,
            math_style=math_style,
            footnote_style=footnote_style,
            latin_spacing=latin_spacing,
            punctuation_spacing=punctuation_spacing,
            han_variation=han_variation,
            character_em={
                c: style.digit_height_mm / style.numeric_height_em for c in "0123456789."
            },
        )
        # The table numeric profile uses the legacy bank's compact side bearings.
        # Translate the immutable guide coordinates; never rescale each specimen
        # to its own height or change the original points/metadata.
        numeric_boxes = []
        for box in boxes:
            char = box.run.occurrence.text
            if box.glyph and char in "0123456789." and box.run.kind != "code_inline":
                left, _, right, _ = box.glyph.bounds
                ink_width = (right - left) * box.em
                spacing = max(0.16 * style.digit_height_mm, style.stroke_width_mm)
                advance = max(
                    (0.2 if char == "." else 0.45) * style.digit_height_mm, ink_width + spacing
                )
                bearing = (advance - ink_width - spacing) / 2
                box = replace(
                    box,
                    advance=advance,
                    origin_offset=bearing - left * box.em + style.stroke_width_mm / 2,
                )
            numeric_boxes.append(box)
        boxes = numeric_boxes
        if (
            style.numeric_spacing == "legacy-ink"
            and boxes
            and all(b.glyph and b.run.occurrence.text in "0123456789." for b in boxes)
        ):
            # The old tool measures a complete numeric cell by its ink width,
            # excluding outer side bearings. Keep internal advances unchanged.
            first = boxes[0]
            leading = max(
                0,
                first.origin_offset + first.glyph.bounds[0] * first.em - style.stroke_width_mm / 2,
            )
            boxes[0] = replace(
                first, advance=first.advance - leading, origin_offset=first.origin_offset - leading
            )
            last = boxes[-1]
            trailing = max(
                0,
                last.advance
                - (last.origin_offset + last.glyph.bounds[2] * last.em + style.stroke_width_mm / 2),
            )
            boxes[-1] = replace(last, advance=last.advance - trailing)
        issues.extend(diagnostics)
        narrow = break_lines(boxes, 0.001, cancelled=cancelled)
        unwrapped = break_lines(boxes, float("inf"), cancelled=cancelled)
        minimum = max(sum(b.advance for b in line) for line in narrow) + clearance
        wanted = max(sum(b.advance for b in line) for line in unwrapped) + clearance
        align = cell.align
        if style.column_alignments and cell.row >= model.header_rows:
            configured = style.column_alignments[cell.column]
            if configured != "auto":
                align = configured
        before = after = 0.0
        if align == "decimal":
            text = "".join(b.run.occurrence.text for b in boxes)
            if cell.colspan != 1 or not NUMERIC.fullmatch(text):
                issues.append(
                    Diagnostic(
                        "table-decimal-invalid",
                        "Decimal alignment requires one numeric value in a single column",
                        cell.node.span,
                    )
                )
                align = "center"
            else:
                point = next(
                    (i for i, b in enumerate(boxes) if b.run.occurrence.text == "."), len(boxes)
                )
                before = sum(b.advance for b in boxes[:point])
                after = sum(b.advance for b in boxes[point:])
                decimal[cell.column][0] = max(decimal[cell.column][0], before)
                decimal[cell.column][1] = max(decimal[cell.column][1], after)
        constraints.append((cell.column, cell.column + cell.colspan, minimum))
        preferred.append((cell.column, cell.column + cell.colspan, wanted))
        raw.append((cell, boxes, minimum, wanted, align, before, after))
    for column, (left, right) in enumerate(decimal):
        if left or right:
            constraints.append((column, column + 1, left + right + clearance))
            preferred.append(constraints[-1])
    widths = _widths(model, style, constraints, preferred, issues)
    cells, heights = [], [style.min_row_height_mm] * model.rows
    for cell, boxes, minimum, wanted, align, before, after in raw:
        check_cancel(cancelled)
        width = max(0.001, sum(widths[cell.column : cell.column + cell.colspan]) - clearance)
        lines = break_lines(boxes, width, cancelled=cancelled)
        metrics = []
        for line in lines:
            ascent = max(
                [0.88 * style.text_em_mm + style.stroke_width_mm / 2] + [b.ascent for b in line]
            )
            descent = max(
                [0.12 * style.text_em_mm + style.stroke_width_mm / 2] + [b.descent for b in line]
            )
            metrics.append((ascent, descent, max(style.line_height_mm, ascent + descent)))
            if sum(b.advance for b in line) > width + 1e-7:
                issues.append(
                    Diagnostic(
                        "table-cell-width-overflow",
                        "Unbreakable cell content exceeds its column; change width or character size",
                        cell.node.span,
                    )
                )
        measured = MeasuredCell(
            cell,
            tuple(tuple(line) for line in lines),
            tuple(metrics),
            minimum,
            wanted,
            align,
            before,
            after,
        )
        cells.append(measured)
        if cell.rowspan == 1 and not style.fixed_row_height:
            heights[cell.row] = max(heights[cell.row], measured.content_height + vertical)
    for measured in sorted(cells, key=lambda m: m.cell.rowspan):
        cell = measured.cell
        available = sum(heights[cell.row : cell.row + cell.rowspan])
        required = measured.content_height + vertical
        if required > available + 1e-7:
            if style.fixed_row_height:
                issues.append(
                    Diagnostic(
                        "table-fixed-row-overflow",
                        f"Cell needs {required:.3f} mm height; fixed rows supply {available:.3f} mm",
                        cell.node.span,
                    )
                )
            else:
                for r in range(cell.row, cell.row + cell.rowspan):
                    heights[r] += (required - available) / cell.rowspan
    return MeasuredTable(
        model,
        style,
        tuple(cells),
        widths,
        tuple(heights),
        tuple(tuple(v) for v in decimal),
        tuple(issues),
    )
