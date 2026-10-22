"""Fixed-region references share global note definitions and reserve first-page heads."""

from collections import Counter
from dataclasses import replace

import pytest
from test_footnote_pages import assert_bands, assert_coverage
from test_template_fields import setup

from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import StyleProfile
from inkstruct.document.table_style import TableStyle
from inkstruct.document.template import Region, TemplateBinding
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page


def layout(doc, r, flow):
    return layout_markdown(doc, r, flow=flow)


def body_bands(s, flow):
    pages = tuple(
        replace(
            p,
            fragments=tuple(
                f for f in p.fragments if not (f.container_id or "").startswith("template-field:")
            ),
            paint_ops=tuple(
                op for op in p.paint_ops if not op.execution_domain.startswith("template-field:")
            ),
        )
        for p in s.pages
    )
    assert_bands(replace(s, pages=pages), flow.template.bounds)


@pytest.mark.parametrize("repeat", [False, True])
@pytest.mark.parametrize("mode", ["blank", "preprinted"])
def test_fixed_field_reference_starts_note_on_first_page_only(repeat, mode):
    _, doc, r, flow = setup("1[^a]\n\n" + "2\n\n" * 12 + "[^a]: 34", repeat=repeat, mode=mode)
    s = layout(doc, r, flow)
    assert s.plotter_exportable, s.diagnostics
    assert len(s.pages) > 1
    definition = doc.nodes[-1]
    number = next(f for f in s.fragments if f.node_id == definition.node_id)
    assert number.page_index == 0 and not number.repeated
    ref = next(n for n in doc.nodes[0].walk() if n.kind == "footnote_reference")
    refs = [f for f in s.fragments if f.occurrence_id == ref.occurrences[0].occurrence_id]
    assert len(refs) == (len(s.pages) if repeat else 1)
    assert all(f.container_id == "template-field:header" for f in refs)
    assert not refs[0].repeated and all(f.repeated for f in refs[1:])
    assert sum(f.node_id == definition.node_id for f in s.fragments) == 1
    assert_coverage(doc, s)
    body_bands(s, flow)
    for page in plan_from_snapshot(s).pages:
        route = route_page(page, optimize=True)
        assert route.after_mm <= route.before_mm
        domains = [stroke.execution_domain for stroke in route.page.strokes]
        assert (
            domains.index("template-field:header") < domains.index("page-footnotes")
            if "page-footnotes" in domains and repeat
            else True
        )


def test_field_only_document_can_use_note_only_continuation_pages():
    _, doc, r, flow = setup("1[^a]\n\n[^a]: " + "23 45 " * 100, repeat=True)
    s = layout(doc, r, flow)
    assert s.exportable, s.diagnostics
    assert 2 < len(s.pages) < 100
    assert all(any(f.container_id == "template-field:header" for f in p.fragments) for p in s.pages)
    assert all(
        any((f.container_id or "").startswith("footnote:") for f in p.fragments) for p in s.pages
    )
    assert_coverage(doc, s)
    body_bands(s, flow)


def test_field_and_body_references_share_one_definition_and_selection_records():
    _, doc, r, flow = setup(
        "1[^a]\n\n2[^a]\n\n" + "3\n\n" * 12 + "[^a]: 45", repeat=True, scale=0.7
    )
    s = layout(doc, r, flow)
    assert s.exportable, s.diagnostics
    note = doc.nodes[-1]
    assert len([f for f in s.fragments if f.node_id == note.node_id]) == 1
    first_choices = r.selection_records()
    again = layout(doc, r, flow)
    assert again == s and r.selection_records() == first_choices
    assert_coverage(doc, s)
    body_bands(s, flow)


def test_source_numbering_and_page_note_order_survive_moved_later_field():
    _, doc, r, flow = setup("1[^a]\n\n2[^b]\n\n[^a]: 34\n\n[^b]: 56")
    flow = replace(
        flow,
        template_bindings=(replace(flow.template_bindings[0], node_ids=(doc.nodes[1].node_id,)),),
    )
    s = layout(doc, r, flow)
    assert s.exportable, s.diagnostics
    definitions = [n for n in doc.nodes if n.kind == "footnote_definition"]
    ids = {n.node_id for n in definitions}
    labels = [f for f in s.pages[0].fragments if f.node_id in ids]
    assert [f.text for f in labels] == ["1", "2"]
    assert_coverage(doc, s)
    body_bands(s, flow)


def test_two_distinct_fields_share_definition_without_double_primary_instances():
    _, doc, r, flow = setup("1[^a]\n\n2[^a]\n\n3\n\n[^a]: 45")
    t = flow.template
    face = replace(t.first, reserved=(*t.first.reserved, Region("second", 10, 42, 60, 8)))
    flow = replace(
        flow,
        template=replace(t, first=face),
        template_bindings=(
            *flow.template_bindings,
            TemplateBinding("second", (doc.nodes[1].node_id,), scale=0.7),
        ),
    )
    s = layout(doc, r, flow)
    assert s.exportable, s.diagnostics
    assert len([f for f in s.fragments if f.node_id == doc.nodes[-1].node_id]) == 1
    assert_coverage(doc, s)
    body_bands(s, flow)


def test_definition_binding_is_rejected_and_kept_in_the_page_bottom_flow():
    _, doc, r, flow = setup("1[^a]\n\n[^a]: 23")
    definition = doc.nodes[-1]
    flow = replace(
        flow,
        template_bindings=(replace(flow.template_bindings[0], node_ids=(definition.node_id,)),),
    )
    s = layout(doc, r, flow)
    assert not s.exportable
    assert "template-footnote-definition-binding" in {d.code for d in s.diagnostics}
    assert any(
        f.node_id == definition.node_id and f.container_id.startswith("footnote:")
        for f in s.fragments
    )
    assert_coverage(doc, s)


def test_impossible_fixed_head_never_moves_silently_to_a_later_page():
    _, doc, r, flow = setup("1[^a]\n\n2\n\n[^a]: |3|\n    |---|\n    |4|", repeat=True)
    flow = replace(flow, table=TableStyle(width_mm=50, min_row_height_mm=60))
    s = layout(doc, r, flow)
    assert not s.exportable and len(s.pages) < 5
    assert "footnote-fixed-anchor-overflow" in {d.code for d in s.diagnostics}
    assert_coverage(doc, s)


def test_large_body_head_can_follow_a_first_page_with_only_field_and_note():
    _, doc, r, flow = setup("1[^a]\n\n# 23\n\n[^a]: 45")
    flow = replace(flow, heading_scales=(4, 1.4, 1.2, 1.1, 1, 1))
    s = layout(doc, r, flow)
    assert s.exportable, s.diagnostics
    assert len(s.pages) == 2
    definition = doc.nodes[-1]
    assert next(f for f in s.fragments if f.node_id == definition.node_id).page_index == 0
    assert {
        f.page_index
        for f in s.fragments
        if f.node_id == doc.nodes[1].children[0].children[0].node_id
    } == {1}
    assert_coverage(doc, s)
    body_bands(s, flow)


def test_missing_definition_in_field_remains_an_export_error():
    _, doc, r, flow = setup("1[^a]\n\n2")
    s = layout(doc, r, flow)
    assert not s.exportable
    assert "footnote-missing-definition" in {d.code for d in s.diagnostics}
    assert_coverage(doc, s)


def test_fields_and_structural_notes_save_and_reopen_identically(tmp_path):
    session, doc, r, flow = setup("1[^a]\n\n2\n\n[^a]: - [x] 34\n    - [ ] 56", repeat=True)
    s = layout(doc, r, flow)
    assert s.plotter_exportable, s.diagnostics
    path = tmp_path / "fixed-note.inkdoc"
    save_package(path, session, r, s.page_profile, StyleProfile(), flow=flow, optimize=True)
    p = load_package(path)
    after = layout(parse_markdown(p.session), p.resolver, p.flow)
    assert s == after
    assert Counter(f.occurrence_id for f in s.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
