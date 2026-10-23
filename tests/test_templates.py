"""Template pagination, preview separation, calibration and portable identity."""

import json
import xml.etree.ElementTree as ET
from dataclasses import replace

import pytest
from test_math_layout import resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.document.template import Anchor, PageTemplate, Region, TemplateFace, TemplateRule
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg as machine_svg
from inkstruct.renderers.pages import page_svg


def template(mode="preprinted", **kwargs):
    return PageTemplate(
        "test",
        90,
        110,
        TemplateFace(
            Region("body", 10, 60, 60, 30),
            (TemplateRule("frame", ((8, 50), (75, 50), (75, 95))),),
            (Anchor("signature", 45, 30),),
            (Region("header", 10, 10, 60, 30),),
        ),
        TemplateFace(
            Region("body", 15, 10, 60, 80), (TemplateRule("frame", ((8, 5), (80, 5), (80, 95))),)
        ),
        mode=mode,
        **kwargs,
    )


def test_template_modes_preserve_body_and_never_write_preview_frames():
    doc, r = parse_markdown("1\n\n2\n\n3\n\n4\n\n5\n\n6"), resolver()
    t = template()
    a = layout_markdown(doc, r, flow=FlowStyle(template=t))
    b = layout_markdown(doc, r, flow=FlowStyle(template=replace(t, mode="blank")))
    assert a.exportable and b.exportable
    assert len(a.pages) == 2
    assert a.fragments == b.fragments
    assert [f.occurrence_id for f in a.fragments] == [o.occurrence_id for o in doc.occurrences]
    assert any(d.code == "template-calibration-unreviewed" for d in a.diagnostics)
    for p in a.pages:
        x1, y1, x2, y2 = t.bounds(p.index)
        for f in p.fragments:
            assert f.ink_bounds[0] >= x1 and f.ink_bounds[1] >= y1
            assert f.ink_bounds[2] <= x2 and f.ink_bounds[3] <= y2
        assert len(p.preview_ops) == 1
        assert "template:frame" in page_svg(a, p.index)
    pa, pb = plan_from_snapshot(a), plan_from_snapshot(b)
    for i, p in enumerate(pa.pages):
        assert all(s.execution_domain == "template-body" for s in p.strokes)
        assert pb.pages[i].strokes[0].execution_domain == "template-frame"
        assert len(pb.pages[i].strokes) == len(p.strokes) + 1
        assert all(s.occurrence_id != "template:frame" for s in p.strokes)
        root = ET.fromstring(machine_svg(p))
        assert all(n.tag.endswith("path") for n in root)


def test_calibration_translates_every_point_and_fragment_without_reflow():
    doc, r, t = parse_markdown("1\n\n2\n\n3\n\n4"), resolver(), template()
    a = layout_markdown(doc, r, flow=FlowStyle(template=t))
    b = layout_markdown(
        doc, r, flow=FlowStyle(template=replace(t, offset_x_mm=1.25, offset_y_mm=-2))
    )
    assert a.exportable and b.exportable and len(a.pages) == len(b.pages)
    for f, g in zip(a.fragments, b.fragments):
        assert f.occurrence_id == g.occurrence_id and f.asset_id == g.asset_id
        assert g.x_mm == pytest.approx(f.x_mm + 1.25)
        assert g.baseline_mm == pytest.approx(f.baseline_mm - 2)
    for p, q in zip(a.pages, b.pages):
        assert p.preview_ops == q.preview_ops  # Printed paper stays fixed during ink calibration.
        for op, oq in zip(p.paint_ops, q.paint_ops):
            for (x, y), point in zip(op.points, oq.points):
                assert point == pytest.approx((x + 1.25, y - 2))


def test_template_roundtrip_includes_mode_geometry_and_source_identity(tmp_path):
    session, r, t = SourceSession("1\n\n2"), resolver(), template("blank")
    flow = FlowStyle(template=t)
    a = layout_markdown(parse_markdown(session), r, flow=flow)
    path = tmp_path / "template.inkdoc"
    save_package(path, session, r, t.page, StyleProfile(), flow=flow)
    loaded = load_package(path)
    assert loaded.flow == flow
    b = layout_markdown(
        parse_markdown(loaded.session),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    assert a == b


def test_large_first_line_moves_to_taller_continuation_without_false_overflow():
    result = layout_markdown(
        parse_markdown("1"),
        resolver(),
        style=StyleProfile(line_height_mm=40),
        flow=FlowStyle(template=template()),
    )
    assert result.exportable and len(result.pages) == 2
    assert not result.pages[0].fragments and len(result.pages[1].fragments) == 1


def test_table_atomic_group_can_skip_small_first_region():
    source = "|1|2|\n|---|---|\n" + "|3|4|\n" * 10
    r = layout_markdown(
        parse_markdown(source),
        resolver(),
        flow=FlowStyle(template=template(), table=TableStyle(width_mm=50, min_row_height_mm=18)),
    )
    assert r.exportable, r.diagnostics
    assert not r.pages[0].fragments
    assert len(r.pages) >= 3
    for page in r.pages:
        bounds = template().bounds(page.index)
        for op in page.paint_ops:
            assert all(
                bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3] for x, y in op.points
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "guess"},
        {"offset_x_mm": 100},
        {"offset_y_mm": float("nan")},
        {"schema_version": "v100"},
        {"source_sha256": "bad"},
        {"continuation": TemplateFace(Region("body", 10, 10, 50, 80))},
        {"continuation": TemplateFace(Region("body", 10, 10, 60, 20))},
    ],
)
def test_invalid_template_rejected(changes):
    with pytest.raises(ValueError):
        replace(template(), **changes)


def test_overlap_and_frame_pen_outside_paper_rejected():
    with pytest.raises(ValueError, match="overlap"):
        TemplateFace(Region("body", 1, 1, 10, 10), reserved=(Region("header", 5, 5, 10, 10),))
    with pytest.raises(ValueError, match="outside"):
        replace(
            template(),
            first=TemplateFace(
                Region("body", 10, 10, 60, 30), rules=(TemplateRule("outside", ((0, 0), (5, 5))),)
            ),
        )


def test_cli_template_and_portable_reopen(tmp_path):
    from dataclasses import asdict

    from inkstruct.cli import main

    src, conf = tmp_path / "numbers.md", tmp_path / "template.json"
    src.write_text("1\n\n2\n\n3\n\n4")
    conf.write_text(json.dumps(asdict(template())))
    project = tmp_path / "result.inkdoc"
    assert (
        main(
            [
                "document",
                "render",
                str(src),
                "--mode",
                "markdown",
                "--template",
                str(conf),
                "--save-project",
                str(project),
                "--plotter",
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    assert load_package(project).page == template().page
    assert (
        main(
            [
                "document",
                "render",
                str(project),
                "--plotter",
                "--output",
                str(tmp_path / "reopened"),
            ]
        )
        == 0
    )
    for f in (tmp_path / "out").glob("*.svg"):
        assert f.read_bytes() == (tmp_path / "reopened" / f.name).read_bytes()
    assert (
        main(
            [
                "document",
                "render",
                str(project),
                "--page-width",
                "210",
                "--output",
                str(tmp_path / "invalid"),
            ]
        )
        != 0
    )


def test_background_is_embedded_preview_only_and_verified(tmp_path):
    import base64
    import io
    from hashlib import sha256

    from PIL import Image

    from inkstruct.document.template import TemplateBackground
    from inkstruct.renderers.pages import page_png

    stream = io.BytesIO()
    Image.new("RGB", (20, 30), "blue").save(stream, format="PNG")
    raw = stream.getvalue()
    bg = TemplateBackground(base64.b64encode(raw).decode(), sha256(raw).hexdigest())
    t = template()
    t = replace(t, first=replace(t.first, background=bg))
    session, r = SourceSession("1"), resolver()
    flow = FlowStyle(template=t)
    a = layout_markdown(parse_markdown(session), r, flow=flow)
    assert a.pages[0].background == bg and not a.pages[0].preview_ops
    assert "data:image/png;base64," in page_svg(a, 0)
    assert page_png(a, 0).getpixel((0, 0)) == (0, 0, 255)
    assert "image" not in machine_svg(plan_from_snapshot(a).pages[0])
    b = layout_markdown(
        parse_markdown(session), r, flow=replace(flow, template=replace(t, mode="blank"))
    )
    assert b.pages[0].background is None and "data:image" not in page_svg(b, 0)
    path = tmp_path / "with-background.inkdoc"
    save_package(path, session, r, t.page, StyleProfile(), flow=flow)
    assert load_package(path).flow == flow
    with pytest.raises(ValueError, match="hash"):
        replace(bg, sha256="0" * 64)
    with pytest.raises(ValueError):
        TemplateBackground("garbage", "0" * 64)
