"""Versioned Markdown structure inspector; layout support is a separate capability."""

from __future__ import annotations

from dataclasses import dataclass

from ..math.schema import MATH_VERSION, MathNode
from ._markdown_mapping import LocatedString, located, make_parser
from .cancellation import check_cancel
from .editing import SourceSession
from .image_labels import (
    PATTERN as IMAGE_LABEL_PATTERN, PREFIX as IMAGE_LABEL_PREFIX, ImageLabel,
    bind_image_labels, validate_label_text,
)
from .limits import bounded_parse, validate_nodes
from .obsidian import OBSIDIAN_VERSION
from .schema import Diagnostic, Occurrence, SourceSpan, digest
from .source import clusters
from .source_map import MappedText, parser_view

DIALECT_VERSION = "inkstruct-markdown-v1/markdown-it-py-4.0.0/break-commands-v2"


@dataclass(frozen=True)
class SemanticNode:
    node_id: str
    kind: str
    span: SourceSpan
    children: tuple[SemanticNode, ...] = ()
    occurrences: tuple[Occurrence, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()
    raw_content: str = ""
    math: MathNode | None = None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class MarkdownDocument:
    document_id: str
    revision: int
    source: str
    nodes: tuple[SemanticNode, ...]
    diagnostics: tuple[Diagnostic, ...]
    dialect: str = DIALECT_VERSION
    export_scope: str = "document"
    math_version: str = MATH_VERSION

    @property
    def occurrences(self):
        return tuple(o for root in self.nodes for n in root.walk() for o in n.occurrences)

    @property
    def content_key(self):
        # Stale-request protection must use revision separately from this content key.
        return digest(
            {
                "source": self.source,
                "dialect": self.dialect,
                "export_scope": self.export_scope,
                "math_version": self.math_version,
                "scope": [(n.kind, n.span.start, n.span.end) for n in self.nodes],
            }
        )


def dialect_version(dialect):
    if dialect not in {"markdown", "obsidian"}:
        raise ValueError("Unknown Markdown dialect")
    return OBSIDIAN_VERSION if dialect == "obsidian" else DIALECT_VERSION


@bounded_parse
def parse_markdown(
    session: SourceSession | str, *, dialect="markdown", cancelled=None, field_blocks=False
) -> MarkdownDocument:
    check_cancel(cancelled)
    version = dialect_version(dialect) + ("/named-fields-v1" if field_blocks else "")
    session = SourceSession(session) if isinstance(session, str) else session
    view = parser_view(session.source, cancelled=cancelled)
    source = located(view)
    line_starts = [0] + [i + 1 for i, c in enumerate(source) if c == "\n"]
    line_starts.append(len(source))
    diagnostics = []
    html_sources = {}
    label_parser = None
    has_image_labels = False

    def source_span(token, fallback):
        if "source_span" in token.meta:
            return token.meta["source_span"]
        if token.type == "inline" and isinstance(token.content, LocatedString) and token.content:
            return SourceSpan(token.content.ranges[0].start, token.content.ranges[-1].end)
        if token.map:
            a, b = (min(line_starts[i], len(source)) for i in token.map)
            if a < b:
                return view.covering_span(a, b)
        if isinstance(token.content, LocatedString) and token.content:
            return SourceSpan(token.content.ranges[0].start, token.content.ranges[-1].end)
        return fallback

    def build(tokens, fallback):
        nonlocal label_parser, has_image_labels
        roots, stack = [], []
        for token in tokens:
            check_cancel(cancelled)
            if token.type == "text" and not token.content:
                continue
            if token.nesting == -1:
                if not stack:
                    raise ValueError("Unbalanced parser token stream")
                opened = stack.pop()
                closing = source_span(token, opened["span"])
                opened["span"] = SourceSpan(
                    min(opened["span"].start, closing.start), max(opened["span"].end, closing.end)
                )
                children = tuple(opened.pop("pending"))
                infer_span = opened.pop("infer_span")
                if infer_span and children:
                    opened["span"] = SourceSpan(children[0].span.start, children[-1].span.end)
                    opened["node_id"] = digest(
                        [session.document_id, opened["kind"], children[0].node_id]
                    )
                node = SemanticNode(**opened, children=children)
                (stack[-1]["pending"] if stack else roots).append(node)
                continue
            span = source_span(token, stack[-1]["span"] if stack else fallback)
            kind = token.type.removesuffix("_open")
            if "break_error" in token.meta:
                diagnostics.append(Diagnostic("break-command-option", token.meta["break_error"], span))
            if "field_error" in token.meta:
                diagnostics.append(Diagnostic("template-field-syntax", token.meta["field_error"], span))
            anchor = session.atom_ids[span.start] if span.start < len(session.atom_ids) else "eof"
            node_id = digest(
                [session.document_id, "node", kind, anchor, token.meta.get("empty_column")]
            )
            attrs = tuple(sorted((str(k), str(v)) for k, v in token.attrs.items()))
            attrs += (("markup", str(token.markup)), ("info", str(token.info)), ("tag", token.tag))
            if token.nesting == 1:
                stack.append(
                    {
                        "node_id": node_id,
                        "kind": kind,
                        "span": span,
                        "attributes": attrs,
                        "pending": [],
                        "infer_span": not token.map and "source_span" not in token.meta,
                    }
                )
                continue
            if token.type in {"math_inline", "math_block"}:
                from .math_adapter import math_node

                mapped = MappedText(
                    str(token.content), token.content.ranges if token.content else ()
                )
                node = math_node(
                    kind, mapped, span, node_id, session, diagnostics, token.meta.get("math_error")
                )
            elif token.type == "inline":
                children = build(token.children or [], span)
                if "task_span" in token.meta:
                    task_span = token.meta["task_span"]
                    task_id = digest(
                        [session.document_id, "task-checkbox", session.atom_ids[task_span.start]]
                    )
                    task_occurrence = session.occurrence_id(
                        SourceSpan(task_span.start, task_span.start + 1),
                        role="task-checkbox",
                        text="\ufffc",
                    )
                    task = SemanticNode(
                        task_id,
                        "task_checkbox",
                        task_span,
                        occurrences=(Occurrence(task_occurrence, task_id, task_span, "\ufffc"),),
                        attributes=(
                            ("checked", "true" if token.meta["task_checked"] else "false"),
                        ),
                    )
                    children = (task, *children)
                node = SemanticNode(node_id, "inline", span, children, attributes=attrs)
            elif token.type == "image":
                identity = session.occurrence_id(span, role="image", text="\ufffc")
                node = SemanticNode(
                    node_id,
                    "image",
                    span,
                    build(token.children or [], span),
                    (Occurrence(identity, node_id, span, "\ufffc"),),
                    attrs,
                    str(token.content),
                )
            elif token.type == "html_block" and token.content.lstrip().startswith(IMAGE_LABEL_PREFIX):
                has_image_labels = True
                comment = token.content.strip()
                match = IMAGE_LABEL_PATTERN.fullmatch(comment)
                try:
                    if not match:
                        raise ValueError("图片标注格式无效。")
                    x, y, size = match.group("x", "y", "size")
                    ImageLabel.from_fields(x, y, size)
                    text = comment[match.start("text"):match.end("text")]
                    validate_label_text(text)
                except ValueError as error:
                    diagnostics.append(Diagnostic("image-label-syntax", str(error), span))
                    node = SemanticNode(node_id, "image_label", span)
                else:
                    if label_parser is None:
                        label_parser = make_parser(cancelled=cancelled)
                        label_parser.inline.ruler.enableOnly(["text", "escape", "entity", "math_inline"])
                    children = build(label_parser.inline.parse(text, label_parser, {}, []), span)
                    node = SemanticNode(node_id, "image_label", span, children,
                                        attributes=(("x", x), ("y", y), ("size", size)), raw_content=str(text))
            else:
                occurrences = []
                ranges = token.meta.get("display_ranges")
                if ranges is None and isinstance(token.content, LocatedString):
                    ranges = token.content.ranges
                if (
                    token.type
                    in {
                        "text",
                        "text_special",
                        "code_inline",
                        "fence",
                        "code_block",
                        "wiki_link",
                        "wiki_embed",
                    }
                    and token.content
                ):
                    if ranges is None or len(ranges) != len(token.content):
                        raise ValueError(f"Missing exact source mapping for {token.type}")
                    duplicates = {}
                    for local, text in clusters(str(token.content)):
                        check_cancel(cancelled)
                        mapped = SourceSpan(ranges[local.start].start, ranges[local.end - 1].end)
                        index = duplicates.get(mapped, 0)
                        duplicates[mapped] = index + 1
                        identity = session.occurrence_id(mapped, role=f"text:{index}", text=text)
                        occurrences.append(Occurrence(identity, node_id, mapped, text))
                        if (
                            token.type in {"fence", "code_block"}
                            and "\x00" in session.source[mapped.start : mapped.end]
                        ):
                            diagnostics.append(
                                Diagnostic(
                                    "code-control-character",
                                    "NUL in literal code cannot be rendered faithfully",
                                    mapped,
                                )
                            )
                elif token.type in {"softbreak", "hardbreak", "break_hint"} and span.start < span.end:
                    text = " " if token.type == "break_hint" else "\n"
                    identity = session.occurrence_id(span, role=token.type, text=text)
                    occurrences.append(Occurrence(identity, node_id, span, text))
                if token.type in {"wiki_link", "wiki_embed"}:
                    if token.meta.get("obsidian_error"):
                        diagnostics.append(
                            Diagnostic(
                                "obsidian-reference-invalid", token.meta["obsidian_error"], span
                            )
                        )
                    elif token.type == "wiki_embed":
                        diagnostics.append(
                            Diagnostic(
                                "obsidian-embed-label-only",
                                "Embed is shown as its explicit label; target content is not expanded",
                                span,
                                "warning",
                            )
                        )
                if token.type in {"html_block", "html_inline", "image"}:
                    diagnostics.append(
                        Diagnostic(
                            "layout-pending",
                            f"{token.type} is preserved; layout capability pending",
                            span,
                            severity="warning",
                        )
                    )
                node = SemanticNode(
                    node_id,
                    kind,
                    span,
                    occurrences=tuple(occurrences),
                    attributes=attrs,
                    raw_content=str(token.content),
                )
            if token.type == "html_block" and isinstance(token.content, LocatedString):
                html_sources[node_id] = token.content
            (stack[-1]["pending"] if stack else roots).append(node)
        if stack:
            raise ValueError("Unclosed parser structure")
        return tuple(roots)

    # HTML is parsed into inert source nodes, never executed, fetched or rendered here.
    parser = make_parser(obsidian=dialect == "obsidian", cancelled=cancelled)
    if field_blocks:
        from .named_fields import install_fields
        install_fields(parser,cancelled)
    tokens = parser.parse(source)
    check_cancel(cancelled)
    nodes = build(tokens, SourceSpan(0, len(session.source)))
    validate_nodes(nodes, cancelled=cancelled)
    if has_image_labels:
        nodes = bind_image_labels(nodes, diagnostics)
    from .tables import expand_html_tables

    nodes = expand_html_tables(nodes, session, diagnostics, html_sources)
    validate_nodes(nodes, cancelled=cancelled)
    check_cancel(cancelled)
    from .footnotes import resolve_footnotes

    nodes = resolve_footnotes(nodes, session, diagnostics)
    validate_nodes(nodes, cancelled=cancelled)
    check_cancel(cancelled)
    from .equations import resolve_equations

    nodes = resolve_equations(nodes, session, diagnostics)
    validate_nodes(nodes, cancelled=cancelled)
    check_cancel(cancelled)
    from .break_commands import constrain_flow_breaks

    nodes = constrain_flow_breaks(nodes, diagnostics, cancelled=cancelled)
    return MarkdownDocument(
        session.document_id,
        session.revision,
        session.source,
        nodes,
        tuple(diagnostics),
        dialect=version,
    )
