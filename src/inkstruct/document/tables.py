"""Bounded table semantics with original-source ranges, independent of layout."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser

from .editing import SourceSession
from .markdown import SemanticNode
from .schema import Diagnostic, Occurrence, SourceSpan, digest
from .source import clusters

GROUPS = {"thead", "tbody", "tfoot"}
CELLS = {"td", "th"}
INLINE = {"strong", "b", "em", "i", "s", "del", "code", "a", "br"}
KINDS = {
    "b": "strong",
    "i": "em",
    "del": "s",
    "code": "code_inline",
    "a": "link",
    "br": "hardbreak",
}
ALIGNMENTS = {"left", "center", "right", "decimal"}


class TableSourceError(ValueError):
    def __init__(self, message, span):
        super().__init__(message)
        self.span = span


@dataclass(frozen=True)
class TableCell:
    node: SemanticNode
    row: int
    column: int
    rowspan: int
    colspan: int
    align: str = "center"
    valign: str = "auto"


@dataclass(frozen=True)
class TableModel:
    node: SemanticNode
    cells: tuple[TableCell, ...]
    rows: int
    columns: int
    header_rows: int

    @property
    def row_groups(self):
        """Atomic row intervals connected by any rowspan, in source order."""
        groups, start = [], 0
        while start < self.rows:
            end = start + 1
            for row in range(start, self.rows):
                if row >= end:
                    break
                end = max([end] + [c.row + c.rowspan for c in self.cells if c.row == row])
            groups.append((start, end))
            start = end
        return tuple(groups)


def table_model(node: SemanticNode) -> TableModel:
    if node.kind != "table":
        raise ValueError("Expected table node")
    rows, explicit_headers = [], 0
    for child in node.children:
        if child.kind in GROUPS:
            if child.kind == "thead":
                if rows or explicit_headers:
                    raise TableSourceError("Table headers must form one leading group", child.span)
                explicit_headers = len(child.children)
            rows.extend(child.children)
        else:
            rows.append(child)
    if not 1 <= len(rows) <= 100 or any(r.kind != "tr" for r in rows):
        raise TableSourceError("A table requires 1–100 rows", node.span)
    occupied, cells = {}, []
    header_rows = explicit_headers
    if not header_rows:
        for row in rows:
            if not row.children or not all(c.kind == "th" for c in row.children):
                break
            header_rows += 1
    for r, row in enumerate(rows):
        column = 0
        for cell in row.children:
            if cell.kind not in CELLS:
                raise TableSourceError("Rows may contain only cells", cell.span)
            attrs = dict(cell.attributes)
            rowspan, colspan = int(attrs.get("rowspan", 1)), int(attrs.get("colspan", 1))
            while (r, column) in occupied:
                column += 1
            if (
                not (1 <= rowspan <= 100 and 1 <= colspan <= 50)
                or r + rowspan > len(rows)
                or column + colspan > 50
            ):
                raise TableSourceError("Merged cell exceeds table or 50 columns", cell.span)
            if r < header_rows < r + rowspan:
                raise TableSourceError(
                    "A rowspan cannot cross the repeated-header boundary", cell.span
                )
            align = attrs.get("align", "center")
            if "style" in attrs:  # markdown-it's pipe-table alignment only
                match = re.fullmatch(r"text-align:(left|center|right)", attrs["style"])
                if not match:
                    raise TableSourceError("Unsupported cell style", cell.span)
                align = match[1]
            valign = attrs.get("valign", "auto")
            if align not in ALIGNMENTS or valign not in {"auto", "top", "middle", "bottom"}:
                raise TableSourceError("Unknown cell alignment", cell.span)
            item = TableCell(cell, r, column, rowspan, colspan, align, valign)
            for rr in range(r, r + rowspan):
                for cc in range(column, column + colspan):
                    if (rr, cc) in occupied:
                        raise TableSourceError("Merged cells overlap", cell.span)
                    occupied[rr, cc] = item
            cells.append(item)
            column += colspan
    if not occupied:
        raise TableSourceError("Table has no cells", node.span)
    columns = max(c for _, c in occupied) + 1
    if len(occupied) != len(rows) * columns:
        raise TableSourceError("Ragged table grid; add explicit empty cells", node.span)
    return TableModel(node, tuple(cells), len(rows), columns, header_rows)


class _TableHTML(HTMLParser):
    def __init__(self, session, span, mapped=None):
        super().__init__(convert_charrefs=False)
        self.session, self.span = session, span
        self.raw = str(mapped) if mapped is not None else session.source[span.start : span.end]
        self.ranges = (
            mapped.ranges
            if mapped is not None
            else tuple(SourceSpan(span.start + i, span.start + i + 1) for i in range(len(self.raw)))
        )
        self.starts = [0] + [i + 1 for i, c in enumerate(self.raw) if c == "\n"]
        self.stack, self.roots, self.diagnostics = [], [], []
        self.space = True
        self.cell_scalars = 0
        self.tokens = 0

    def local_position(self):
        line, col = self.getpos()
        return self.starts[line - 1] + col

    def position(self):
        local = self.local_position()
        return self.ranges[local].start if local < len(self.ranges) else self.span.end

    def token_end(self, length):
        return self.ranges[self.local_position() + length - 1].end

    def fail(self, message):
        start = self.position()
        raise TableSourceError(message, SourceSpan(start, min(self.span.end, start + 1)))

    def append(self, node):
        self.tokens += 1
        if self.tokens > 25_000:
            self.fail("HTML table exceeds node budget")
        (self.stack[-1]["children"] if self.stack else self.roots).append(node)

    def node(self, tag, start, end, *, children=(), attrs=(), occurrences=(), raw=""):
        kind = KINDS.get(tag, tag)
        identity = digest([self.session.document_id, "html", kind, self.session.atom_ids[start]])
        return SemanticNode(
            identity,
            kind,
            SourceSpan(start, end),
            tuple(children),
            tuple(occurrences),
            tuple(attrs),
            raw,
        )

    def handle_starttag(self, tag, attrs):
        if tag not in {"table", "tr", *GROUPS, *CELLS, *INLINE}:
            self.fail(f"Unsupported HTML table tag <{tag}>")
        parent = self.stack[-1]["tag"] if self.stack else None
        valid = (
            (tag == "table" and parent is None)
            or (tag in GROUPS and parent == "table")
            or (tag == "tr" and parent in {"table", *GROUPS})
            or (tag in CELLS and parent == "tr")
            or (tag in INLINE and parent in {*CELLS, *INLINE} and parent not in {"br", "code"})
        )
        if not valid or len(self.stack) >= 32:
            self.fail("Invalid HTML table nesting; explicit closing tags are required")
        values = {}
        for key, value in attrs:
            if key in values:
                self.fail("Duplicate HTML attribute")
            values[key] = value
        normalized = []
        for key, value in values.items():
            if key == "id":
                normalized.append((key, value or ""))
            elif tag in CELLS and key in {"rowspan", "colspan"}:
                if (
                    not value
                    or not re.fullmatch(r"[0-9]{1,3}", value)
                    or not 1 <= int(value) <= 100
                ):
                    self.fail("Rowspan/colspan must be positive bounded integers")
                normalized.append((key, value))
            elif tag in CELLS and (
                (key == "align" and value in ALIGNMENTS)
                or (key == "valign" and value in {"top", "middle", "bottom"})
            ):
                normalized.append((key, value))
            elif tag == "a" and key in {"href", "title"}:
                normalized.append((key, value or ""))  # inert metadata, never fetched
            elif tag == "table" and (
                (key == "border" and value == "1") or (key == "cellspacing" and value == "0")
            ):
                pass
            elif (
                tag == "table"
                and key == "cellpadding"
                and value
                and re.fullmatch(r"[0-9]{1,3}", value)
            ):
                self.warning("HTML cellpadding ignored; document millimetre padding applies")
            elif key == "style" and tag in {"table", *CELLS}:
                for declaration in (value or "").split(";"):
                    if not declaration.strip():
                        continue
                    pair = [p.strip().lower() for p in declaration.split(":", 1)]
                    if len(pair) != 2:
                        self.fail("Invalid style declaration")
                    k, v = pair
                    if k == "text-align" and v in {"left", "center", "right"}:
                        if tag in CELLS:
                            normalized.append(("align", v))
                        else:
                            self.warning(
                                "Table text-align ignored; document/cell alignment applies"
                            )
                    elif tag == "table" and k == "border-collapse" and v == "collapse":
                        pass
                    else:
                        self.fail("Unsupported CSS; use the document's table settings")
            else:
                self.fail(f"Unsupported <{tag}> attribute {key}")
        start = self.position()
        end = self.token_end(len(self.get_starttag_text()))
        if tag == "br":
            o = Occurrence(
                self.session.occurrence_id(SourceSpan(start, end), role="html-break", text="\n"),
                "",
                SourceSpan(start, end),
                "\n",
            )
            node = self.node(tag, start, end)
            self.append(replace(node, occurrences=(replace(o, node_id=node.node_id),)))
            self.space = True
        else:
            self.stack.append({"tag": tag, "start": start, "children": [], "attrs": normalized})
            if tag in CELLS:
                self.space, self.cell_scalars = True, 0

    def warning(self, message):
        start = self.position()
        self.diagnostics.append(
            Diagnostic(
                "table-source-style-ignored",
                message,
                SourceSpan(start, self.token_end(len(self.get_starttag_text()))),
                "warning",
            )
        )

    def handle_startendtag(self, tag, attrs):
        if tag != "br":
            self.fail("Only br may be self-closing")
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1]["tag"] != tag:
            self.fail("Mismatched HTML table closing tag")
        frame = self.stack.pop()
        close = self.raw.find(">", self.local_position())
        if close < 0:
            self.fail("Incomplete closing tag")
        node = self.node(
            tag,
            frame["start"],
            self.ranges[close].end,
            children=frame["children"],
            attrs=frame["attrs"],
        )
        if tag == "code":
            node = replace(
                node,
                children=(),
                occurrences=tuple(
                    replace(o, node_id=node.node_id)
                    for child in node.children
                    for n in child.walk()
                    for o in n.occurrences
                ),
            )
        if tag in CELLS:
            node = _trim_cell_end(node)
        self.append(node)

    def text(self, value, spans):
        if not any(f["tag"] in CELLS for f in self.stack):
            if value.strip():
                self.fail("Text must be inside a table cell")
            return
        self.cell_scalars += len(value)
        if self.cell_scalars > 4096:
            self.fail("Cell exceeds 4096 scalars")
        kept, mapped = [], []
        code = any(f["tag"] == "code" for f in self.stack)
        for i, c in enumerate(value):
            if not code and c in " \t\r\n\f":
                if self.space:
                    continue
                c = " "
            self.space = c.isspace()
            kept.append(c)
            mapped.append(spans[i])
        if not kept:
            return
        value = "".join(kept)
        node = self.node("text", mapped[0].start, mapped[-1].end, raw=value)
        occurrences, duplicates = [], {}
        for local, text in clusters(value):
            span = SourceSpan(mapped[local.start].start, mapped[local.end - 1].end)
            index = duplicates.get(span, 0)
            duplicates[span] = index + 1
            identity = self.session.occurrence_id(span, role=f"html-text:{index}", text=text)
            occurrences.append(Occurrence(identity, node.node_id, span, text))
        self.append(replace(node, occurrences=tuple(occurrences)))

    def handle_data(self, data):
        start = self.local_position()
        self.text(data, self.ranges[start : start + len(data)])

    def entity(self, name):
        start = self.position()
        raw = "&" + name
        local = self.local_position()
        if self.raw[local + len(raw) : local + len(raw) + 1] == ";":
            raw += ";"
        value = html.unescape(raw)
        self.text(value, [SourceSpan(start, self.token_end(len(raw)))] * len(value))

    def handle_entityref(self, name):
        self.entity(name)

    def handle_charref(self, name):
        self.entity("#" + name)

    def handle_comment(self, data):
        self.fail("Comments are outside the supported table subset")

    def handle_decl(self, decl):
        self.fail("Document declarations are not table content")

    def handle_pi(self, data):
        self.fail("Processing instructions are not supported")


def _trim_cell_end(node):
    if node.kind == "code_inline":
        return node
    if node.children:
        children = list(node.children)
        children[-1] = _trim_cell_end(children[-1])
        return replace(node, children=tuple(children))
    occurrences = list(node.occurrences)
    while occurrences and occurrences[-1].text == " ":
        occurrences.pop()
    return replace(node, occurrences=tuple(occurrences))


def parse_html_tables(session: SourceSession, span: SourceSpan, mapped=None):
    from .math_adapter import html_math

    parser = _TableHTML(session, span, mapped)
    parser.feed(parser.raw)
    parser.close()
    if parser.stack or not parser.roots or any(n.kind != "table" for n in parser.roots):
        raise TableSourceError("Expected complete closed HTML tables", span)
    roots = html_math(tuple(parser.roots), session, parser.diagnostics)
    from .break_commands import html_break_commands

    roots = html_break_commands(roots, session, parser.diagnostics)
    for node in roots:
        table_model(node)
    return roots, tuple(parser.diagnostics)


def expand_html_tables(nodes, session, diagnostics, html_sources=None):
    result = []
    for node in nodes:
        if node.kind == "html_block" and re.match(
            r"\s*<table(?:\s|>)", node.raw_content, re.IGNORECASE
        ):
            try:
                tables, issues = parse_html_tables(
                    session, node.span, (html_sources or {}).get(node.node_id)
                )
                diagnostics[:] = [
                    d
                    for d in diagnostics
                    if not (d.code == "layout-pending" and d.span == node.span)
                ]
                result.extend(tables)
                diagnostics.extend(issues)
                continue
            except TableSourceError as error:
                diagnostics.append(Diagnostic("html-table-invalid", str(error), error.span))
        if node.children:
            node = replace(
                node, children=expand_html_tables(node.children, session, diagnostics, html_sources)
            )
        result.append(node)
    return tuple(result)
