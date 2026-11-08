"""Bounded array column formats and source-located grid rules; never TeX execution."""

import re


def parse_array(p, start):
    p.space()
    position = "c"
    if p.text[p.pos : p.pos + 1] == "[":
        a = p.pos
        end = p.text.find("]", a + 1)
        if end < 0 or p.text[a + 1 : end].strip() not in {"t", "b", "c"}:
            p.fail(
                "math-array-option",
                "Array accepts only [t], [b], or [c]",
                a,
                end + 1 if end >= 0 else len(p.text),
            )
        position = p.text[a + 1 : end].strip()
        p.pos = end + 1
    p.space()
    spec_start = p.pos + 1
    spec = p.environment_name()
    columns, rules, bars = [], [], {}
    for i, c in enumerate(spec):
        if c.isspace():
            continue
        if c in "lcr":
            columns.append(c)
        elif c == "|":
            boundary = len(columns)
            bars[boundary] = bars.get(boundary, 0) + 1
            if bars[boundary] > 2:
                p.fail("math-array-format", "At most two rules per column boundary", spec_start + i)
            rules.append(
                p.node(
                    "ArrayRule",
                    spec_start + i,
                    spec_start + i + 1,
                    attributes=(("axis", "vertical"), ("boundary", str(boundary))),
                )
            )
        else:
            p.fail(
                "math-array-format",
                "Only l, c, r and | are supported in array column formats",
                spec_start + i,
            )
    if not 1 <= len(columns) <= 8:
        p.fail("math-array-budget", "Array requires 1-8 columns", start, p.pos)
    children = list(rules)
    rows = []
    while True:
        p.space()
        boundary_rules = []
        while p.at_command("hline") or p.at_command("cline"):
            name, a = p.command()
            first, last = 0, len(columns)
            if name == "cline":
                value = p.environment_name()
                m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value)
                if not m:
                    p.fail(
                        "math-array-rule",
                        "cline requires a column interval such as {1-2}",
                        a,
                        p.pos,
                    )
                first, last = int(m[1]) - 1, int(m[2])
                if not 0 <= first < last <= len(columns):
                    p.fail(
                        "math-array-rule",
                        "cline interval is outside the declared columns",
                        a,
                        p.pos,
                    )
            if boundary_rules:
                if (
                    (
                        name == "hline"
                        and all(dict(n.attributes)["style"] == "hline" for n in boundary_rules)
                        and len(boundary_rules) == 1
                    )
                    or name == "cline"
                    and all(
                        dict(n.attributes)["style"] == "cline"
                        and (
                            last <= int(dict(n.attributes)["first"])
                            or first >= int(dict(n.attributes)["last"])
                        )
                        for n in boundary_rules
                    )
                ):
                    pass
                else:
                    p.fail(
                        "math-array-rule-overlap",
                        "Use at most two hlines, or non-overlapping clines, at a boundary",
                        a,
                        p.pos,
                    )
            node = p.node(
                "ArrayRule",
                a,
                p.pos,
                attributes=(
                    ("axis", "horizontal"),
                    ("boundary", str(len(rows))),
                    ("first", str(first)),
                    ("last", str(last)),
                    ("style", name),
                ),
            )
            boundary_rules.append(node)
            p.space()
        children.extend(boundary_rules)
        if p.at_command("end"):
            p.command()
            if p.environment_name() != "array":
                p.fail("math-environment", "Mismatched array environment end", start, p.pos)
            break
        row_start, cells = p.pos, []
        while True:
            cells.append(
                p.row(
                    lambda: (
                        p.text[p.pos : p.pos + 1] == "&"
                        or p.at_row_break()
                        or p.at_command("end")
                    )
                )
            )
            if len(cells) > len(columns):
                p.fail(
                    "math-array-columns",
                    "Too many cells for the array column format",
                    row_start,
                    p.pos,
                )
            if p.text[p.pos : p.pos + 1] == "&":
                p.pos += 1
                continue
            break
        cells.extend(p.node("Row", p.pos, p.pos) for _ in range(len(columns) - len(cells)))
        row = p.node("ArrayRow", row_start, p.pos, cells)
        rows.append(row)
        children.append(row)
        if len(rows) > 32 or len(rows) * len(columns) > 256:
            p.fail("math-array-budget", "Array exceeds 32 rows or 256 cells", start, p.pos)
        if p.at_row_break():
            p.consume_row_break()
            p.space()
            if p.text[p.pos : p.pos + 1] in {"[", "*"}:
                p.fail(
                    "math-array-option", "Per-row spacing and starred breaks are unsupported", p.pos
                )
            continue
        if not p.at_command("end"):
            p.fail("math-environment", "Unclosed array environment", start, p.pos)
    if not rows:
        p.fail("math-array-empty", "Array needs at least one row", start, p.pos)
    return p.node(
        "Array",
        start,
        p.pos,
        children,
        attributes=(("columns", "".join(columns)), ("position", position)),
    )
