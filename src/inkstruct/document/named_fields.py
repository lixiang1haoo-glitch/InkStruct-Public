"""Explicit named-field blocks; offsets remain in the single authoritative source."""

import re

from .flow_template import IDENTIFIER
from .schema import SourceSpan
from .template_diagnostics import TemplateDiagnostic, TemplateTarget


def install_fields(md, cancelled=None):
    from .cancellation import check_cancel

    def rule(state, start, end, silent):
        text = state.src[state.bMarks[start] + state.tShift[start] : state.eMarks[start]]
        if state.sCount[start] >= 4 or not (text.startswith(":::field") or text.strip() == ":::"):
            return False
        if silent:
            return True
        match = re.fullmatch(r":::field\s+([A-Za-z][A-Za-z0-9_-]{0,63})\s*", text)
        error = None
        close = None
        if not match:
            error = "字段标记无效；使用 :::field 标识 和独立一行的 :::。"
        elif state.env.get("_inside_named_field"):
            error = "字段块不允许嵌套。"
        else:
            fence = None
            for line in range(start + 1, end):
                check_cancel(cancelled)
                value = state.src[state.bMarks[line] : state.eMarks[line]].strip()
                marker = re.match(r"(`{3,}|~{3,})", value)
                if marker:
                    m = marker[1]
                    if fence is None:
                        fence = (m[0], len(m))
                    elif m[0] == fence[0] and len(m) >= fence[1] and not value[len(m) :].strip():
                        fence = None
                    continue
                if fence is None and value == ":::":
                    close = line
                    break
            if close is None:
                error = "字段块缺少结束标记 :::；后续内容仍按正文解析，请补全协议。"
        if error:
            token = state.push("named_field_error", "", 0)
            token.map = [start, start + 1]
            token.meta["field_error"] = error
            state.line = start + 1
            return True
        opening = state.push("named_field_open", "", 1)
        opening.map = [start, close + 1]
        opening.attrSet("field_id", match[1])
        old_max = state.lineMax
        state.lineMax = close
        state.env["_inside_named_field"] = True
        try:
            state.md.block.tokenize(state, start + 1, close)
        finally:
            state.lineMax = old_max
            state.env.pop("_inside_named_field", None)
        closing = state.push("named_field_close", "", -1)
        closing.map = [close, close + 1]
        state.line = close + 1
        return True

    md.block.ruler.before(
        "fence", "named_fields", rule, {"alt": ["paragraph", "reference", "blockquote"]}
    )


def split_fields(document, template):
    """Partition an already parsed document, without reparsing or copying source text."""
    from dataclasses import replace

    definitions = {}
    diagnostics = []
    body = []
    declared = {f.field_id: f for f in template.fields}

    def issue(code, message, span, key):
        return TemplateDiagnostic(code, message, span, target=TemplateTarget(key, key, "named"))

    for node in document.nodes:
        if node.kind != "named_field":
            if node.kind != "named_field_error":
                body.append(node)
            continue
        key = dict(node.attributes)["field_id"]
        if key in definitions:
            diagnostics.append(
                issue("template-field-duplicate", f"字段 {key} 重复定义。", node.span, key)
            )
        else:
            definitions[key] = node
        if key not in declared:
            diagnostics.append(
                issue(
                    "template-field-unknown",
                    f"字段 {key} 未在模板声明；请修正标识或声明，不能丢弃。",
                    node.span,
                    key,
                )
            )
        if any(n.kind.startswith("footnote_") for n in node.walk()):
            diagnostics.append(
                issue(
                    "template-field-footnote",
                    "字段内不能使用脚注；请将脚注移到正文。",
                    node.span,
                    key,
                )
            )
    for key, f in declared.items():
        node = definitions.get(key)
        text = document.source[node.span.start : node.span.end] if node else ""
        lines = text.splitlines()[1:-1]
        content = "\n".join(lines).strip()
        if f.required and not content:
            diagnostics.append(
                issue(
                    "template-field-required",
                    f"必填字段 {f.label} ({key}) 缺失或为空。",
                    node.span if node else SourceSpan(0, 0),
                    key,
                )
            )
        if (
            content
            and f.value_type == "number"
            and not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", content)
        ):
            diagnostics.append(
                issue("template-field-type", f"字段 {key} 必须为数值。", node.span, key)
            )
        if content and f.value_type == "date":
            import datetime

            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',content):
                    raise ValueError('Date must use YYYY-MM-DD')
                datetime.date.fromisoformat(content)
            except ValueError:
                diagnostics.append(
                    issue(
                        "template-field-type",
                        f"字段 {key} 必须为 YYYY-MM-DD 日期。",
                        node.span,
                        key,
                    )
                )
    return replace(document, nodes=tuple(body)), definitions, tuple(diagnostics)


def field_example(field_id):
    if not IDENTIFIER.fullmatch(field_id):
        raise ValueError("Invalid field identifier")
    return f":::field {field_id}\n\n:::\n"
