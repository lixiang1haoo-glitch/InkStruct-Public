"""Missing raster omission is a scoped capability, never a diagnostic rewrite."""

import json
from dataclasses import replace
from urllib.parse import quote

import pytest
from test_images import raster
from test_math_layout import resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.images import (
    ImageStyle,
    RasterResource,
    import_local_images,
    local_raster_reference_name,
)
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import Diagnostic, PageProfile, SourceSpan, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import (
    can_export_with_image_omission,
    plan_from_snapshot,
    reference_image_export_scope,
)
from inkstruct.plotter.export import export_plan
from inkstruct.renderers.pages import page_svg


@pytest.mark.parametrize('source,name', [
    ('直流电压校准曲线.png', '直流电压校准曲线.png'),
    (quote('交流电压校准曲线.png'), '交流电压校准曲线.png'),
    ('folder/%E4%B8%AD%E6%96%87%20%E5%9B%BE.JPEG', '中文 图.JPEG'),
    ('./sample%2ejPg', 'sample.jPg'),
    ('bad%25ZZ.png', 'bad%ZZ.png'),
])
def test_missing_supported_references_keep_errors_but_allow_explicit_export(tmp_path, source, name):
    document = parse_markdown(f'1\n\n![12](<{source}>)\n\n3')
    snapshot = layout_markdown(document, resolver())
    assert not snapshot.exportable and not snapshot.plotter_exportable
    assert can_export_with_image_omission(snapshot)
    before = page_svg(snapshot, 0, debug=True)
    diagnostics = snapshot.diagnostics
    with pytest.raises(ValueError, match='Unresolved'):
        plan_from_snapshot(snapshot)
    scope = reference_image_export_scope(snapshot)
    item, = scope['omitted_images']
    assert item['display_name'] == name and item['reason'] == 'resource-not-loaded'
    assert item['original_sha256'] is None and item['page_number'] == 1
    image, = snapshot.pages[0].images
    assert item['span'] == {'start': image.span.start, 'end': image.span.end}
    assert item['occurrence_id'] == image.occurrence_id and item['bounds'] == image.bounds
    plan = plan_from_snapshot(snapshot, omit_reference_images=True)
    assert [s.points for p in plan.pages for s in p.strokes] == [op.points for p in snapshot.pages for op in p.paint_ops]
    export_plan(plan, tmp_path/'svg', export_scope=scope)
    manifest = json.loads((tmp_path/'svg/plotter.json').read_text(encoding='utf-8'))
    assert manifest['export_scope'] == json.loads(json.dumps(scope))
    assert snapshot.diagnostics == diagnostics and before == page_svg(snapshot, 0, debug=True)


@pytest.mark.parametrize('source', [
    'missing.svg', 'missing.SVG', 'unknown.bmp', 'unknown', 'not-a-jpeg.webp',
    '../outside.png', '%2e%2e/outside.png', '/absolute.png', '//server/image.jpg',
    'https://example.com/a.png', 'file:///C:/a.png', 'C:/a.png',
    'a.png?format=svg', 'a.png#part', 'bad%FF.png', 'CON.png', 'a%00.png',
])
def test_unknown_vector_or_unsafe_missing_references_cannot_be_omitted(source):
    assert local_raster_reference_name(source) is None
    doc = parse_markdown(f'![](<{source}>)')
    snapshot = layout_markdown(doc, resolver())
    # Markdown may itself reject an unsafe URL; either way no unsafe image is waived.
    if any(p.images for p in snapshot.pages):
        assert not can_export_with_image_omission(snapshot)
        with pytest.raises(ValueError):
            plan_from_snapshot(snapshot, omit_reference_images=True)


def test_mixed_rasters_pagination_reopen_and_frozen_choices_are_exact(tmp_path):
    resource = RasterResource.from_file(raster(tmp_path), 'loaded.png')
    session = SourceSession('1\n\n![12](loaded.png)\n\n![23](电阻校准曲线.png)\n\n4')
    flow = FlowStyle(images=(resource,), image=ImageStyle(height_mm=30))
    page = PageProfile(70, 85, 5)
    rr = resolver()
    snapshot = layout_markdown(parse_markdown(session), rr, flow=flow, page=page)
    assert len(snapshot.pages) >= 2 and can_export_with_image_omission(snapshot), snapshot.diagnostics
    before = [page_svg(snapshot, i, debug=True) for i in range(len(snapshot.pages))]
    choices = rr.selection_records()
    scope = reference_image_export_scope(snapshot)
    assert [i['reason'] for i in scope['omitted_images']] == ['loaded-raster', 'resource-not-loaded']
    assert scope['omitted_images'][0]['original_sha256'] == resource.original_sha256
    path = tmp_path/'preserved.inkdoc'
    save_package(path, session, rr, page, StyleProfile(), flow=flow)
    loaded = load_package(path)
    restored = layout_markdown(parse_markdown(loaded.session), loaded.resolver, page=loaded.page, style=loaded.style, flow=loaded.flow)
    assert before == [page_svg(restored, i, debug=True) for i in range(len(restored.pages))]
    assert choices == loaded.resolver.selection_records()
    assert session.identity_record() == loaded.session.identity_record()
    assert scope == reference_image_export_scope(restored)
    assert loaded.flow.images == flow.images and restored.diagnostics == snapshot.diagnostics


@pytest.mark.parametrize('code', ['asset-missing', 'math-command-unsupported', 'ink-overflow', 'image-width-overflow', 'image-import-failed'])
def test_other_errors_and_uncorrelated_missing_errors_still_block(code):
    snapshot = layout_markdown(parse_markdown('![1](missing.png)'), resolver())
    span = snapshot.pages[0].images[0].span
    broken = replace(snapshot, diagnostics=snapshot.diagnostics + (Diagnostic(code, 'blocked', span),))
    assert not can_export_with_image_omission(broken)
    with pytest.raises(ValueError, match='Unresolved'):
        plan_from_snapshot(broken, omit_reference_images=True)
    unmatched = replace(snapshot, diagnostics=(Diagnostic('image-resource-missing', 'unknown image', SourceSpan(0, 0)),))
    assert not can_export_with_image_omission(unmatched)


def test_cli_missing_png_explicit_success_but_invalid_bytes_and_svg_still_block(tmp_path, capsys):
    from inkstruct.cli import main

    source = tmp_path/'source.md'
    source.write_text('![12](直流电压校准曲线.png)', encoding='utf-8')
    argv = ['document', 'render', str(source), '--mode', 'markdown', '--plotter']
    assert main([*argv, '--output', str(tmp_path/'refused')]) == 2
    assert not (tmp_path/'refused').exists()
    capsys.readouterr()
    assert main([*argv, '--omit-reference-images', '--output', str(tmp_path/'machine')]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['exportable'] is False and report['plotter_exportable'] is False
    assert report['kind'] == 'plotter-pages' and report['export_scope']['omitted_images'][0]['reason'] == 'resource-not-loaded'
    for name, raw in [('broken.png', b'not an image'), ('missing.svg', None)]:
        if raw is not None:
            (tmp_path/name).write_bytes(raw)
        source.write_text(f'![1]({name})', encoding='utf-8')
        assert main([*argv, '--omit-reference-images', '--output', str(tmp_path/(name+'-output'))]) == 2
        assert not (tmp_path/(name+'-output')).exists()


def test_missing_only_page_is_retained_and_invalid_import_diagnostics_are_not_waived(tmp_path):
    assert local_raster_reference_name('bad%ZZ.png') is None
    assert local_raster_reference_name('\nname.png') is None
    document = parse_markdown('![](missing.jpeg)')
    snapshot = layout_markdown(document, resolver())
    plan = plan_from_snapshot(snapshot, omit_reference_images=True)
    assert len(plan.pages) == 1 and not plan.pages[0].strokes
    export_plan(plan, tmp_path/'blank', export_scope=reference_image_export_scope(snapshot))
    assert (tmp_path/'blank/page-001.svg').exists()
    (tmp_path/'bad.png').write_bytes(b'invalid image bytes')
    document = parse_markdown('![](bad.png)')
    flow, issues = import_local_images(document, FlowStyle(), tmp_path)
    assert any(d.code == 'image-import-failed' for d in issues)
    snapshot = layout_markdown(replace(document, diagnostics=document.diagnostics + issues), resolver(), flow=flow)
    assert not can_export_with_image_omission(snapshot)


def test_template_report_keeps_missing_image_errors_and_exact_geometry():
    from test_template_fields import setup

    from inkstruct.document.template_fit import template_fit_report

    _, doc, rr, flow = setup('![1](missing.png)\n\n2')
    flow = replace(flow, image=ImageStyle(width_mm=20))
    snapshot = layout_markdown(doc, rr, flow=flow)
    assert not snapshot.exportable and can_export_with_image_omission(snapshot), snapshot.diagnostics
    before = template_fit_report(doc, flow, snapshot)
    plan = plan_from_snapshot(snapshot, omit_reference_images=True)
    assert before == template_fit_report(doc, flow, snapshot)
    assert before['severity_counts']['error'] >= 1 and before['exportable'] is False
    assert any(d['code'] == 'image-resource-missing' and d['severity'] == 'error' for d in before['diagnostics'])
    assert [s.points for p in plan.pages for s in p.strokes] == [op.points for p in snapshot.pages for op in p.paint_ops]
