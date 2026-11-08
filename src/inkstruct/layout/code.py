"""Code lines preserve literal whitespace and break only at source newlines."""

import unicodedata
from dataclasses import replace

from ..document.schema import Diagnostic
from .inline import check_cancel, measure_runs
from .measurement_cache import cached_measurement


@cached_measurement
def measure_code(runs, resolver, style, config, *, width=None, cancelled=None):
    style = replace(style, em_mm=config.em_mm, line_height_mm=config.line_height_mm)
    boxes, issues = measure_runs(runs, resolver, style, cancelled=cancelled)
    lines, line, column = [], [], 0
    for box in boxes:
        check_cancel(cancelled)
        text = box.run.occurrence.text
        if text == "\n":
            line.append(replace(box, advance=0, status="line-break"))
            lines.append(line)
            line, column = [], 0
            continue
        cells = config.tab_columns - column % config.tab_columns if text == "\t" else 1
        advance = cells * config.advance_mm
        if box.glyph and box.advance > advance + 1e-9:
            issues.append(
                Diagnostic(
                    "code-cell-overflow",
                    "Code glyph exceeds fixed cell width; enlarge advance or reduce code em",
                    box.run.occurrence.span,
                )
            )
        if any(unicodedata.category(c) == "Cc" for c in text) and text != "\t":
            issues.append(
                Diagnostic(
                    "code-control-character",
                    "Unsupported literal control character in code",
                    box.run.occurrence.span,
                )
            )
        line.append(replace(box, advance=advance))
        column += cells
    if line or not lines:
        lines.append(line)
    if not config.wrap_lines:
        return lines, issues, set()
    wrapped, continuations = [], set()
    for line in lines:
        chunk, used, continued = [], 0, False
        for box in line:
            check_cancel(cancelled)
            if (
                width is not None
                and used + box.advance > width + 1e-9
                and chunk
                and box.status != "line-break"
            ):
                if continued:
                    continuations.add(len(wrapped))
                wrapped.append(chunk)
                chunk, used, continued = [], 0, True
            chunk.append(box)
            used += box.advance
        if continued:
            continuations.add(len(wrapped))
        wrapped.append(chunk)
    return wrapped, issues, continuations
