"""Bind mathematical syntax to persistent document occurrences."""

from dataclasses import replace
from itertools import groupby

from ..math.parser import parse_math
from ._math_mapping import inline_math_end
from .markdown import SemanticNode
from .schema import Diagnostic, Occurrence, SourceSpan, digest
from .source import clusters
from .source_map import MappedText


def math_node(kind, mapped, span, node_id, session, diagnostics, error=None):
    if error:
        diagnostics.append(Diagnostic("math-delimiter", error, span))
        result = None
    else:
        result = parse_math(mapped, offset=span.start)
        diagnostics.extend(result.diagnostics)
    occurrences, duplicates = [], {}

    def bind(node):
        if node.kind == "Symbol":
            ordinal = duplicates.get(node.span, 0)
            duplicates[node.span] = ordinal + 1
            identity = session.occurrence_id(
                node.span, role=f"math-symbol:{ordinal}", text=node.value
            )
            occurrences.append(Occurrence(identity, node_id, node.span, node.value))
            node = replace(node, occurrence_id=identity)
        elif node.kind in {
            "Fraction",
            "Radical",
            "Delimited",
            "Matrix",
            "EquationTag",
            "EquationReference",
        }:
            # Structural specimens have their own stable choice without adding
            # visible text occurrences or changing source-coverage accounting.
            anchor = SourceSpan(node.span.start, node.span.start + 1)
            node = replace(
                node,
                occurrence_id=session.occurrence_id(
                    anchor,
                    role="math-construction:" + node.kind,
                    text=node.kind,
                ),
            )
        return replace(node, children=tuple(bind(c) for c in node.children))

    root = bind(result.root) if result and result.root else None
    return SemanticNode(
        node_id, kind, span, occurrences=tuple(occurrences), raw_content=mapped.text, math=root
    )


def html_math(nodes, session, diagnostics):
    """HTML entities may split a formula into several adjacent text callbacks.

    Combine adjacent text only within one inline container. Tags and code keep
    their boundaries; a formula crossing a tag is a delimiter diagnostic.
    """
    result = []
    for is_text, group in groupby(nodes, lambda n: n.kind == "text"):
        members = tuple(group)
        if not is_text:
            result.extend(
                replace(n, children=html_math(n.children, session, diagnostics))
                if n.children and n.kind != "code_inline"
                else n
                for n in members
            )
            continue
        if not any("$" in o.text for n in members for o in n.occurrences):
            result.extend(members)
            continue
        text = "".join(o.text for n in members for o in n.occurrences)
        ranges = tuple(o.span for n in members for o in n.occurrences for _ in o.text)
        mapped = MappedText(text, ranges)

        def append_plain(a, b, mapped=mapped):
            if a == b:
                return
            part = mapped.slice(a, b)
            span = part.covering_span()
            node_id = digest([session.document_id, "html", "text", session.atom_ids[span.start]])
            occurrences, duplicates = [], {}
            for local, value in clusters(part.text):
                source_span = part.covering_span(local.start, local.end)
                ordinal = duplicates.get(source_span, 0)
                duplicates[source_span] = ordinal + 1
                identity = session.occurrence_id(
                    source_span, role=f"html-text:{ordinal}", text=value
                )
                occurrences.append(Occurrence(identity, node_id, source_span, value))
            result.append(
                SemanticNode(
                    node_id, "text", span, occurrences=tuple(occurrences), raw_content=part.text
                )
            )

        start = at = 0
        while at < len(text):
            # HTML text is otherwise literal. Escaped dollars remain literal too.
            if text[at] == "\\" and at + 1 < len(text):
                at += 2
                continue
            if text[at] != "$":
                at += 1
                continue
            append_plain(start, at)
            end, a, b, error = inline_math_end(text, at)
            span = mapped.covering_span(at, end)
            node_id = digest(
                [session.document_id, "node", "math_inline", session.atom_ids[span.start], None]
            )
            result.append(
                math_node(
                    "math_inline", mapped.slice(a, b), span, node_id, session, diagnostics, error
                )
            )
            start = at = end
        append_plain(start, len(text))
    return tuple(result)
