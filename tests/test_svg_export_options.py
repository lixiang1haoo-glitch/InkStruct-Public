import json
from dataclasses import replace
from xml.etree import ElementTree

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.style import MathStyle
from inkstruct.plotter.export import export_plan
from inkstruct.plotter.options import ExportOptions, content_frames, parse_pages, prepare_export
from inkstruct.plotter.svg import page_svg
from inkstruct.scene.schema import PaintOp


@pytest.mark.parametrize('text,expected', [('', (0, 1, 2, 3, 4)), ('1-3,5', (0, 1, 2, 4)), ('2，2,1', (0, 1))])
def test_page_syntax(text, expected):
    assert parse_pages(text, 5) == expected


@pytest.mark.parametrize('text', ['0', '6', '3-1', '1,,2', 'x', '-1', '1-99'])
def test_bad_pages(text):
    with pytest.raises(ValueError):
        parse_pages(text, 5)


def test_table_omission_preserves_borders_math_rules_and_other_content(tmp_path):
    doc = parse_markdown('1\n\n| 2 | 3 |\n|---|---|\n| $\\frac{4}{5}$ | **6** |\n\n7')
    resolver = AssetResolver(builtin_numbers=True)
    flow = FlowStyle(math=MathStyle(fraction_source='geometric'))
    snap = layout_markdown(doc, resolver, flow=flow)
    assert snap.exportable, snap.diagnostics
    original, _ = prepare_export(snap, doc, flow, ExportOptions((0,)))
    filtered, scope = prepare_export(snap, doc, flow, ExportOptions((0,), table_contents=False))
    table = next(n for n in doc.nodes if n.kind == 'table')
    cell_occurrences = {o.occurrence_id for n in table.walk() for o in n.occurrences}
    assert len(filtered.pages[0].strokes) < len(original.pages[0].strokes)
    assert all(s.occurrence_id not in cell_occurrences for s in filtered.pages[0].strokes)
    assert [s for s in filtered.pages[0].strokes if ':border:' in s.occurrence_id]
    assert not [s for s in filtered.pages[0].strokes if ':math-rule:' in s.occurrence_id]
    assert scope['omitted_table_strokes']
    assert original.pages[0].strokes == prepare_export(snap, doc, flow, ExportOptions((0,)))[0].pages[0].strokes
    export_plan(filtered, tmp_path/'filtered', export_scope=scope, page_indices=(0,))


def test_selection_scaling_markers_and_original_page_filenames(tmp_path):
    doc = parse_markdown('1\n\n2')
    flow = FlowStyle()
    snap = layout_markdown(doc, AssetResolver(builtin_numbers=True), flow=flow)
    snap = replace(snap, pages=tuple(replace(snap.pages[0], index=i) for i in range(3)))
    source = snap.pages[0].paint_ops
    options = ExportOptions((0, 2), scale_x=1.02, scale_y=.98, registration=True)
    plan, scope = prepare_export(snap, doc, flow, options)
    marks = [s for s in plan.pages[0].strokes if s.execution_domain == 'registration']
    assert len(marks) == 2
    _, (a, b, c, d) = content_frames(snap, flow, 0)[0]
    assert marks[0].points[0] == (a * 1.02, b * .98)
    assert marks[1].points[-1] == (c * 1.02, d * .98)
    for old, new in zip(source, plan.pages[0].strokes, strict=False):
        assert new.points == tuple((x * 1.02, y * .98) for x, y in old.points)
        assert new.width_mm == old.width_mm
    assert snap.pages[0].paint_ops == source
    assert plan.pages[0].width_mm == snap.page_profile.width_mm * 1.02
    assert plan.pages[0].height_mm == snap.page_profile.height_mm * .98
    assert plan.pages[1].width_mm == snap.page_profile.width_mm
    svg = ElementTree.fromstring(page_svg(plan.pages[0]))
    assert svg.attrib['width'] == f'{plan.pages[0].width_mm:.6f}mm'
    assert svg.attrib['height'] == f'{plan.pages[0].height_mm:.6f}mm'
    assert svg.attrib['viewBox'] == f'0 0 {plan.pages[0].width_mm:.6f} {plan.pages[0].height_mm:.6f}'
    export_plan(plan, tmp_path/'selected', export_scope=scope, page_indices=options.pages)
    assert sorted(p.name for p in (tmp_path/'selected').glob('*.svg')) == ['page-001.svg', 'page-003.svg']
    manifest = json.loads((tmp_path/'selected/plotter.json').read_text())
    assert manifest['export_scope']['page_numbers'] == [1, 3]
    assert manifest['export_scope']['source_snapshot_id'] == snap.snapshot_id
    assert len(manifest['export_scope']['registration_marks']) == 4
    scale = manifest['export_scope']['coordinate_scale']
    assert scale['canvas_policy'] == 'scale-with-coordinates-v1' and scale['pen_width_unchanged']
    assert [c['page_number'] for c in scale['canvases']] == [1, 3]
    assert scale['canvases'][0]['output_size_mm'] == [plan.pages[0].width_mm, plan.pages[0].height_mm]
    assert '1.020000' not in page_svg(plan.pages[1])  # Unselected page is never transformed.


def test_paper_edge_registration_and_output_dimension_limit():
    doc = parse_markdown('1')
    snap = layout_markdown(doc, AssetResolver(builtin_numbers=True), page=PageProfile(margin_mm=0))
    plan, _ = prepare_export(snap, doc, FlowStyle(), ExportOptions((0,), registration=True))
    assert plan.pages[0].strokes[-2].points[0] == (0, 0)
    with pytest.raises(ValueError, match='dimensions'):
        prepare_export(snap, doc, FlowStyle(), ExportOptions((0,), scale_y=10, registration=True))


def _snapshot_with_ink(points, width=.3):
    doc = parse_markdown('1')
    snap = layout_markdown(doc, AssetResolver(builtin_numbers=True),
                           page=PageProfile(width_mm=195, height_mm=270, margin_mm=0))
    op = PaintOp('scale-regression', points, width)
    return doc, replace(snap, pages=(replace(snap.pages[0], paint_ops=(op,)),))


def test_132293_percent_preserves_valid_original_ink_beyond_old_canvas():
    doc, snap = _snapshot_with_ink(((15, 205), (15, 208)))
    base, _ = prepare_export(snap, doc, FlowStyle(), ExportOptions((0,)))
    plan, _ = prepare_export(snap, doc, FlowStyle(), ExportOptions((0,), scale_x=1.32293, scale_y=1.32293))
    page = plan.pages[0]
    assert page.strokes[0].points[-1][1] > base.pages[0].height_mm
    assert (page.width_mm, page.height_mm) == (195 * 1.32293, 270 * 1.32293)
    assert page.strokes[0].width_mm == .3
    assert base.pages[0].strokes[0].points == snap.pages[0].paint_ops[0].points
    unchanged, _ = prepare_export(snap, doc, FlowStyle(), ExportOptions((0,)))
    assert page_svg(unchanged.pages[0]) == page_svg(base.pages[0])


@pytest.mark.parametrize('options', [ExportOptions((0,), scale_x=.5, scale_y=.5),
                                    ExportOptions((0,), table_contents=False)])
def test_original_out_of_bounds_is_rejected_before_scaling_or_filtering(options):
    doc, snap = _snapshot_with_ink(((190, 260), (196, 271)))
    with pytest.raises(ValueError, match='bounds'):
        prepare_export(snap, doc, FlowStyle(), options)


def test_unselected_original_invalid_page_is_still_rejected():
    doc, snap = _snapshot_with_ink(((15, 205), (15, 208)))
    bad = replace(snap.pages[0], index=1, paint_ops=(PaintOp('bad', ((195, 10), (196, 10)), .3),))
    snap = replace(snap, pages=(*snap.pages, bad))
    with pytest.raises(ValueError, match='bounds'):
        prepare_export(snap, doc, FlowStyle(), ExportOptions((0,), scale_x=.5))


def test_shrinking_still_checks_fixed_pen_radius_against_new_canvas():
    doc, snap = _snapshot_with_ink(((.15, 10), (.15, 11)))
    prepare_export(snap, doc, FlowStyle(), ExportOptions((0,)))
    with pytest.raises(ValueError, match='bounds'):
        prepare_export(snap, doc, FlowStyle(), ExportOptions((0,), scale_x=.1))


def test_empty_output_page_canvas_is_also_scaled():
    doc, snap = _snapshot_with_ink(((15, 205), (15, 208)))
    snap = replace(snap, pages=(replace(snap.pages[0], paint_ops=()),))
    plan, scope = prepare_export(snap, doc, FlowStyle(), ExportOptions((0,), scale_x=2, scale_y=1.5))
    assert not plan.pages[0].strokes
    assert scope['coordinate_scale']['canvases'][0]['output_size_mm'] == [390, 405]
