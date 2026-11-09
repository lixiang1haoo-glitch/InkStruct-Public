"""Explicit table export views; source and source identities remain authoritative."""

import re
from dataclasses import asdict, replace

from .schema import Diagnostic
from .tables import table_model

NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")


def table_export_view(document, node, *, numbers_only=False):
    """Retain whole unsigned decimal cells, never strip a sign/unit/exponent.

    This is an export view, not a source edit. Omitted cells keep their grid and
    original spans; an accompanying manifest records each intentional omission.
    """
    if not any(n == node for root in document.nodes for n in root.walk()):
        raise ValueError("Selected table does not belong to this document revision")
    model = table_model(node)
    omitted = []
    if numbers_only:
        for cell in model.cells:
            parts = tuple(n for n in cell.node.walk() if not n.children)
            text = "".join(o.text for n in parts for o in n.occurrences)
            supported = not any(n.kind == "image" for n in cell.node.walk()) and all(
                n.kind in {"text", "text_special", "code_inline", "inline", "td", "th"}
                for n in parts
            )
            if (not supported) or (text.strip() and not NUMBER.fullmatch(text.strip())):
                omitted.append(
                    {
                        "node_id": cell.node.node_id,
                        "row": cell.row,
                        "column": cell.column,
                        "span": asdict(cell.node.span),
                        "source": document.source[cell.node.span.start : cell.node.span.end],
                        "display_text": text,
                    }
                )
    ids = {item["node_id"] for item in omitted}

    def filtered(n):
        if n.node_id in ids:
            return replace(n, children=(), occurrences=())
        return replace(n, children=tuple(filtered(c) for c in n.children))

    diagnostics = []
    for diagnostic in document.diagnostics:
        if not (node.span.start <= diagnostic.span.start < node.span.end):
            continue
        intentionally_omitted = any(
            item["span"]["start"] <= diagnostic.span.start
            and diagnostic.span.end <= item["span"]["end"]
            for item in omitted
        )
        if intentionally_omitted and (
            diagnostic.code.startswith("math-") or diagnostic.code == "layout-pending"
        ):
            continue
        diagnostics.append(diagnostic)
    for cell in model.cells:
        if cell.node.node_id in ids:
            diagnostics.append(
                Diagnostic(
                    "table-cell-omitted",
                    "Explicit numeric-only export leaves this cell blank",
                    cell.node.span,
                    "warning",
                )
            )
    mode = "unsigned-decimal-cells" if numbers_only else "all-table-content"
    selected = replace(
        document, nodes=(filtered(node),), diagnostics=tuple(diagnostics), export_scope=mode
    )
    report = {
        "schema_version": "inkstruct_table_export_scope_v1",
        "mode": mode,
        "table_node_id": node.node_id,
        "source_span": asdict(node.span),
        "source_content_key": document.content_key,
        "omitted_cells": omitted,
    }
    return selected, report
