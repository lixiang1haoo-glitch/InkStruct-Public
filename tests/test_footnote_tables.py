"""Tables admit atomic row groups with note heads and preserve repeated headers."""

from dataclasses import replace

import pytest
from test_footnote_pages import assert_bands, assert_coverage

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot


def render(source, **kw):
    doc = parse_markdown(source)
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=kw.pop("page", PageProfile(95, 90, 5)),
        flow=kw.pop("flow", replace(FlowStyle(), table=TableStyle(width_mm=80))),
        **kw,
    )
    return doc, result


def assert_anchors(doc, result):
    definitions = {n.node_id: n for n in doc.nodes if n.kind == "footnote_definition"}
    first = {}
    for root in doc.nodes:
        for n in root.walk():
            if n.kind == "footnote_reference":
                first.setdefault(dict(n.attributes)["definition_id"], n)
    for key, n in first.items():
        ref = next(f for f in result.fragments if f.occurrence_id == n.occurrences[0].occurrence_id)
        definition = definitions[key]
        head = next(
            f
            for f in result.fragments
            if f.occurrence_id == definition.occurrences[0].occurrence_id
        )
        assert ref.page_index == head.page_index


def test_table_body_references_and_repeated_header_emit_definition_once():
    source = (
        "|1[^h]|2|\n|---|---|\n"
        + "\n".join(f"|{i}|3[^a{i}]|" for i in range(12))
        + "\n\n[^h]: 45\n\n"
        + "\n\n".join(f"[^a{i}]: " + "67 89 " * 3 for i in range(12))
    )
    doc, result = render(source)
    assert result.exportable, result.diagnostics
    assert len(result.pages) > 2
    assert any(f.repeated for f in result.fragments)
    assert_anchors(doc, result)
    assert_coverage(doc, result)
    assert_bands(result)
    plan_from_snapshot(result)


def test_table_without_references_respects_earlier_notes():
    source = "1[^a]\n\n|2|3|\n|---|---|\n" + "|4|5|\n" * 15 + "\n[^a]: " + "67 89 " * 50
    doc, result = render(source)
    assert result.exportable, result.diagnostics
    assert len(result.pages) > 2
    assert_anchors(doc, result)
    assert_coverage(doc, result)
    assert_bands(result)


def test_rowspan_group_stays_whole_while_existing_note_continues():
    source = (
        '1[^a]\n\n<table><tr><th>2</th><th>3</th></tr><tr><td rowspan="2">4</td><td>5</td></tr><tr><td>6</td></tr><tr><td>7</td><td>8</td></tr></table>\n\n[^a]: '
        + "12 34 " * 30
    )
    doc, result = render(source, page=PageProfile(95, 65, 5))
    assert result.exportable, result.diagnostics
    table = next(n for n in doc.nodes if n.kind == "table")
    groupids = {o.occurrence_id for n in table.walk() for o in n.occurrences if o.text in "456"}
    assert len({f.page_index for f in result.fragments if f.occurrence_id in groupids}) == 1
    assert_coverage(doc, result)
    assert_bands(result)


def test_header_only_table_reference_is_reserved():
    doc, result = render("|1[^a]|2|\n|---|---|\n\n[^a]: 34")
    assert result.exportable, result.diagnostics
    assert_anchors(doc, result)
    assert_coverage(doc, result)
    assert_bands(result)


def test_heading_keeps_first_table_group_with_its_note():
    doc, result = render(
        "1[^a]\n\n2\n\n3\n\n## 4\n\n|5[^b]|6|\n|---|---|\n|7|8|\n\n[^a]: "
        + "12 34 " * 10
        + "\n\n[^b]: 56"
    )
    assert result.exportable, result.diagnostics
    heading = next(f for f in result.fragments if f.text == "4" and not f.container_id)
    header = next(f for f in result.fragments if f.text == "5")
    assert heading.page_index == header.page_index
    assert_coverage(doc, result)
    assert_bands(result)


def test_oversized_group_or_impossible_note_head_makes_progress():
    doc, result = render("|1[^a]|2|\n|---|---|\n|3|4|\n\n[^a]: 56", page=PageProfile(95, 25, 5))
    assert not result.exportable
    assert len(result.pages) < 4
    assert any(
        d.code in {"footnote-anchor-overflow", "table-group-height-overflow"}
        for d in result.diagnostics
    )
    assert_coverage(doc, result)


@pytest.mark.parametrize("repeat", [False, True])
def test_prior_reference_then_table_header_reference_does_not_restart_note(repeat):
    source = "1[^a]\n\n|2[^a]|3|\n|---|---|\n" + "|4|5|\n" * 20 + "\n[^a]: 67"
    doc, result = render(
        source, flow=replace(FlowStyle(), table=TableStyle(width_mm=80, repeat_header=repeat))
    )
    assert result.exportable, result.diagnostics
    definition = doc.nodes[-1]
    labels = [
        f for f in result.fragments if f.occurrence_id == definition.occurrences[0].occurrence_id
    ]
    assert len(labels) == 1
    assert_coverage(doc, result)
    assert_bands(result)
