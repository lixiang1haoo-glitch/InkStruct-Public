"""Source-mapped footnote syntax and stable reference/definition relationships.

This is an explicit InkStruct dialect: case-sensitive labels without whitespace,
first-reference numbering, four-column continuation indentation. Page allocation
belongs to the layout layer, never to Markdown parsing.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .schema import Diagnostic, Occurrence, SourceSpan, digest

_LABEL = r"[^\s\[\]\\\x00-\x1f\x7f]{1,64}"
_DEFINITION = re.compile(r"\[\^(" + _LABEL + r")\]:[ \t]*")
_REFERENCE = re.compile(r"\[\^(" + _LABEL + r")\]")
MAX_DEFINITIONS = 128
MAX_REFERENCES = 1024


def footnote_reference(state, silent):
    match = _REFERENCE.match(state.src, state.pos, state.posMax)
    if not match:
        return False
    if not silent:
        count = state.env.get("inkstruct_footnote_references", 0) + 1
        if count > MAX_REFERENCES:
            raise ValueError("Footnotes exceed the 1024 reference budget")
        state.env["inkstruct_footnote_references"] = count
        token = state.push("footnote_reference", "", 0)
        token.attrSet("label", match[1])
        token.meta["source_span"] = SourceSpan(
            state.src.ranges[state.pos].start, state.src.ranges[match.end() - 1].end
        )
    state.pos = match.end()
    return True


def footnote_definition(state, start, end, silent):
    if state.is_code_block(start):
        return False
    first = state.bMarks[start] + state.tShift[start]
    match = _DEFINITION.match(state.src, first, state.eMarks[start])
    if not match:
        return False
    if silent:
        return True
    count = state.env.get("inkstruct_footnote_definitions", 0) + 1
    if count > MAX_DEFINITIONS:
        raise ValueError("Footnotes exceed the 128 definition budget")
    state.env["inkstruct_footnote_definitions"] = count
    # A fresh block parser is needed to preserve exact first-line and continuation
    # ranges. Explicit depth accounting complements markdown-it's local nesting cap.
    depth = state.env.get("inkstruct_footnote_depth", 0)
    if depth >= 16:
        raise ValueError("Footnote definition nesting exceeds the supported depth")
    last = start + 1
    while last < end:
        if state.isEmpty(last):
            probe = last + 1
            while probe < end and state.isEmpty(probe):
                probe += 1
            if probe == end or state.sCount[probe] < state.blkIndent + 4:
                break
            last = probe
        if state.sCount[last] < state.blkIndent + 4:
            break
        last += 1
    # Include the first LF only when a continuation follows. LocatedString slicing
    # and getLines retain CRLF/tab provenance in original Unicode scalar offsets.
    body = state.src[match.end() : state.eMarks[start] + int(last > start + 1)]
    if last > start + 1:
        body += state.getLines(start + 1, last, state.blkIndent + 4, False)
    marker_end = first + len(match[1]) + 4  # [^label]:, excluding content spacing.
    span = SourceSpan(
        state.src.ranges[first].start, state.src.ranges[state.eMarks[last - 1] - 1].end
    )
    opened = state.push("footnote_definition_open", "", 1)
    opened.block = True
    opened.attrSet("label", match[1])
    opened.attrSet("marker_start", state.src.ranges[first].start)
    opened.attrSet("marker_end", state.src.ranges[marker_end - 1].end)
    opened.meta["source_span"] = span
    children = []
    state.env["inkstruct_footnote_depth"] = depth + 1
    try:
        state.md.block.parse(body, state.md, state.env, children)
    finally:
        state.env["inkstruct_footnote_depth"] = depth
    starts = [0] + [i + 1 for i, char in enumerate(body) if char == "\n"]
    starts.append(len(body))
    for token in children:
        if token.map:
            a, b = (starts[index] for index in token.map)
            if a < b:
                token.meta.setdefault(
                    "source_span", SourceSpan(body.ranges[a].start, body.ranges[b - 1].end)
                )
            token.map = None  # These map indices belong to the local body, not the document.
    state.tokens.extend(children)
    closed = state.push("footnote_definition_close", "", -1)
    closed.meta["source_span"] = span
    state.line = last
    return True


def resolve_footnotes(nodes, session, diagnostics):
    """Link references after the whole file is parsed, without moving source nodes."""
    definitions, references, order = {}, [], []

    def visit(node, *, in_definition=False, top=False):
        attrs = dict(node.attributes)
        if node.kind == "footnote_definition":
            label = attrs["label"]
            if not top:
                diagnostics.append(
                    Diagnostic(
                        "footnote-definition-context",
                        "Footnote definitions must be top-level blocks",
                        node.span,
                    )
                )
            if label in definitions:
                diagnostics.append(
                    Diagnostic(
                        "footnote-duplicate-definition",
                        f"Duplicate footnote definition: {label}",
                        node.span,
                    )
                )
            else:
                definitions[label] = node
            in_definition = True
        elif node.kind == "footnote_reference":
            label = attrs["label"]
            references.append(node)
            if in_definition:
                diagnostics.append(
                    Diagnostic(
                        "footnote-recursive-reference",
                        "References inside footnote definitions are not supported",
                        node.span,
                    )
                )
            elif label not in order:
                order.append(label)
        for child in node.children:
            visit(child, in_definition=in_definition)

    for root in nodes:
        visit(root, top=True)
    for reference in references:
        label = dict(reference.attributes)["label"]
        if label not in definitions:
            diagnostics.append(
                Diagnostic(
                    "footnote-missing-definition",
                    f"Missing footnote definition: {label}",
                    reference.span,
                )
            )
    for label, node in definitions.items():
        if label not in order:
            diagnostics.append(
                Diagnostic(
                    "footnote-unused-definition",
                    f"Footnote definition has no body reference: {label}",
                    node.span,
                )
            )
        if not node.children:
            diagnostics.append(
                Diagnostic(
                    "footnote-empty-definition", f"Footnote definition is empty: {label}", node.span
                )
            )
    numbers = {label: str(index + 1) for index, label in enumerate(order)}

    def link(node):
        children = tuple(link(child) for child in node.children)
        if node.kind not in {"footnote_reference", "footnote_definition"}:
            return replace(node, children=children) if children != node.children else node
        attrs = dict(node.attributes)
        label = attrs["label"]
        number = numbers.get(label, "")
        definition = definitions.get(label)
        attrs.update(number=number, definition_id=definition.node_id if definition else "")
        span = (
            SourceSpan(int(attrs["marker_start"]), int(attrs["marker_end"]))
            if node.kind == "footnote_definition"
            else node.span
        )
        anchor = session.atom_ids[span.start]
        # Numbering is generated display text, not source text. Keep identity tied
        # to the actual marker, slot and displayed digit. A renumbered digit needs
        # a new asset selection; the reference/definition node remains stable.
        occurrences = tuple(
            Occurrence(
                digest([session.document_id, node.kind, anchor, i, digit]),
                node.node_id,
                span,
                digit,
            )
            for i, digit in enumerate(number)
        )
        return replace(
            node,
            children=children,
            attributes=tuple(sorted(attrs.items())),
            occurrences=occurrences,
        )

    return tuple(link(node) for node in nodes)
