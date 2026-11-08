"""Distribute spare line width across legal gaps, keeping words and math intact."""
from dataclasses import replace
from itertools import pairwise

from ..assets.glyph_provider import is_han
from .plain import CLOSING, OPENING


def justify_line(line, width):
    """Return placement boxes and extra space after each box; source order is fixed."""
    visible = [i for i, box in enumerate(line) if box.status not in {"space", "line-break", "break-hint"}]
    if len(visible) < 2:
        return line, [0.0] * len(line)
    last = visible[-1]
    placed = [replace(box, advance=0) if i > last and box.status == "space" else box
              for i, box in enumerate(line)]
    spare = width - sum(box.advance for box in placed)
    extra = [0.0] * len(line)
    if spare <= 1e-9:
        return line, extra
    gaps = []
    for left, right in pairwise(visible):
        a, b = placed[left], placed[right]
        first, second = a.run.occurrence.text, b.run.occurrence.text
        if (first in OPENING or second in CLOSING or b.run.kind == "footnote_reference"
                or (a.run.kind == b.run.kind == "code_inline"
                    and a.run.occurrence.node_id == b.run.occurrence.node_id)):
            continue
        space = any(box.status == "space" and box.advance > 0 for box in placed[left+1:right])
        if (space or is_han(first) or is_han(second)
                or a.run.kind == "math_inline" or b.run.kind == "math_inline"):
            gaps.append(left)
    if not gaps:
        return line, extra
    for index in gaps:
        extra[index] = spare / len(gaps)
    return placed, extra
