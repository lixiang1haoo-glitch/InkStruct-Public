"""Real page allocations: anchor heads, bottom bands, source coverage and progress."""

import re
from collections import Counter
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page
from inkstruct.plotter.svg import page_svg


def render(source, **kw):
    doc = parse_markdown(source)
    result = layout_markdown(doc, AssetResolver(builtin_numbers=True), **kw)
    return doc, result


def assert_coverage(doc, snapshot):
    actual = Counter(f.occurrence_id for f in snapshot.fragments if not f.repeated)
    expected = Counter(o.occurrence_id for o in doc.occurrences)
    assert all(actual[key] == count for key, count in expected.items())


def assert_bands(snapshot, bounds=None):
    p = snapshot.page_profile
    bounds = bounds or (
        lambda index: (
            p.margin_mm,
            p.margin_mm,
            p.width_mm - p.margin_mm,
            p.height_mm - p.margin_mm,
        )
    )
    for page in snapshot.pages:
        left, top, right, bottom = bounds(page.index)
        foot = [
            f for f in page.fragments if f.container_id and f.container_id.startswith("footnote:")
        ]
        body = [f for f in page.fragments if f not in foot]
        separators = [
            op for op in page.paint_ops if op.occurrence_id.startswith("footnotes:separator:")
        ]
        if foot:
            assert len(separators) == 1
            sy = separators[0].points[0][1]
            if body:
                assert max(f.logical_bounds[3] for f in body) < sy
            assert sy < min(f.logical_bounds[1] for f in foot)
            assert max(f.logical_bounds[3] for f in foot) <= bottom + 1e-8
        for op in page.paint_ops:
            if op.execution_domain == "template-frame":
                continue
            r = op.width_mm / 2
            for x, y in op.points:
                assert left - 1e-8 <= x - r <= x + r <= right + 1e-8
                assert top - 1e-8 <= y - r <= y + r <= bottom + 1e-8


def test_first_reference_page_bottom_and_repetition_no_duplicate_definition():
    source = "12[^a]\n\n" + "34\n\n" * 18 + "56[^a]\n\n[^a]: 78"
    doc, result = render(source, page=PageProfile(80, 65, 5))
    assert result.plotter_exportable, result.diagnostics
    assert len(result.pages) > 2
    refs = [n for root in doc.nodes for n in root.walk() if n.kind == "footnote_reference"]
    definition = next(n for n in doc.nodes if n.kind == "footnote_definition")
    label = next(
        f for f in result.fragments if f.occurrence_id == definition.occurrences[0].occurrence_id
    )
    first = next(
        f for f in result.fragments if f.occurrence_id == refs[0].occurrences[0].occurrence_id
    )
    assert label.page_index == first.page_index == 0
    assert sum(f.occurrence_id == label.occurrence_id for f in result.fragments) == 1
    assert_coverage(doc, result)
    assert_bands(result)


def test_reference_near_page_end_moves_with_its_note_head():
    source = "1\n\n2\n\n3\n\n4[^a]\n\n[^a]: 56"
    doc, result = render(source, page=PageProfile(70, 55, 5))
    assert result.exportable, result.diagnostics
    ref = next(n for root in doc.nodes for n in root.walk() if n.kind == "footnote_reference")
    marker = next(
        f for f in result.fragments if f.occurrence_id == ref.occurrences[0].occurrence_id
    )
    note = next(f for f in result.fragments if f.container_id)
    assert marker.page_index == note.page_index == 1
    assert_coverage(doc, result)
    assert_bands(result)


def test_long_note_continues_after_body_and_advances_every_page():
    source = "1[^a]\n\n[^a]: " + "12 34 56 78 90 " * 100
    doc, result = render(source, page=PageProfile(70, 70, 5))
    assert result.exportable, result.diagnostics
    assert 1 < len(result.pages) < 100
    assert all(page.fragments for page in result.pages)
    assert_coverage(doc, result)
    assert_bands(result)
    ids = [o.occurrence_id for n in doc.nodes[-1].walk() for o in n.occurrences]
    actual = [f.occurrence_id for f in result.fragments if f.container_id and not f.repeated]
    assert actual == ids


def test_dense_new_references_and_pending_notes_do_not_starve_or_duplicate():
    source = (
        "\n\n".join(f"{i % 10}[^a{i}]" for i in range(15))
        + "\n\n"
        + "\n\n".join(f"[^a{i}]: " + "12 34 56 " * 12 for i in range(15))
    )
    doc, result = render(source, page=PageProfile(75, 85, 5))
    assert result.exportable, result.diagnostics
    assert len(result.pages) < 100
    assert_coverage(doc, result)
    assert_bands(result)
    for node in [n for root in doc.nodes for n in root.walk() if n.kind == "footnote_reference"]:
        definition = next(
            n for n in doc.nodes if n.node_id == dict(node.attributes)["definition_id"]
        )
        a = next(
            f for f in result.fragments if f.occurrence_id == node.occurrences[0].occurrence_id
        )
        b = next(
            f
            for f in result.fragments
            if f.occurrence_id == definition.occurrences[0].occurrence_id
        )
        assert a.page_index == b.page_index


def test_multiple_new_note_heads_on_one_line_with_long_tails():
    source = "1[^a] 2[^b]\n\n[^a]: " + "12 34 " * 50 + "\n\n[^b]: " + "56 78 " * 40
    doc, result = render(source, page=PageProfile(90, 80, 5))
    assert result.exportable, result.diagnostics
    definitions = [n for n in doc.nodes if n.kind == "footnote_definition"]
    assert all(
        next(
            f for f in result.fragments if f.occurrence_id == d.occurrences[0].occurrence_id
        ).page_index
        == 0
        for d in definitions
    )
    assert_coverage(doc, result)
    assert_bands(result)


@pytest.mark.parametrize(
    "source",
    [
        "1[^a]\n\n[^a]: 2\n\n    > **3**\n\n    - [x] 4\n    - [ ] 5",
        "> - 1[^a]\n> - 2\n\n[^a]: 34\n\n    56",
        "1[^a]\n\n[^a]: 2\n\n    ```\n    3 4\n    5 6\n    ```",
    ],
)
def test_shared_inline_and_nested_note_rendering(source):
    doc, result = render(source, page=PageProfile(90, 75, 5))
    assert result.exportable, result.diagnostics
    assert_coverage(doc, result)
    assert_bands(result)


def test_template_first_and_continuation_regions_include_note_only_pages():
    from inkstruct.document.template import PageTemplate, Region, TemplateFace

    template = PageTemplate(
        "notes",
        100,
        100,
        TemplateFace(Region("body", 10, 25, 80, 60)),
        TemplateFace(Region("body", 10, 10, 80, 75)),
        calibration="user-measured",
    )
    doc, result = render(
        "1[^a]\n\n[^a]: " + "12 34 " * 160, flow=replace(FlowStyle(), template=template)
    )
    assert result.exportable, result.diagnostics
    assert len(result.pages) > 2
    assert_coverage(doc, result)
    assert_bands(result, template.bounds)


def test_native_roundtrip_strict_svg_and_route_geometry(tmp_path):
    from inkstruct.document.package import load_package, save_package

    session = SourceSession("12[^a] 34[^b]\n\n[^a]: 56\n\n[^b]: 78")
    resolver = AssetResolver(builtin_numbers=True)
    result = layout_markdown(parse_markdown(session), resolver)
    path = tmp_path / "notes.inkdoc"
    save_package(path, session, resolver, PageProfile(), StyleProfile())
    loaded = load_package(path)
    assert result == layout_markdown(
        parse_markdown(loaded.session),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    for page in plan_from_snapshot(result).pages:
        routed = route_page(page, optimize=True).page
        canonical = lambda p: min(p, tuple(reversed(p)))
        assert Counter(canonical(s.points) for s in page.strokes) == Counter(
            canonical(s.points) for s in routed.strokes
        )
        assert all(
            n.tag == "{http://www.w3.org/2000/svg}path"
            and set(re.findall("[A-Za-z]", n.attrib["d"])) <= {"M", "L"}
            for n in ET.fromstring(page_svg(routed))
        )


@pytest.mark.parametrize(
    "source",
    [
        "1[^a]\n\n[^a]: 6\n\n    <div>2</div>",
        "1[^a]\n\n[^a]: <section>3</section>",
    ],
)
def test_raw_html_remains_explicitly_blocked(source):
    _, result = render(source)
    assert not result.exportable
    assert any(d.code == "footnote-context-pending" for d in result.diagnostics)


def test_impossible_anchor_terminates_with_diagnostics_and_preserves_definition():
    source = "1[^a] 2[^b]\n\n[^a]: 34\n\n[^b]: 56"
    doc, result = render(source, page=PageProfile(80, 20, 2))
    assert not result.exportable
    assert any(d.code == "footnote-anchor-overflow" for d in result.diagnostics)
    assert len(result.pages) <= 4
    assert_coverage(doc, result)


def test_accepted_note_lines_are_not_squeezed_out_by_later_body_text():
    source = "1[^a]\n\n" + "2\n\n" * 12 + "[^a]: " + "12 34 " * 40
    doc, result = render(source, page=PageProfile(80, 85, 5))
    assert result.exportable, result.diagnostics
    # At least three note lines stay on the anchor page, although body remains.
    foot = [f for f in result.pages[0].fragments if f.container_id]
    assert len({f.line_index for f in foot}) >= 3
    assert len(result.pages) > 1
    assert_bands(result)
    assert_coverage(doc, result)


def test_continuation_labels_reuse_source_and_assets_without_duplicate_primary_instances():
    doc, result = render("1[^a]\n\n[^a]: " + "12 34 " * 150, page=PageProfile(70, 60, 5))
    assert result.exportable, result.diagnostics
    occurrence = doc.nodes[-1].occurrences[0]
    labels = [f for f in result.fragments if f.occurrence_id == occurrence.occurrence_id]
    assert len(labels) == len(result.pages) > 1
    assert not labels[0].repeated and all(f.repeated for f in labels[1:])
    assert len({f.asset_id for f in labels}) == 1
    assert_coverage(doc, result)
    assert_bands(result)


def test_footnotes_in_body_with_unrelated_repeated_template_fields():
    from test_template_fields import setup

    _, doc, resolver, flow = setup("123\n\n4[^a]\n\n[^a]: " + "56 78 " * 70, repeat=True)
    result = layout_markdown(doc, resolver, flow=flow)
    assert result.exportable, result.diagnostics
    assert len(result.pages) > 1
    assert_coverage(doc, result)
    for page in result.pages:
        assert len([f for f in page.fragments if f.container_id == "template-field:header"]) == 3
        assert any(op.execution_domain == "page-footnotes" for op in page.paint_ops)


def test_small_footnote_body_limit_and_math_content():
    from test_math_layout import resolver

    doc = parse_markdown("1[^a]\n\n[^a]: $\\frac{2+3}{4}$\n\n    5")
    result = layout_markdown(doc, resolver())
    assert result.exportable, result.diagnostics
    assert_bands(result)
    assert_coverage(doc, result)
    _, tiny = render("1[^a]\n\n[^a]: 2", style=StyleProfile(em_mm=1))
    assert any(d.code == "footnote-text-size-limit" for d in tiny.diagnostics)


def test_note_reservation_does_not_leave_heading_alone_at_bottom():
    source = ""
    for i in range(1, 7):
        source += f"## {i}\n\n" + ("12 34 56 " * 6) + f"78[^a{i}]\n\n"
    source += "\n\n".join(f"[^a{i}]: " + "12 34 " * 15 for i in range(1, 7))
    doc, result = render(source, page=PageProfile(85, 100, 5))
    assert result.exportable, result.diagnostics
    for index, node in enumerate(doc.nodes):
        if node.kind != "heading":
            continue
        first = lambda n: next(o for child in n.walk() for o in child.occurrences)
        heading = next(f for f in result.fragments if f.occurrence_id == first(node).occurrence_id)
        paragraph = next(
            f
            for f in result.fragments
            if f.occurrence_id == first(doc.nodes[index + 1]).occurrence_id
        )
        assert heading.page_index == paragraph.page_index
    assert_bands(result)
    assert_coverage(doc, result)
