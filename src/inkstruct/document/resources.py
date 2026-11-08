"""Read-only glyph requirements, including configured captured math structures."""

from dataclasses import asdict

from ..assets.resolver import AssetResolver
from ..math.delimiters import node_delimiters
from ..math.sample_constructions import sample_occurrence
from .schema import SourceSpan
from .styles import FlowStyle


def construction_requirements(document, style):
    result = []
    for root in document.nodes:
        for formula in root.walk():
            if not formula.math:
                continue
            for node in formula.math.walk():
                specs = []
                if node.kind == "Fraction" and style.fraction_source == "sample":
                    specs.append(("fraction", "−", node.span))
                if (node.kind == "Accent" and node.value in {"bar", "overline", "underline"}
                        and style.fraction_source == "sample"):
                    specs.append(("accent-line", "−", node.span))
                if node.kind == "Radical" and style.radical_source == "sample":
                    specs.append(("radical", "√", node.span))
                if style.delimiter_source == "sample":
                    for side, char in zip(("left", "right"), node_delimiters(node), strict=True):
                        if char != ".":
                            encoded = dict(node.attributes).get(side + "_span")
                            span = (
                                SourceSpan(*(int(v) for v in encoded.split(":")))
                                if encoded
                                else node.span
                            )
                            specs.append(("delimiter-" + side, char, span))
                result.extend(
                    sample_occurrence(node, formula.node_id, role, char, span)
                    for role, char, span in specs
                )
    return tuple(result)


def inspect_resources(document, resolver, *, flow=None):
    """Scan a private resolver: checking gaps must not select assets in the project.

    Presence/selection is checked, not geometry, calibration or exportability.
    The layout remains the authority on whether a chosen specimen is usable.
    """
    if any(d.severity == "error" for d in document.diagnostics):
        raise ValueError("Resource inspection requires resolved syntax diagnostics")
    flow = flow or FlowStyle()
    scanned = AssetResolver(
        embedded=(g for pool in resolver.pools.values() for g in pool),
        seed=resolver.seed,
        selections=tuple(resolver.selections.values()),
    )
    excluded = {
        o.occurrence_id
        for root in document.nodes
        for node in root.walk()
        if node.kind in {"image", "task_checkbox"}
        for o in node.occurrences
    }
    ordinary = tuple(o for o in document.occurrences if o.occurrence_id not in excluded)
    structures = construction_requirements(document, flow.math)
    return {
        "kind": "markdown-resource-inspection",
        "gaps": scanned.gaps((*ordinary, *structures)),
        "resource_key": scanned.resource_key,
        "selections": scanned.selection_records(),
        "construction_requirements": [asdict(o) for o in structures],
        "math_sources": {
            key: getattr(flow.math, key)
            for key in ("fraction_source", "radical_source", "delimiter_source")
        },
        "dialect": flow.markdown_dialect,
        "diagnostics": [asdict(d) for d in document.diagnostics],
        "scope": "visible text, semantic math symbols and configured captured constructions; layout readiness is separate",
        "machine_export_ready": False,
    }
