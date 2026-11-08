"""Task markers are source syntax, never font glyphs or hidden widget state."""

import re

from .schema import SourceSpan


def task_list_core(state):
    """Recognize only the first direct paragraph of an actual parsed list item."""
    for i, token in enumerate(state.tokens):
        if (
            token.type != "inline"
            or i < 2
            or state.tokens[i - 1].type != "paragraph_open"
            or state.tokens[i - 2].type != "list_item_open"
        ):
            continue
        match = re.match(r"^ *\[([ \txX])\](?:[ \t\n\v\f]+|$)", token.content)
        if not match:
            continue
        ranges = token.content.ranges
        token.meta["task_span"] = SourceSpan(
            ranges[match.start(1) - 1].start, ranges[match.end(1)].end
        )
        token.meta["task_checked"] = match[1] in "xX"
        token.meta["source_span"] = SourceSpan(ranges[0].start, ranges[-1].end)
        token.content = token.content[match.end() :]


def task_patch(document, occurrence_id):
    """Return one explicit scalar replacement in the authoritative parsed revision."""
    node = next(
        (
            n
            for root in document.nodes
            for n in root.walk()
            if n.kind == "task_checkbox" and n.occurrences[0].occurrence_id == occurrence_id
        ),
        None,
    )
    if node is None:
        raise ValueError("Task checkbox no longer exists in this source")
    original = document.source[node.span.start : node.span.end]
    if original not in {"[ ]", "[\t]", "[x]", "[X]"}:
        raise ValueError("Task source range does not match its marker")
    return node.span.start + 1, node.span.start + 2, "x" if original[1].isspace() else " "
