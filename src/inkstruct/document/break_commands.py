"""Mapped LaTeX line/page controls and template-body frame controls, never text macros."""

import re
from dataclasses import dataclass, replace

from .schema import Diagnostic, SourceSpan

LINE_COMMANDS = frozenset({"newline", "linebreak"})
PAGE_COMMANDS = frozenset({"newpage", "pagebreak", "clearpage"})
FRAME_COMMANDS = frozenset({"framebreak"})
FLOW_BREAK_KINDS = frozenset({"pagebreak", "framebreak"})
_COMMAND = re.compile(r"\\([A-Za-z]+)")


@dataclass(frozen=True)
class BreakCommand:
    name: str
    end: int
    strength: int = 4
    error: str = ""


def scan_break(source, start=0):
    match = _COMMAND.match(source, start)
    if match is None or match[1] not in LINE_COMMANDS | PAGE_COMMANDS | FRAME_COMMANDS:
        return None
    name, end, strength, error = match[1], match.end(), 4, ""
    if name in {"linebreak", "pagebreak"}:
        option = end
        while option < len(source) and source[option] in " \t":
            option += 1
        if source[option : option + 1] == "[":
            close = source.find("]", option + 1)
            end = close + 1 if close >= 0 else len(source)
            value = source[option + 1 : close].strip() if close >= 0 else ""
            if value not in {"0", "1", "2", "3", "4"}:
                error = "Break strength must be an integer from 0 to 4 in a closed bracket"
            else:
                strength = int(value)
    if source[end : end + 2] == "{}":
        end += 2
    return BreakCommand(name, end, strength, error)


def _token(state, match, start):
    kind = (
        "break_command_error"
        if match.error
        else "framebreak"
        if match.name in FRAME_COMMANDS
        else "pagebreak"
        if match.name in PAGE_COMMANDS
        else "hardbreak"
        if match.strength == 4
        else "break_hint"
    )
    token = state.push(kind, "br" if kind == "hardbreak" else "", 0)
    token.attrs = {"command": match.name, "strength": str(match.strength)}
    token.markup = str(state.src[start : match.end])
    token.meta["source_span"] = SourceSpan(
        state.src.ranges[start].start, state.src.ranges[match.end - 1].end
    )
    if match.error:
        token.meta["break_error"] = match.error
    return token


def inline_break(state, silent):
    start = state.pos
    match = scan_break(state.src, start)
    if match is None:
        return False
    if not silent:
        _token(state, match, start)
    state.pos = match.end
    # Control-word whitespace is syntax, not leading spaces on the next line.
    while match.strength == 4 and state.pos < state.posMax and state.src[state.pos].isspace():
        state.pos += 1
    return True


def block_flow_break(state, start, end, silent):
    if state.is_code_block(start):
        return False
    first = state.bMarks[start] + state.tShift[start]
    last = state.eMarks[start]
    match = scan_break(state.src, first)
    if (
        match is None
        or match.name not in PAGE_COMMANDS | FRAME_COMMANDS
        or match.end > last
        or state.src[match.end : last].strip()
    ):
        return False
    if not silent:
        token = _token(state, match, first)
        token.map = [start, start + 1]
        state.line = start + 1
    return True


def constrain_flow_breaks(nodes, diagnostics, *, context="", cancelled=None):
    """Only body flow may advance its cursor; embedded/fixed content cannot."""
    from .cancellation import check_cancel

    blocked = {"td", "th", "footnote_definition", "footnote_entry", "named_field", "image"}

    def visit(node, container=""):
        check_cancel(cancelled)
        container = node.kind if node.kind in blocked else container
        if (node.kind in FLOW_BREAK_KINDS and container
                and dict(node.attributes).get("blocked") != "true"):
            diagnostics.append(
                Diagnostic(
                    "frame-break-context" if node.kind == "framebreak" else "page-break-context",
                    ("Frame" if node.kind == "framebreak" else "Page")
                    + " breaks are inactive inside " + container,
                    node.span,
                    "warning",
                )
            )
            node = replace(node, attributes=(*node.attributes, ("blocked", "true")))
        return replace(node, children=tuple(visit(child, container) for child in node.children))

    return tuple(visit(node, context) for node in nodes)


def html_break_commands(nodes, session, diagnostics):
    """Apply the same controls to mapped HTML cell text, preserving code/math."""
    from .markdown import SemanticNode
    from .schema import Occurrence, digest

    def text_parts(node):
        text = node.raw_content
        starts, ranges, offset = [], [], 0
        for occurrence in node.occurrences:
            starts.append((offset, offset + len(occurrence.text), occurrence))
            ranges.extend([occurrence.span] * len(occurrence.text))
            offset += len(occurrence.text)
        if offset != len(text):
            return (node,)
        result, start, pos = [], 0, 0

        def flush(end):
            occurrences = tuple(o for a, b, o in starts if start <= a and b <= end)
            if occurrences:
                span = SourceSpan(occurrences[0].span.start, occurrences[-1].span.end)
                identity = digest([node.node_id, "html-break-text", session.atom_ids[span.start]])
                result.append(
                    replace(
                        node,
                        node_id=identity,
                        span=span,
                        occurrences=tuple(replace(o, node_id=identity) for o in occurrences),
                        raw_content=text[start:end],
                    )
                )

        while pos < len(text):
            if text.startswith("\\\\", pos):
                pos += 2
                continue
            match = scan_break(text, pos)
            if match is None:
                pos += 1
                continue
            flush(pos)
            span = SourceSpan(ranges[pos].start, ranges[match.end - 1].end)
            kind = (
                "break_command_error"
                if match.error
                else "framebreak"
                if match.name in FRAME_COMMANDS
                else "pagebreak"
                if match.name in PAGE_COMMANDS
                else "hardbreak"
                if match.strength == 4
                else "break_hint"
            )
            identity = digest(
                [session.document_id, "html-break", kind, session.atom_ids[span.start]]
            )
            value = "\n" if kind == "hardbreak" else " "
            occurrences = (
                ()
                if kind in FLOW_BREAK_KINDS | {"break_command_error"}
                else (
                    Occurrence(
                        session.occurrence_id(span, role=kind, text=value), identity, span, value
                    ),
                )
            )
            result.append(
                SemanticNode(
                    identity,
                    kind,
                    span,
                    occurrences=occurrences,
                    attributes=(("command", match.name), ("strength", str(match.strength))),
                )
            )
            if match.error:
                diagnostics.append(Diagnostic("break-command-option", match.error, span))
            pos = match.end
            while match.strength == 4 and pos < len(text) and text[pos].isspace():
                pos += 1
            start = pos
        if not result:
            return (node,)
        flush(len(text))
        return tuple(result)

    def visit(node):
        if node.kind == "text":
            return text_parts(node)
        if node.kind == "code_inline":
            return (node,)
        return (
            replace(node, children=tuple(part for child in node.children for part in visit(child))),
        )

    return tuple(part for node in nodes for part in visit(node))
