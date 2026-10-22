"""Reference raster provenance, atomic figures and strict plotter gating."""

import base64
import io
import json
import zipfile
from collections import Counter
from dataclasses import replace
from hashlib import sha256

import pytest
from PIL import Image
from test_math_layout import resolver
from test_template_fields import setup as field_setup

from inkstruct.document.editing import SourceSession
from inkstruct.document.images import ImageStyle, RasterResource, import_local_images
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.renderers.pages import export_pages, page_png, page_svg


def raster(tmp_path, name="plot.png", size=(120, 60)):
    p = tmp_path / name
    Image.new("RGB", size, "#3366ff").save(p)
    return p


def test_image_alt_mapping_and_reference_capabilities_are_distinct(tmp_path):
    doc = parse_markdown('1\n\n![12 &amp; 3](plot.png "metadata")\n\n4')
    flow, issues = import_local_images(doc, FlowStyle(), tmp_path)
    assert issues and not flow.images
    p = raster(tmp_path)
    flow, issues = import_local_images(doc, FlowStyle(), tmp_path)
    assert not issues
    result = layout_markdown(doc, resolver("1234&"), flow=flow)
    assert result.exportable and not result.plotter_exportable
    assert len(result.pages[0].images) == 1
    assert Counter(f.occurrence_id for f in result.fragments) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    amp = next(o for o in doc.occurrences if o.text == "&")
    assert doc.source[amp.span.start : amp.span.end] == "&amp;"
    assert result.pages[0].images[0].original_sha256 == sha256(p.read_bytes()).hexdigest()
    assert "data:image/png;base64," in page_svg(result, 0)
    assert "NOT PLOTTER READY" in page_svg(result, 0)
    with pytest.raises(ValueError, match="Raster"):
        plan_from_snapshot(result)
    # Removing warnings cannot bypass the actual scene capability gate.
    with pytest.raises(ValueError, match="Raster"):
        plan_from_snapshot(replace(result, diagnostics=()))
    export_pages(result, tmp_path / "preview")
    report = json.loads((tmp_path / "preview/layout.json").read_text(encoding="utf-8"))
    assert not report["plotter_exportable"]
    assert page_png(result, 0).size


def test_image_caption_is_atomic_and_proportions_are_preserved(tmp_path):
    doc = parse_markdown("1\n\n2\n\n![123](plot.png)\n\n3")
    r = RasterResource.from_file(raster(tmp_path), "plot.png")
    flow = FlowStyle(images=(r,), image=ImageStyle(width_mm=40))
    result = layout_markdown(doc, resolver(), page=PageProfile(60, 60, 5), flow=flow)
    assert result.exportable and len(result.pages) == 2, result.diagnostics
    image = next(p.images[0] for p in result.pages if p.images)
    assert image.bounds[2] - image.bounds[0] == 40
    assert image.bounds[3] - image.bounds[1] == 20
    image_node = next(n for root in doc.nodes for n in root.walk() if n.kind == "image")
    ids = {o.occurrence_id for n in image_node.walk() for o in n.occurrences}
    assert len({f.page_index for f in result.fragments if f.occurrence_id in ids}) == 1
    assert ImageStyle(width_mm=40, max_height_mm=10).dimensions(r) == (20, 10)


def test_missing_inline_and_oversize_images_are_explicit_errors(tmp_path):
    missing = layout_markdown(parse_markdown("![1](missing.png)"), resolver())
    assert not missing.exportable and any(
        d.code == "image-resource-missing" for d in missing.diagnostics
    )
    resource = RasterResource.from_file(raster(tmp_path), "plot.png")
    flow = FlowStyle(images=(resource,))
    inline = layout_markdown(parse_markdown("1 ![2](plot.png) 3"), resolver(), flow=flow)
    assert not inline.exportable
    tall = layout_markdown(
        parse_markdown("![1](plot.png)"), resolver(), flow=flow, page=PageProfile(60, 30, 5)
    )
    assert not tall.exportable
    assert {"image-width-overflow", "image-height-overflow"} <= {d.code for d in tall.diagnostics}


def test_image_project_is_self_contained_and_validates_original_and_preview(tmp_path):
    path = raster(tmp_path)
    session = SourceSession("![12](plot.png)")
    flow = FlowStyle(images=(RasterResource.from_file(path, "plot.png"),))
    r = resolver()
    first = layout_markdown(parse_markdown(session), r, flow=flow)
    target = tmp_path / "image.inkdoc"
    save_package(target, session, r, PageProfile(), StyleProfile(), flow=flow)
    path.unlink()
    loaded = load_package(target)
    restored = layout_markdown(parse_markdown(loaded.session), loaded.resolver, flow=loaded.flow)
    assert restored == first
    with zipfile.ZipFile(target) as z:
        style = z.read("styles.json")
        assert b"png_base64" not in style and b"original_file" in style
        assert len([n for n in z.namelist() if n.startswith("images/")]) == 2
    resource = flow.images[0]
    red = io.BytesIO()
    Image.new("RGBA", (120, 60), "red").save(red, format="PNG")
    with pytest.raises(ValueError, match="pixels"):
        replace(
            resource,
            png_base64=base64.b64encode(red.getvalue()).decode(),
            png_sha256=sha256(red.getvalue()).hexdigest(),
        )
    with pytest.raises(ValueError, match="hash"):
        replace(resource, original_sha256="0" * 64)


def test_image_import_rejects_network_and_escape_paths_without_reading_them(tmp_path):
    for src in (
        "https://example.com/x.png",
        "../outside.png",
        "/tmp/private.png",
    ):
        doc = parse_markdown(f"![1]({src})")
        flow, issues = import_local_images(doc, FlowStyle(), tmp_path)
        assert issues and not flow.images


def test_image_import_rejects_real_symlink_escape(tmp_path):
    inside = tmp_path / "inner"
    inside.mkdir()
    p = raster(tmp_path)
    try:
        (inside / "escape.png").symlink_to(p)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symbolic-link privilege; real symlink check unverified")
        raise
    flow, issues = import_local_images(parse_markdown("![1](escape.png)"), FlowStyle(), inside)
    assert issues and not flow.images


def test_bound_image_remains_reference_only_after_template_composition(tmp_path):
    _, doc, r, flow = field_setup("![1](plot.png)\n\n2")
    resource = RasterResource.from_file(raster(tmp_path), "plot.png")
    flow = replace(flow, images=(resource,), image=ImageStyle(width_mm=20))
    snapshot = layout_markdown(doc, r, flow=flow)
    assert snapshot.exportable and not snapshot.plotter_exportable, snapshot.diagnostics
    assert snapshot.pages[0].images[0].bounds[0] >= 10
    with pytest.raises(ValueError, match="Raster"):
        plan_from_snapshot(snapshot)


def test_cli_reference_export_and_machine_refusal(tmp_path):
    from inkstruct.cli import main

    p = tmp_path / "image.md"
    p.write_text("![12](plot.png)")
    raster(tmp_path)
    project = tmp_path / "saved.inkdoc"
    assert (
        main(
            [
                "document",
                "render",
                str(p),
                "--mode",
                "markdown",
                "--output",
                str(tmp_path / "preview"),
                "--save-project",
                str(project),
            ]
        )
        == 0
    )
    assert (
        main(
            ["document", "render", str(project), "--plotter", "--output", str(tmp_path / "machine")]
        )
        == 2
    )
    assert not (tmp_path / "machine").exists()


def test_caption_formatting_and_math_are_regular_handwritten_geometry(tmp_path):
    doc = parse_markdown("![**12** $1+2$](plot.png)")
    resource = RasterResource.from_file(raster(tmp_path), "plot.png")
    result = layout_markdown(doc, resolver(), flow=FlowStyle(images=(resource,)))
    assert result.exportable, result.diagnostics
    assert any(":caption-underline:" in op.occurrence_id for op in result.pages[0].paint_ops)
    assert Counter(f.occurrence_id for f in result.fragments) == Counter(
        o.occurrence_id for o in doc.occurrences
    )


def test_jpeg_exif_orientation_and_resource_limits(tmp_path):
    p = tmp_path / "rotated.jpg"
    im = Image.new("RGB", (20, 10), "red")
    exif = Image.Exif()
    exif[274] = 6
    im.save(p, exif=exif)
    resource = RasterResource.from_file(p, "rotated.jpg")
    assert (resource.width_px, resource.height_px) == (10, 20)
    p = raster(tmp_path, "large.png", (2001, 1000))
    with pytest.raises(ValueError, match="2 million"):
        RasterResource.from_file(p, "large.png")
    p = tmp_path / "animated.png"
    im.save(p, save_all=True, append_images=[Image.new("RGB", (20, 10), "blue")])
    with pytest.raises(ValueError, match="single frame"):
        RasterResource.from_file(p, "animated.png")
