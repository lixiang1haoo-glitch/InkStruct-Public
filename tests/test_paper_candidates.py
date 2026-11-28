from dataclasses import replace

import pytest
from PIL import Image, ImageDraw

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.flow_template import PageLayout
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.paper_candidates import body_candidates
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template_authoring import (
    pack_reference_image,
    parse_template,
    template_json,
)
from inkstruct.layout.blocks import layout_markdown
from test_flow_templates import template


def printed_grid():
    im = Image.new("RGB", (800, 900), "white")
    pen = ImageDraw.Draw(im)
    for i in range(20):
        y = 35 + i * 40
        pen.rectangle((70, y, 670, y + 29), outline="#508482")
        for j in range(1, 20):
            pen.line((70 + j * 30, y, 70 + j * 30, y + 29), fill="#508482")
    return pack_reference_image(im.convert("RGBA"))


@pytest.mark.parametrize("mode", ["markdown", "plain-text"])
def test_printed_centers_wrap_and_continue(mode):
    bg = printed_grid()
    (box,) = body_candidates(bg, 120, 120)
    grid = box.paper_grid
    assert (grid.rows, grid.columns) == (20, 20)
    t = template(layouts=(PageLayout("p1", "p1", (box,), background=bg),))
    flow = FlowStyle(template=parse_template(template_json(t)), content_mode=mode)
    resolver = AssetResolver(builtin_numbers=True)
    snap = layout_markdown(parse_markdown("1" * 401, dialect=mode), resolver, flow=flow)
    assert snap.plotter_exportable and [len(p.fragments) for p in snap.pages] == [400, 1]
    for i in (0, 19, 20, 399, 400):
        f = snap.fragments[i]
        row, col = divmod(i % 400, 20)
        l, t, r, b = f.ink_bounds
        assert ((l + r) / 2, (t + b) / 2) == pytest.approx(
            ((85 + 30 * col) * 120 / 800, (49.5 + 40 * row) * 120 / 900), abs=0.16
        )
    assert all(op.execution_domain == "template-body" for p in snap.pages for op in p.paint_ops)
    if mode == "plain-text":
        snap = layout_markdown(parse_markdown("    1\n\n　1", dialect=mode), resolver, flow=flow)
        a, b = [f for f in snap.fragments if f.text == "1"]
        assert b.baseline_mm - a.baseline_mm == pytest.approx(2 * grid.pitch)
        assert a.x_mm - b.x_mm == pytest.approx(3 * box.region.width_mm / grid.columns)
        assert all(f.ink_bounds is None for f in snap.fragments if f.text.isspace())


def test_next_body_frame_uses_its_own_columns():
    bg = printed_grid()
    (first,) = body_candidates(bg, 120, 120)
    first = replace(
        first, paper_grid=replace(first.paper_grid, rows=1, last_mm=first.paper_grid.first_mm)
    )
    second = replace(
        first,
        frame_id="next",
        order=2,
        paper_grid=replace(first.paper_grid, columns=10),
        region=replace(first.region, y_mm=20, height_mm=12),
    )
    first = replace(first, region=replace(first.region, height_mm=10))
    flow = FlowStyle(template=template(layouts=(PageLayout("p1", "p1", (first, second)),)))
    snap = layout_markdown(parse_markdown("1" * 31), AssetResolver(builtin_numbers=True), flow=flow)
    assert [len(p.fragments) for p in snap.pages] == [30, 1]
    assert snap.fragments[20].advance_mm == pytest.approx(2 * snap.fragments[0].advance_mm)
