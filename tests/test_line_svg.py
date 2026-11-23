"""Physical-unit SVG subset, independently sampled error bounds and native integration."""

import base64
import math
import re
import zipfile
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from itertools import pairwise
from xml.etree import ElementTree as ET

import pytest
from test_math_layout import resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.images import ImageStyle, import_local_images
from inkstruct.document.line_svg import LineSvgResource, compile_svg, root_data
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.svg_geometry import distance_segment, point, transform
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page
from inkstruct.plotter.svg import page_svg


def svg(body, attrs='width="100mm" height="60mm" viewBox="0 0 100 60"'):
    return f'<svg xmlns="http://www.w3.org/2000/svg" {attrs} fill="none" stroke="black">{body}</svg>'.encode()


def resource(tmp_path, body='<path d="M10 10 L90 50"/>'):
    p = tmp_path / "plot.svg"
    p.write_bytes(svg(body))
    return LineSvgResource.from_file(p, "plot.svg")


def test_units_viewbox_transform_order_and_letterbox():
    raw = svg('<g transform="translate(5 3) scale(2)"><path d="m1 2 3 0 v2 h-3 z"/></g>')
    paths = compile_svg(raw, 100, 60)
    assert paths == (((7, 7), (13, 7), (13, 11), (7, 11), (7, 7)),)
    assert point(transform("translate(10 20) rotate(90 2 3)"), (3, 3)) == pytest.approx((12, 24))
    assert point(transform("matrix(1 0 0 1 3 4) skewX(45)"), (1, 2)) == pytest.approx((6, 6))
    raw = svg('<path d="M0 0 L10 10"/>', 'width="1in" height="72pt" viewBox="0 0 10 10"')
    assert root_data(raw)[1:3] == pytest.approx((25.4, 25.4))
    assert compile_svg(raw, 40, 20) == (((10, 0), (30, 20)),)
    raw = raw.replace(b"viewBox=", b'preserveAspectRatio="none" viewBox=')
    assert compile_svg(raw, 40, 20) == (((0, 0), (40, 20)),)
    assert root_data(svg('<path d="M1 1L2 2"/>', 'width="96" height="96px"'))[1:3] == (25.4, 25.4)


def test_bezier_error_is_bounded_after_final_size_and_affine_transform():
    raw = svg(
        '<g transform="translate(5 5) skewX(15) scale(0.8 0.5)"><path d="M5 5 C10 80 70 -10 80 50"/></g>'
    )
    tolerance = 0.015
    pts = compile_svg(raw, 200, 120, tolerance)[0]
    matrix = transform("scale(2) translate(5 5) skewX(15) scale(0.8 0.5)")
    control = ((5, 5), (10, 80), (70, -10), (80, 50))
    errors = []
    for i in range(2001):
        t = i / 2000
        weights = ((1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t**3)
        p = point(matrix, tuple(sum(w * c[k] for w, c in zip(weights, control)) for k in (0, 1)))
        errors.append(min(distance_segment(p, a, b) for a, b in pairwise(pts)))
    assert max(errors) <= tolerance
    assert len(pts) > len(compile_svg(raw, 100, 60, tolerance)[0])
    assert len(pts) > len(compile_svg(raw, 200, 120, 0.2)[0])


def test_quadratic_smooth_reflections_and_subpath_boundaries():
    one = svg('<path d="M10 30 Q20 5 30 30 T50 30 M10 40 C20 30 25 30 30 40 S40 50 50 40"/>')
    explicit = svg(
        '<path d="M10 30 Q20 5 30 30 Q40 55 50 30 M10 40 C20 30 25 30 30 40 C35 50 40 50 50 40"/>'
    )
    assert compile_svg(one, 100, 60) == compile_svg(explicit, 100, 60)
    assert len(compile_svg(one, 100, 60)) == 2
    closed = compile_svg(svg('<path d="M10 10h10v10z l20 0"/>'), 100, 60)
    assert closed[0][-1] == closed[1][0] == (10, 10)
    assert closed[1][-1] == (30, 10)


def test_arc_error_and_sweep_are_bounded_independently():
    raw = svg(
        '<g transform="translate(40 30) matrix(1 0.2 0.3 0.8 0 0)"><path d="M-20 0 A20 10 0 1 0 20 0 A20 10 0 1 0 -20 0Z"/></g>'
    )
    tolerance = 0.01
    pts = compile_svg(raw, 100, 60, tolerance)[0]
    matrix = transform("translate(40 30) matrix(1 0.2 0.3 0.8 0 0)")
    for i in range(2001):
        theta = 2 * math.pi * i / 2000
        p = point(matrix, (20 * math.cos(theta), 10 * math.sin(theta)))
        assert min(distance_segment(p, a, b) for a, b in pairwise(pts)) <= tolerance
    up = compile_svg(svg('<path d="M30 30 A20 20 0 0 1 70 30"/>'), 100, 60)[0]
    down = compile_svg(svg('<path d="M30 30 A20 20 0 0 0 70 30"/>'), 100, 60)[0]
    assert min(y for x, y in up) < 11 and max(y for x, y in down) > 49
    # Small radii are corrected per SVG endpoint rules, and zero radius is a line.
    corrected = compile_svg(svg('<path d="M30 30 A5 5 0 0 1 70 30"/>'), 100, 60)[0]
    assert corrected == up
    assert compile_svg(svg('<path d="M10 10 A0 5 0 0 1 20 20"/>'), 100, 60)[0] == (
        (10, 10),
        (20, 20),
    )


@pytest.mark.parametrize(
    "body",
    [
        '<text x="1">hello</text>',
        '<image href="a.png"/>',
        '<use href="#a"/>',
        "<script/>",
        "<foreignObject/>",
        "<defs/>",
        "<svg/>",
        '<path d="M1 1L2 2" fill="black"/>',
        '<path d="M1 1L2 2" stroke="red"/>',
        '<path d="M1 1L2 2" style="stroke-dasharray:1 2"/>',
        '<path d="M1 1L2 2" transform="scale(0)"/>',
        '<path d="M1 1L2 2" opacity="0"/>',
        '<path d="M1 1L2 2" clip-path="url(#c)"/>',
        '<path d="M1 1L2 2" onclick="x()"/>',
        '<path d="M1 1L2 2" vector-effect="non-scaling-stroke"/>',
        '<path d="M1 1 L"/>',
        '<path d="L1 1"/>',
        '<path d="M1 1R2 2"/>',
        '<path d="M1 1"/>',
        '<path d="M1 1L1 1"/>',
        '<path d="M1 1L200 200"/>',
        '<path d="M1 1 A-1 2 0 0 1 3 3"/>',
        '<path d="M1 1 A1 2 0 2 1 3 3"/>',
        '<path d="M1 1L1e999 2"/>',
        '<path d="M1 1L2 2" class="styled"/>',
    ],
)
def test_unsupported_content_is_never_silently_skipped(body):
    with pytest.raises(ValueError):
        compile_svg(svg(body), 100, 60)


def test_xml_budgets_and_resource_integrity(tmp_path):
    for raw in (
        b'<!DOCTYPE svg [<!ENTITY x "123">]>' + svg('<path d="M1 1L2 2"/>'),
        b'<?xml-stylesheet href="remote"?>' + svg('<path d="M1 1L2 2"/>'),
        svg("<g>" * 34 + '<path d="M1 1L2 2"/>' + "</g>" * 34),
        svg('<line x1="1" y1="1" x2="2" y2="2"/>' * 5001),
        svg('<path d="M1 1L2 2"/>', 'width="100%" height="60mm"'),
    ):
        with pytest.raises(ValueError):
            compile_svg(raw, 100, 60)
    r = resource(tmp_path)
    with pytest.raises(ValueError, match="hash"):
        replace(r, original_sha256="0" * 64)
    with pytest.raises(ValueError, match="dimensions"):
        replace(r, width_mm=99)
    assert sha256(base64.b64decode(r.original_base64)).hexdigest() == r.original_sha256
    with pytest.raises(ValueError, match="budget"):
        compile_svg(svg('<path d="M1 1 ' + "L2 2 1 1 " * 26000 + '"/>'), 100, 60)


def test_shapes_and_unfilled_style_inheritance():
    body = """<g style="fill:none;stroke:#000;stroke-width:2px">
    <line x1="10" y1="10" x2="20" y2="20"/>
    <polyline points="20 10 30 10 30 20"/><polygon points="40 10 50 10 50 20"/>
    <rect x="10" y="30" width="10" height="10"/><circle cx="40" cy="40" r="5"/>
    <ellipse cx="70" cy="40" rx="10" ry="5"/></g>"""
    paths = compile_svg(svg(body), 100, 60)
    assert len(paths) == 6
    assert paths[0] == ((10, 10), (20, 20))
    assert all(p[0] == p[-1] for p in paths[2:])


def test_native_document_pagination_provenance_and_machine_svg(tmp_path):
    r = resource(tmp_path, '<path d="M10 10 Q50 40 90 10 M10 50 L90 50"/>')
    session = SourceSession("1\n\n2\n\n![12](plot.svg)\n\n3")
    flow = FlowStyle(images=(r,), image=ImageStyle(width_mm=40, svg_tolerance_mm=0.02))
    rr = resolver()
    page = PageProfile(60, 60, 5)
    snapshot = layout_markdown(parse_markdown(session), rr, page=page, flow=flow)
    assert snapshot.exportable and snapshot.plotter_exportable, snapshot.diagnostics
    assert len(snapshot.pages) == 2 and not any(p.images for p in snapshot.pages)
    assert Counter(f.occurrence_id for f in snapshot.fragments) == Counter(
        o.occurrence_id for o in parse_markdown(session).occurrences
    )
    figure = next(f for f in snapshot.fragments if f.status == "image-vector")
    assert figure.asset_id is None and r.original_sha256 in figure.source_resource_id
    plan = plan_from_snapshot(snapshot)
    paths = [s for p in plan.pages for s in p.strokes if s.occurrence_id == figure.occurrence_id]
    assert len(paths) == 2 and all(r.original_sha256 in s.source_stroke_id for s in paths)
    for page_plan in plan.pages:
        routed = route_page(page_plan, optimize=True).page
        canonical = lambda p: min(p, tuple(reversed(p)))
        assert Counter(canonical(s.points) for s in routed.strokes) == Counter(
            canonical(s.points) for s in page_plan.strokes
        )
        tree = ET.fromstring(page_svg(routed))
        assert all(
            n.tag.endswith("path") and set(re.findall("[A-Za-z]", n.attrib["d"])) <= {"M", "L"}
            for n in tree
        )
    project = tmp_path / "vector.inkdoc"
    save_package(project, session, rr, page, StyleProfile(), flow=flow)
    (tmp_path / "plot.svg").unlink()
    p = load_package(project)
    assert (
        layout_markdown(
            parse_markdown(p.session), p.resolver, page=p.page, style=p.style, flow=p.flow
        )
        == snapshot
    )
    with zipfile.ZipFile(project) as z:
        assert len([n for n in z.namelist() if n.startswith("images/")]) == 1
        assert b"original_base64" not in z.read("styles.json")


def test_local_import_and_final_size_edge_warning(tmp_path):
    resource(tmp_path)
    doc = parse_markdown("![](plot.svg)")
    flow, issues = import_local_images(doc, FlowStyle(), tmp_path)
    assert not issues and isinstance(flow.images[0], LineSvgResource)
    small = replace(flow, image=ImageStyle(width_mm=0.1))
    result = layout_markdown(doc, resolver(), flow=small)
    assert [d.severity for d in result.diagnostics if d.code == "svg-ink-overflow"] == ["warning"]
    assert result.plotter_exportable
    assert plan_from_snapshot(result).pages[0].strokes
    with pytest.raises(ValueError):
        ImageStyle(svg_tolerance_mm=0)


def test_cli_svg_export_and_invalid_input_leave_no_partial_machine_files(tmp_path):
    from inkstruct.cli import main

    resource(tmp_path)
    source = tmp_path / "doc.md"
    source.write_text("![12](plot.svg)")
    output = tmp_path / "machine"
    assert (
        main(
            [
                "document",
                "render",
                str(source),
                "--mode",
                "markdown",
                "--plotter",
                "--optimize-paths",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    xml = ET.parse(output / "page-001.svg").getroot()
    assert all(n.tag.endswith("path") for n in xml)
    (tmp_path / "plot.svg").write_bytes(svg("<text>123</text>"))
    bad = tmp_path / "invalid"
    assert (
        main(
            [
                "document",
                "render",
                str(source),
                "--mode",
                "markdown",
                "--plotter",
                "--output",
                str(bad),
            ]
        )
        != 0
    )
    assert not bad.exists()


def test_rotated_arc_and_viewbox_offset():
    # Rotation is exercised in the arc command, not only in an outer transform.
    raw = svg(
        '<path d="M30 30 A20 10 45 1 1 50 50"/>',
        'width="100mm" height="80mm" viewBox="-10 -10 100 80"',
    )
    pts = compile_svg(raw, 100, 80, 0.01)[0]
    assert pts[0] == (40, 40) and pts[-1] == (60, 60)
    # Inverse rotation: start/end become (-sqrt(200),0) / (+sqrt(200),0)
    # about (40,40); centre branch for large clockwise arc lies along -minor axis.
    c = math.sqrt(0.5)
    centre_prime = (0, -math.sqrt(50))
    centre = (40 - c * centre_prime[1], 40 + c * centre_prime[1])
    for x, y in pts:
        dx, dy = x - 10 - centre[0], y - 10 - centre[1]
        u, v = c * (dx + dy), c * (-dx + dy)
        assert (u / 20) ** 2 + (v / 10) ** 2 == pytest.approx(1, abs=1e-10)


def test_template_field_vector_stays_writable_and_retains_provenance(tmp_path):
    from test_template_fields import setup

    _, doc, rr, flow = setup("![](plot.svg)\n\n2")
    r = resource(tmp_path)
    result = layout_markdown(
        doc, rr, flow=replace(flow, images=(r,), image=ImageStyle(width_mm=20))
    )
    assert result.plotter_exportable, result.diagnostics
    vector = next(f for f in result.fragments if f.status == "image-vector")
    strokes = [
        s
        for p in plan_from_snapshot(result).pages
        for s in p.strokes
        if s.occurrence_id == vector.occurrence_id
    ]
    assert all(s.execution_domain.startswith("template-field:") for s in strokes)
    assert all(r.original_sha256 in s.source_stroke_id for s in strokes)
