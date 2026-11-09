"""Document-order equation numbering and source-bound labels/references.

Source remains authoritative. Only displayed equation environments opt into
numbering; ordinary dollar math never gains numbers implicitly.
"""

from dataclasses import replace

from ..math.schema import MathNode
from .schema import Diagnostic, Occurrence, SourceSpan


def resolve_equations(nodes, session, diagnostics):
    formulas = sorted(
        (n for root in nodes for n in root.walk() if n.math), key=lambda n: n.span.start
    )
    labels, rewritten = {}, {}
    counter = 0
    directives = {"Tag", "Label", "NoTag"}

    def issue(code, message, node):
        diagnostics.append(Diagnostic(code, message, node.span))

    def symbols(text, span, role):
        anchor = SourceSpan(span.start, min(len(session.source), span.start + 1))
        actual_span = span if span.end > span.start else anchor
        return tuple(
            MathNode(
                "Symbol",
                actual_span,
                value=c,
                occurrence_id=session.occurrence_id(
                    anchor if role == "equation-number" else actual_span, role=f"{role}:{i}", text=c
                ),
            )
            for i, c in enumerate(text)
        )

    def tag_for(cells, target, automatic):
        nonlocal counter
        found, cleaned = [], []
        for index, cell in enumerate(cells):
            children, reached = [], False
            for child in cell.children:
                if child.kind in directives:
                    if child.kind == "Tag" and index != len(cells) - 1:
                        issue(
                            "math-tag-position",
                            "Equation metadata must follow the final alignment cell",
                            child,
                        )
                    found.append(child)
                    reached = child.kind == "Tag" or reached
                else:
                    if reached and child.kind != "Space":
                        issue(
                            "math-tag-position",
                            "Visible content cannot follow equation metadata",
                            child,
                        )
                    children.append(child)
            cleaned.append(replace(cell, children=tuple(children)))
        tags = [n for n in found if n.kind == "Tag"]
        suppress = [n for n in found if n.kind == "NoTag"]
        keys = [n for n in found if n.kind == "Label"]
        if len(tags) > 1 or len(suppress) > 1 or (tags and suppress):
            issue(
                "math-tag-conflict",
                "Each equation row permits one tag or one suppression command",
                target,
            )
        tag = None
        if tags:
            tag = replace(tags[0], kind="EquationTag")
        elif automatic and not suppress:
            counter += 1
            text = MathNode(
                "Text", target.span, symbols(str(counter), target.span, "equation-number")
            )
            tag = MathNode(
                "EquationTag",
                target.span,
                (text,),
                attributes=(("parentheses", "true"), ("automatic", "true")),
            )
        for key in keys:
            if key.value in labels:
                issue(
                    "math-label-duplicate", "Equation label is already defined: " + key.value, key
                )
            elif tag is None:
                issue("math-label-unnumbered", "Label has no visible equation number or tag", key)
            else:
                labels[key.value] = "".join(n.value for n in tag.walk() if n.kind == "Symbol")
        return tuple(cleaned), tag

    for formula in formulas:
        root = formula.math
        outer = root.children[0] if len(root.children) == 1 else None
        content = root
        if formula.kind == "math_block":
            if outer and outer.kind == "Equation":
                cells, tag = tag_for(
                    outer.children, outer, dict(outer.attributes)["environment"] == "equation"
                )
                content = cells[0]
                if tag:
                    content = MathNode("Numbered", root.span, (content, tag))
            elif (
                outer
                and outer.kind == "Alignment"
                and dict(outer.attributes)["environment"]
                in {"align", "gather", "align*", "gather*"}
            ):
                rows = []
                automatic = dict(outer.attributes)["environment"] in {"align", "gather"}
                for row in outer.children:
                    cells, tag = tag_for(row.children, row, automatic)
                    rows.append(replace(row, children=(*cells, tag) if tag else cells))
                content = replace(outer, children=tuple(rows))
            else:
                cells, tag = tag_for((root,), root, False)
                content = cells[0]
                if tag:
                    content = MathNode("Numbered", root.span, (content, tag))
        # Only resolved outer environments may contain numbering metadata.
        for n in content.walk():
            if n.kind in directives or n.kind == "Equation":
                issue(
                    "math-numbering-context",
                    "Equation metadata/environments require a complete display equation or a numbered row",
                    n,
                )
            if n.kind == "Alignment" and dict(n.attributes)["environment"] in {
                "align",
                "gather",
                "align*",
                "gather*",
                "split",
            }:
                allowed = formula.kind == "math_block" and (
                    n is content
                    or (content.kind == "Row" and content.children == (n,))
                    or (
                        content.kind == "Numbered"
                        and content.children[0].kind == "Row"
                        and content.children[0].children == (n,)
                        and dict(n.attributes)["environment"] == "split"
                    )
                )
                if not allowed:
                    issue(
                        "math-alignment-context",
                        "This environment must occupy a complete display formula; use aligned/gathered for nested math",
                        n,
                    )
        rewritten[formula.node_id] = content

    def references(n):
        if n.kind == "Reference":
            text = labels.get(n.value)
            if text is None:
                issue("math-label-missing", "Unknown equation label: " + n.value, n)
                text = "??"
            content = MathNode("Text", n.span, symbols(text, n.span, "equation-reference"))
            n = replace(n, kind="EquationReference", children=(content,))
        else:
            n = replace(n, children=tuple(references(c) for c in n.children))
        if n.kind in {"EquationTag", "EquationReference"}:
            # These nodes are produced after math_adapter.bind. Anchor the
            # surrounding brackets independently from changing number digits.
            anchor = SourceSpan(n.span.start, n.span.start + 1)
            n = replace(
                n,
                occurrence_id=session.occurrence_id(
                    anchor, role="math-construction:" + n.kind, text=n.kind
                ),
            )
        return n

    def rebuild(n):
        if n.math:
            root = references(rewritten[n.node_id])
            occurrences = tuple(
                Occurrence(m.occurrence_id, n.node_id, m.span, m.value)
                for m in root.walk()
                if m.kind == "Symbol"
            )
            return replace(n, math=root, occurrences=occurrences)
        return replace(n, children=tuple(rebuild(c) for c in n.children))

    return tuple(rebuild(n) for n in nodes)
