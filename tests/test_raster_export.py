"""Explicit omission preserves layout and does not bypass actual document errors."""

import json
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
from test_images import raster
from test_math_layout import resolver

from inkstruct.document.images import RasterResource
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import Diagnostic, SourceSpan
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot, reference_image_export_scope
from inkstruct.plotter.export import export_plan
from inkstruct.renderers.pages import page_svg


def test_explicit_omission_exports_all_ink_and_auditable_images(tmp_path):
    doc = parse_markdown('1\n\n![12](plot.png)\n\n![3](plot.png)\n\n4')
    resource = RasterResource.from_file(raster(tmp_path), 'plot.png')
    snapshot = layout_markdown(doc, resolver(), flow=FlowStyle(images=(resource,)))
    before = [page_svg(snapshot, i) for i in range(len(snapshot.pages))]
    with pytest.raises(ValueError, match='Raster'):
        plan_from_snapshot(snapshot)
    scope = reference_image_export_scope(snapshot)
    assert len(scope['omitted_images']) == 2
    assert all(i['original_sha256'] == resource.original_sha256 for i in scope['omitted_images'])
    assert all('png_base64' not in i and i['span'] for i in scope['omitted_images'])
    plan = plan_from_snapshot(snapshot, omit_reference_images=True)
    assert len(plan.pages) == len(snapshot.pages)
    for page, original in zip(plan.pages, snapshot.pages):
        assert [s.points for s in page.strokes] == [op.points for op in original.paint_ops]
    export_plan(plan, tmp_path/'svg', export_scope=scope)
    manifest = json.loads((tmp_path/'svg/plotter.json').read_text(encoding='utf-8'))
    assert manifest['export_scope'] == json.loads(json.dumps(scope))
    for file in (tmp_path/'svg').glob('*.svg'):
        assert not any(n.tag.rsplit('}', 1)[-1] == 'image' for n in ET.parse(file).iter())
    assert before == [page_svg(snapshot, i) for i in range(len(snapshot.pages))]


def test_omission_never_bypasses_errors_or_makes_up_resources(tmp_path):
    snapshot = layout_markdown(parse_markdown('![1](missing.svg)'), resolver())
    with pytest.raises(ValueError, match='Unresolved'):
        plan_from_snapshot(snapshot, omit_reference_images=True)
    resource = RasterResource.from_file(raster(tmp_path), 'plot.png')
    snapshot = layout_markdown(parse_markdown('![1](plot.png)'), resolver(),
                               flow=FlowStyle(images=(resource,)))
    broken = replace(snapshot, diagnostics=snapshot.diagnostics + (
        Diagnostic('asset-missing', 'missing glyph', SourceSpan(0, 1)),))
    with pytest.raises(ValueError, match='Unresolved'):
        plan_from_snapshot(broken, omit_reference_images=True)


def test_no_images_keeps_existing_plan_exact():
    snapshot = layout_markdown(parse_markdown('123'), resolver())
    assert reference_image_export_scope(snapshot) is None
    assert plan_from_snapshot(snapshot, omit_reference_images=True) == plan_from_snapshot(snapshot)


def test_raster_omission_keeps_vector_figure_and_image_only_page(tmp_path):
    from test_line_svg import resource as vector_resource

    from inkstruct.document.images import ImageStyle

    bitmap = RasterResource.from_file(raster(tmp_path), 'plot.png')
    vector = vector_resource(tmp_path)
    snapshot = layout_markdown(parse_markdown('![](plot.png)\n\n![1](plot.svg)'), resolver(),
                               flow=FlowStyle(images=(bitmap, vector), image=ImageStyle(width_mm=30)))
    assert snapshot.exportable, snapshot.diagnostics
    figure = next(f for f in snapshot.fragments if f.status == 'image-vector')
    plan = plan_from_snapshot(snapshot, omit_reference_images=True)
    assert any(s.occurrence_id == figure.occurrence_id for p in plan.pages for s in p.strokes)
    assert len(reference_image_export_scope(snapshot)['omitted_images']) == 1
    only = layout_markdown(parse_markdown('![](plot.png)'), resolver(), flow=FlowStyle(images=(bitmap,)))
    plan = plan_from_snapshot(only, omit_reference_images=True)
    assert len(plan.pages) == 1 and not plan.pages[0].strokes
    export_plan(plan, tmp_path/'blank-with-omission', export_scope=reference_image_export_scope(only))
    assert (tmp_path/'blank-with-omission/page-001.svg').is_file()


def test_cli_omission_requires_explicit_flag_and_reports_it(tmp_path):
    from inkstruct.cli import main
    p = tmp_path/'source.md'
    p.write_text('![12](plot.png)', encoding='utf-8')
    raster(tmp_path)
    project = tmp_path/'source.inkdoc'
    assert main(['document', 'render', str(p), '--mode', 'markdown', '--save-project',
                 str(project), '--output', str(tmp_path/'reference')]) == 0
    assert main(['document', 'render', str(project), '--plotter', '--output',
                 str(tmp_path/'refused')]) == 2
    assert not (tmp_path/'refused').exists()
    assert main(['document', 'render', str(project), '--plotter', '--omit-reference-images',
                 '--output', str(tmp_path/'machine')]) == 0
    manifest = json.loads((tmp_path/'machine/plotter.json').read_text(encoding='utf-8'))
    assert len(manifest['export_scope']['omitted_images']) == 1
    assert main(['document', 'render', str(project), '--omit-reference-images', '--output',
                 str(tmp_path/'invalid')]) == 2
    assert not (tmp_path/'invalid').exists()
