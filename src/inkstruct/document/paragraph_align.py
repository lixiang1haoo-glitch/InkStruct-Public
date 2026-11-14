"""Explicit, document-body alignment ranges with precise source diagnostics."""

from dataclasses import replace
import re

from .cancellation import check_cancel
from .schema import Diagnostic, SourceSpan

START = r"\begin{paragraphalign}"
END = r"\end{paragraphalign}"
MODES = frozenset({"left", "center", "right", "justify"})


def block_paragraph_align(state, start, end, silent):
    if state.level or state.is_code_block(start):
        return False
    first = state.bMarks[start] + state.tShift[start]
    last = state.eMarks[start]
    raw = str(state.src[first:last]).rstrip()
    if raw.startswith(START):
        parameter = raw[len(START):].strip()
        match = re.fullmatch(r"\{([^{}]*)\}", parameter)
        if parameter and not match and not (parameter.startswith("{") and "}" not in parameter):
            return False
        mode = match[1] if match and match[1] in MODES else ""
        kind = "paragraph_align_start"
    elif raw == END:
        kind, mode = "paragraph_align_end", ""
    else:
        return False
    if not silent:
        token = state.push(kind, "", 0)
        token.attrSet("mode", mode)
        token.meta["source_span"] = SourceSpan(state.src.ranges[first].start,
                                               state.src.ranges[first + len(raw) - 1].end)
        token.map = [start, start + 1]
        state.line = start + 1
    return True


def resolve_paragraph_alignment(nodes, diagnostics, cancelled=None):
    """Annotate only complete, unnested ranges and omit their control lines."""
    body = []
    opening = None
    depth = 0
    first = 0
    mode = ""

    def report(node, code, text):
        diagnostics.append(Diagnostic(code, text, node.span, "warning"))

    for node in nodes:
        check_cancel(cancelled)
        if node.kind == "paragraph_align_start":
            selected = dict(node.attributes)["mode"]
            if not selected:
                report(node, "paragraph-align-option", "段落对齐参数应为 left、center、right 或 justify。")
            if depth:
                report(node, "paragraph-align-nested", "段落对齐区块不允许嵌套。")
                mode = ""
            else:
                opening, first, mode = node, len(body), selected
            depth += 1
        elif node.kind == "paragraph_align_end":
            if not depth:
                report(node, "paragraph-align-unexpected-end", "段落对齐结束符没有对应的起始指令。")
                continue
            depth -= 1
            if not depth and mode:
                for index in range(first, len(body)):
                    check_cancel(cancelled)
                    paragraph = body[index]
                    if paragraph.kind == "paragraph":
                        body[index] = replace(paragraph, attributes=(*paragraph.attributes, ("paragraph_align", mode)))
        else:
            body.append(node)
    if depth:
        report(opening, "paragraph-align-missing-end", "段落对齐区块缺少结束指令 \\end{paragraphalign}。")
    return tuple(body)
