"""Atomic body figures reserve footnotes; raster capability gates remain distinct."""

from collections import Counter
from dataclasses import replace

import pytest
from test_footnote_pages import assert_bands, assert_coverage
from test_images import raster
from test_line_svg import resource

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.images import ImageStyle, RasterResource
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot


def figure_flow(tmp_path, *, bitmap=False, width=50):
    r = RasterResource.from_file(raster(tmp_path), "plot.png") if bitmap else resource(tmp_path)
    return replace(FlowStyle(), images=(r,), image=ImageStyle(width_mm=width))


@pytest.mark.parametrize("bitmap", [False, True])
def test_caption_reference_and_note_head_share_page(tmp_path, bitmap):
    ext = "png" if bitmap else "svg"
    source = "1\n\n2\n\n3\n\n![4[^a]](plot." + ext + ")\n\n[^a]: 56"
    doc = parse_markdown(source)
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(90, 90, 5),
        flow=figure_flow(tmp_path, bitmap=bitmap),
    )
    assert result.exportable, result.diagnostics
    assert result.plotter_exportable != bitmap
    figure = next(f for f in result.fragments if f.status in {"image-reference", "image-vector"})
    ref = next(n for root in doc.nodes for n in root.walk() if n.kind == "footnote_reference")
    number = next(
        f for f in result.fragments if f.occurrence_id == ref.occurrences[0].occurrence_id
    )
    note = next(
        f for f in result.fragments if f.container_id and f.container_id.startswith("footnote:")
    )
    assert figure.page_index == number.page_index == note.page_index
    assert_coverage(doc, result)
    assert_bands(result)
    if bitmap:
        assert any(page.images for page in result.pages)
        with pytest.raises(ValueError, match="Raster image"):
            plan_from_snapshot(result)
    else:
        plan_from_snapshot(result)


def test_figure_moves_past_existing_footnote_reservation(tmp_path):
    doc = parse_markdown("1[^a]\n\n![2](plot.svg)\n\n3\n\n[^a]: " + "12 34 " * 30)
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(90, 80, 5),
        flow=figure_flow(tmp_path, width=65),
    )
    assert result.exportable, result.diagnostics
    figure = next(f for f in result.fragments if f.status == "image-vector")
    assert figure.page_index > 0
    assert_coverage(doc, result)
    assert_bands(result)


def test_multiline_caption_with_multiple_references_is_atomic(tmp_path):
    doc = parse_markdown("![12 34 56 78[^a] 90 12 34 56[^b]](plot.svg)\n\n[^a]: 12\n\n[^b]: 34")
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(90, 100, 5),
        flow=figure_flow(tmp_path, width=45),
    )
    assert result.exportable, result.diagnostics
    figure = next(f for f in result.fragments if f.status == "image-vector")
    assert all(f.page_index == figure.page_index for f in result.fragments)
    assert len({f.line_index for f in result.fragments if f.container_id == figure.node_id}) > 1
    assert_coverage(doc, result)
    assert_bands(result)


def test_impossible_figure_caption_anchor_is_reported_once(tmp_path):
    doc = parse_markdown("![1[^a]](plot.svg)\n\n[^a]: 2")
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(90, 50, 5),
        flow=figure_flow(tmp_path, width=50),
    )
    assert not result.exportable
    assert any(d.code == "footnote-anchor-overflow" for d in result.diagnostics)
    assert len(result.pages) < 4
    assert_coverage(doc, result)


def test_body_rules_share_reservations_without_entering_note_text(tmp_path):
    source = "1[^a]\n\n---\n\n![2](plot.svg)\n\n---\n\n3\n\n[^a]: " + "12 34 " * 15
    doc = parse_markdown(source)
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(90, 90, 5),
        flow=figure_flow(tmp_path, width=45),
    )
    assert result.exportable, result.diagnostics
    rules = [
        op for page in result.pages for op in page.paint_ops if op.occurrence_id.endswith(":rule")
    ]
    assert len(rules) == 2
    assert_coverage(doc, result)
    assert_bands(result)


def test_unplaced_inline_image_reference_is_diagnosed_not_crashed(tmp_path):
    doc = parse_markdown("1 ![2[^a]](plot.svg)\n\n[^a]: 34")
    result = layout_markdown(doc, AssetResolver(builtin_numbers=True), flow=figure_flow(tmp_path))
    assert not result.exportable
    assert any(d.code == "footnote-anchor-unplaced" for d in result.diagnostics)
    definition = doc.nodes[-1]
    expected = Counter(o.occurrence_id for n in definition.walk() for o in n.occurrences)
    actual = Counter(f.occurrence_id for f in result.fragments if not f.repeated)
    assert all(actual[key] == count for key, count in expected.items())
