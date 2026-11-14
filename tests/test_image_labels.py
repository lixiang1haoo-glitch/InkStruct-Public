from dataclasses import replace

import pytest
from PIL import Image

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import FlowTemplate, NamedField, PageLayout, TextFrame
from inkstruct.document.image_labels import ImageLabel, PATTERN
from inkstruct.document.images import import_image_file
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Region
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot

from test_document_layout import provider


@pytest.mark.parametrize("caption", ["人", "*人*~~人~~"])
def test_body_after_image_starts_below_caption(tmp_path, caption):
    image = tmp_path / "diagram.png"
    Image.new("RGB", (40, 40), "white").save(image)
    source = f"人\n\n![{caption}]({image.name})\n\n人"
    document = parse_markdown(source)
    flow = FlowStyle(images=(import_image_file(image, image.name),))
    result = layout_markdown(document, AssetResolver(generated=provider()),
                             page=PageProfile(150, 160, 10), style=StyleProfile(), flow=flow)

    assert result.exportable and len(result.pages) == 1
    picture, = result.pages[0].images
    captions = [f for f in result.fragments if f.status == "ready" and f.span.start < picture.span.end
                and f.span.start >= picture.span.start]
    following, = [f for f in result.fragments if f.status == "ready" and f.span.start >= picture.span.end]
    assert captions and min(f.logical_bounds[1] for f in captions) >= picture.bounds[3]
    assert following.logical_bounds[1] >= max(f.logical_bounds[3] for f in captions)
    if caption.startswith("*"):
        operations = result.pages[0].paint_ops
        assert any(":caption-underline:" in op.occurrence_id for op in operations)
        assert any(":caption-strike:" in op.occurrence_id for op in operations)


@pytest.mark.parametrize("format_name", ["svg", "png"])
def test_label_follows_picture_and_keeps_frozen_ink(tmp_path, format_name):
    name = "diagram." + format_name
    file = tmp_path / name
    if format_name == "svg":
        file.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="20mm" '
                        'viewBox="0 0 20 20"><path d="M1 1 L19 19" fill="none" stroke="black"/></svg>',
                        encoding="utf-8")
    else:
        Image.new("RGB", (40, 40), "white").save(file)
    image_source = f"![人]({name})"
    label_source = ImageLabel(25, 60, 4).source_line("人$F_1$")
    session = SourceSession(f"{image_source}\n{label_source}\n\n{image_source}")
    document = parse_markdown(session)
    assert not document.diagnostics
    image, other = [node for root in document.nodes for node in root.walk() if node.kind == "image"]
    label = next(node for node in image.children if node.kind == "image_label")
    assert not any(node.kind == "image_label" for node in other.children)
    owner = image.node_id, label.node_id
    assert any(node.kind == "math_inline" for node in label.children)

    page = PageProfile(150, 160, 10)
    style = StyleProfile()
    flow = FlowStyle(images=(import_image_file(file, name),))
    resolver = AssetResolver(generated=provider("人F1"))

    def render(document, flow):
        result = layout_markdown(document, resolver, page=page, style=style, flow=flow)
        assert result.exportable
        glyphs = [fragment for fragment in result.fragments if fragment.image_label == owner]
        assert [f.text for f in glyphs] == ["人", "F", "1"]
        assert all(f.asset_id and f.status == "ready" for f in glyphs)
        rect = next(f.logical_bounds for f in result.fragments if f.node_id == image.node_id)
        return result, glyphs, rect

    result, glyphs, rect = render(document, flow)
    smaller = replace(flow, image=replace(flow.image, height_mm=30))
    _, resized, resized_rect = render(document, smaller)
    assert resized[0].x_mm - glyphs[0].x_mm == pytest.approx(
        resized_rect[0] + 0.25 * (resized_rect[2] - resized_rect[0]) - rect[0] - 0.25 * (rect[2] - rect[0])
    )
    assert resized[0].baseline_mm - glyphs[0].baseline_mm == pytest.approx(-18)
    assert [f.glyph_em_mm for f in resized] == pytest.approx([4, 4, 2.8])

    start, end = PATTERN.fullmatch(label_source).span("position")
    session.apply(label.span.start + start, label.span.start + end, ImageLabel(35, 60).position)
    moved, after_move, _ = render(parse_markdown(session), flow)
    assert after_move[0].x_mm - glyphs[0].x_mm == pytest.approx(6)
    assert [(f.occurrence_id, f.asset_id) for f in after_move] == [(f.occurrence_id, f.asset_id) for f in glyphs]

    plan = plan_from_snapshot(moved, omit_reference_images=format_name == "png")
    ids = {f.occurrence_id for f in after_move}
    assert ids <= {stroke.occurrence_id for p in plan.pages for stroke in p.strokes}
    path = tmp_path / "annotated.inkdoc"
    save_package(path, session, resolver, page, style, flow=flow)
    saved = load_package(path)
    reopened = layout_markdown(parse_markdown(saved.session), saved.resolver, page=saved.page,
                               style=saved.style, flow=saved.flow)
    assert reopened.pages == moved.pages


def test_unattached_and_invalid_labels_report_errors():
    label = ImageLabel(35, 60).source_line("人")
    assert [item.code for item in parse_markdown("人\n\n" + label).diagnostics] == ["image-label-orphan"]
    invalid = label.replace("35.000000", "135.000000")
    parsed = parse_markdown("![](diagram.svg)\n" + invalid)
    assert [item.code for item in parsed.diagnostics] == ["image-label-syntax"]


def test_image_label_in_markdown_field_retains_image_and_field_identity(tmp_path):
    path = tmp_path / "diagram.png"
    Image.new("RGB", (40, 40), "white").save(path)
    body = TextFrame("body", "Body", Region("body", 10, 10, 80, 30))
    field = TextFrame("field", "Field", Region("field", 10, 45, 80, 40), "field", field_id="figure")
    template = FlowTemplate(kind="custom", width_mm=100, height_mm=100,
                            layouts=(PageLayout("layout", "Layout", (body, field)),),
                            loop_pages=("layout",), fields=(NamedField("figure", "Figure", value_type="markdown"),))
    source = ":::field figure\n![](diagram.png)\n" + ImageLabel(50, 50).source_line("人") + "\n:::\n\n人"
    document = parse_markdown(source, field_blocks=True)
    flow = FlowStyle(template=template, image=replace(FlowStyle().image, height_mm=20),
                     images=(import_image_file(path, path.name),))
    resolver = AssetResolver(generated=provider("人"))
    snapshot = layout_markdown(document, resolver, page=template.page, flow=flow)
    image = next(f for f in snapshot.fragments if f.status == "image-reference")
    label = next(f for f in snapshot.fragments if f.image_label)
    assert label.image_label[0] == image.node_id
    assert label.container_id == image.container_id == "template-field:figure"
