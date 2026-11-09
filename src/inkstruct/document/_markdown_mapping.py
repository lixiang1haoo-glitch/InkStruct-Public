"""Version-pinned markdown-it adapter preserving provenance during tokenization.

The block indentation and inline rule contracts follow markdown-it-py 4.0.0
(MIT, https://github.com/executablebooks/markdown-it-py). Never monkeypatch global
parser classes: every document gets its own instrumented parser instance.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.parser_block import ParserBlock
from markdown_it.parser_inline import ParserInline
from markdown_it.rules_block.state_block import StateBlock
from markdown_it.rules_block.table import escapedSplit, getLine, table
from markdown_it.rules_inline.state_inline import StateInline

from ._math_mapping import block_math, inline_math
from .break_commands import block_flow_break, inline_break
from .cancellation import check_cancel
from .footnotes import footnote_definition, footnote_reference
from .schema import SourceSpan
from .source_map import MappedText
from .tasks import task_list_core


class LocatedString(str):
    def __new__(cls, text, ranges):
        value = super().__new__(cls, text)
        value.ranges = tuple(ranges)
        if len(value) != len(value.ranges):
            raise ValueError("Parser source mapping length mismatch")
        return value

    def __getitem__(self, key):
        value = super().__getitem__(key)
        ranges = self.ranges[key]
        return LocatedString(value, ranges if isinstance(key, slice) else (ranges,))

    def __add__(self, other):
        if not other:
            return self
        if not self:
            return other
        if isinstance(other, LocatedString):
            return LocatedString(str(self) + str(other), self.ranges + other.ranges)
        return str(self) + other

    def __radd__(self, other):
        if not other:
            return self
        return other + str(self)

    def strip(self, chars=None):
        return self.lstrip(chars).rstrip(chars)

    def lstrip(self, chars=None):
        trimmed = str(self).lstrip(chars)
        return self[len(self) - len(trimmed) :]

    def rstrip(self, chars=None):
        return self[: len(str(self).rstrip(chars))]

    def replace(self, old, new, count=-1):
        if not old:
            raise ValueError("Unmapped insertion is not allowed in parser strings")
        result, spans = [], []
        pos, replaced = 0, 0
        while pos < len(self):
            if self.startswith(old, pos) and (count < 0 or replaced < count):
                result.append(new)
                spans.extend(
                    [SourceSpan(self.ranges[pos].start, self.ranges[pos + len(old) - 1].end)]
                    * len(new)
                )
                pos += len(old)
                replaced += 1
            else:
                result.append(str(self)[pos])
                spans.append(self.ranges[pos])
                pos += 1
        return LocatedString("".join(result), spans)


class LocatedBlockState(StateBlock):
    def push(self, ttype, tag, nesting):
        from .limits import DocumentLimitError, created_token

        created_token()
        if len(self.tokens) >= 50_000:
            raise DocumentLimitError("block_tokens", len(self.tokens) + 1, 50_000)
        return super().push(ttype, tag, nesting)

    def getLines(self, begin, end, indent, keepLastLF):
        parts, spans = [], []
        for line in range(begin, end):
            first = self.bMarks[line]
            origin = first
            last = min(len(self.src), self.eMarks[line] + int(line + 1 < end or keepLastLF))
            consumed = 0
            while first < last and consumed < indent:
                char = self.src[first]
                if char == "\t":
                    consumed += 4 - (consumed + self.bsCount[line]) % 4
                elif char == " " or first - origin < self.tShift[line]:
                    consumed += 1
                else:
                    break
                first += 1
            if consumed > indent:
                parts.append(" " * (consumed - indent))
                spans.extend([self.src.ranges[first - 1]] * (consumed - indent))
            parts.append(str(self.src)[first:last])
            spans.extend(self.src.ranges[first:last])
        result = LocatedString("".join(parts), spans)
        if result != super().getLines(begin, end, indent, keepLastLF):
            raise ValueError("Block mapping differs from pinned parser semantics")
        return result


def located_code(state, startLine, endLine, silent):
    """Pinned indented-code rule without an invented unmapped terminal LF."""
    if not state.is_code_block(startLine):
        return False
    last = nextLine = startLine + 1
    while nextLine < endLine:
        if state.isEmpty(nextLine):
            nextLine += 1
            continue
        if state.is_code_block(nextLine):
            nextLine += 1
            last = nextLine
            continue
        break
    state.line = last
    token = state.push("code_block", "code", 0)
    token.content = state.getLines(startLine, last, 4 + state.blkIndent, True)
    token.map = [startLine, last]
    return True


class LocatedBlockParser(ParserBlock):
    def __init__(self):
        super().__init__()
        self.ruler.at("table", bounded_table)
        self.ruler.at("code", located_code)
        self.ruler.before(
            "fence", "flow_break", block_flow_break,
            {"alt": ["paragraph", "reference", "blockquote", "list"]},
        )
        self.ruler.before(
            "reference",
            "footnote_definition",
            footnote_definition,
            {"alt": ["paragraph", "reference", "blockquote", "list"]},
        )
        self.ruler.before(
            "fence",
            "math_block",
            block_math,
            {"alt": ["paragraph", "reference", "blockquote", "list"]},
        )

    def tokenize(self, state, startLine, endLine):
        if state.level >= state.md.options["maxNesting"]:
            from .limits import DocumentLimitError

            raise DocumentLimitError(
                "parser_depth", state.level + 1, state.md.options["maxNesting"]
            )
        return super().tokenize(state, startLine, endLine)

    def parse(self, src, md, env, outTokens):
        if src:
            state = LocatedBlockState(src, md, env, outTokens)
            self.tokenize(state, state.line, state.lineMax)
            return state.tokens
        return outTokens


def bounded_table(state, start, end, silent):
    if not table(state, start, end, True):
        return False

    def cells(line):
        parts = escapedSplit(getLine(state, line).strip())
        if parts and not parts[0]:
            parts.pop(0)
        if parts and not parts[-1]:
            parts.pop()
        return parts

    columns = len(cells(start))
    if columns > 50:
        raise ValueError("Markdown table exceeds 50 columns")
    if silent:
        return True
    before = len(state.tokens)
    table(state, start, end, False)
    if state.line - start - 1 > 100:
        raise ValueError("Markdown table exceeds 100 rows")
    empty_spans, column = [], 0
    for token in state.tokens[before:]:
        if token.type == "tr_open" and len(cells(token.map[0])) > columns:
            raise ValueError("Markdown table has extra cells that would be discarded")
        if token.type == "tr_open":
            line = getLine(state, token.map[0]).strip()
            separators = [
                i for i, ch in enumerate(line) if ch == "|" and (i == 0 or line[i - 1] != "\\")
            ]
            bounds = list(zip([0] + [i + 1 for i in separators], separators + [len(line)]))
            if bounds and bounds[0] == (0, 0):
                bounds.pop(0)
            if bounds and bounds[-1] == (len(line), len(line)):
                bounds.pop()
            empty_spans = []
            for a, b in bounds:
                index = min(a, len(line) - 1)
                empty_spans.append(
                    SourceSpan(line.ranges[index].start, line.ranges[b - 1 if b > a else index].end)
                )
            column = 0
        if token.type == "inline":
            if not token.content:
                # An autocompleted missing cell is explicitly anchored to the end
                # of its row, with its column role included in the node identity.
                token.meta["source_span"] = empty_spans[min(column, len(empty_spans) - 1)]
                token.meta["empty_column"] = column
            column += 1
        if token.type == "inline" and isinstance(token.content, LocatedString):
            ranges = list(token.content.ranges)
            for i, char in enumerate(token.content):
                # The table rule removes the escape slash before inline parsing.
                # Its source coordinates are still known from the original mapped line.
                if char == "|" and i < len(ranges):
                    current = ranges[i]
                    line = getLine(state, token.map[0])
                    for j, candidate in enumerate(line.ranges):
                        if candidate == current and j > 0 and line[j - 1] == "\\":
                            ranges[i] = SourceSpan(line.ranges[j - 1].start, current.end)
                            break
            token.content = LocatedString(token.content, ranges)
    return True


class LocatedInlineState(StateInline):
    def push(self, ttype, tag, nesting):
        from .limits import created_token

        created_token()
        return super().push(ttype, tag, nesting)

    def pushPending(self):
        from .limits import created_token

        created_token()
        token = super().pushPending()
        if isinstance(token.content, LocatedString):
            token.meta["display_ranges"] = token.content.ranges
        return token


def instrument_rule(rule):
    def located_rule(state, silent):
        start, count = state.pos, len(state.tokens)
        matched = rule(state, silent)
        if not matched or silent:
            return matched
        consumed = state.src[start : state.pos]
        if not consumed:
            return matched
        span = SourceSpan(consumed.ranges[0].start, consumed.ranges[-1].end)
        marker_offset = 0
        for token in state.tokens[count:]:
            if (
                rule.__module__.endswith((".emphasis", ".strikethrough"))
                and token.type == "text"
                and "display_ranges" not in token.meta
            ):
                token.content = consumed[marker_offset : marker_offset + len(token.content)]
                marker_offset += len(token.content)
            if token.type == "text_special":
                token.meta["display_ranges"] = (
                    consumed.ranges
                    if str(token.content) == str(consumed)
                    else (span,) * len(token.content)
                )
                token.meta["source_span"] = span
            elif isinstance(token.content, LocatedString) and token.content:
                token.meta.setdefault("display_ranges", token.content.ranges)
                token.meta.setdefault(
                    "source_span",
                    SourceSpan(token.content.ranges[0].start, token.content.ranges[-1].end),
                )
            elif token.content and "display_ranges" not in token.meta:
                # Entities/escapes may expand one source lexeme to several scalars.
                if token.type == "text_special":
                    token.meta["display_ranges"] = (span,) * len(token.content)
                elif token.type == "text" and consumed.startswith("<"):
                    # Keep autolink display literal; URL normalization is for the target only.
                    token.content = consumed[1:-1]
                    token.meta["display_ranges"] = token.content.ranges
            token.meta.setdefault("source_span", span)
            if token.type in {"code_inline", "image"}:
                token.meta["source_span"] = span
        return matched

    return located_rule


class LocatedInlineParser(ParserInline):
    def __init__(self):
        super().__init__()
        self.ruler.before("escape", "break_command", inline_break)
        self.ruler.before("escape", "math_inline", inline_math)
        self.ruler.before("link", "footnote_reference", footnote_reference)
        for entry in self.ruler.__rules__:
            self.ruler.at(entry.name, instrument_rule(entry.fn))
        # Joining plain/entity/delimiter tokens loses lexeme provenance. AST consumers
        # do not require that optimization or token.level after pair balancing.
        self.ruler2.disable("fragments_join")

    def parse(self, src, md, env, tokens):
        if not isinstance(src, LocatedString):
            if src:
                raise ValueError("Inline parser received content without source mapping")
            return tokens
        state = LocatedInlineState(src, md, env, tokens)
        self.tokenize(state)
        for rule in self.ruler2.getRules(""):
            rule(state)
        for index, token in enumerate(state.tokens):
            # Pair balancing represents ** by one live and one empty marker token.
            neighbour = index - 1 if token.type == "strong_open" else index + 1
            if token.type in {"strong_open", "strong_close"} and 0 <= neighbour < len(tokens):
                left = token.meta["source_span"]
                right = tokens[neighbour].meta["source_span"]
                token.meta["source_span"] = SourceSpan(
                    min(left.start, right.start), max(left.end, right.end)
                )
        return state.tokens


def make_parser(*, obsidian=False, cancelled=None) -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "typographer": False, "maxNesting": 32})
    md.block = LocatedBlockParser()
    md.inline = LocatedInlineParser()
    md.enable(["table", "strikethrough"])
    if obsidian:
        from .obsidian import callout_core, wiki_link

        md.inline.ruler.before("link", "wiki_link", instrument_rule(wiki_link))
        md.core.ruler.before("inline", "obsidian_callouts", callout_core)
    md.core.ruler.before("inline", "task_list_markers", task_list_core)
    md.core.ruler.disable(["normalize", "text_join"])
    if cancelled is not None:

        def cancellable(rule):
            def wrapped(*args, **kwargs):
                check_cancel(cancelled)
                return rule(*args, **kwargs)

            return wrapped

        # This parser is local to one request. Preserve alternative rule chains,
        # including paragraph terminators and recursive list/quote parsing.
        for ruler in (md.core.ruler, md.block.ruler, md.inline.ruler, md.inline.ruler2):
            for entry in ruler.__rules__:
                ruler.at(entry.name, cancellable(entry.fn), {"alt": entry.alt})
    return md


def located(view: MappedText) -> LocatedString:
    return LocatedString(view.text, view.ranges)
