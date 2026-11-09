"""Packaged application checks in isolated workspaces."""

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from inkstruct.application import InkStructWindow
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.fonts import APP_VERSION
from inkstruct.fonts.core import FontPackage
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import (
    can_export_with_image_omission,
    plan_from_snapshot,
    reference_image_export_scope,
)
from inkstruct.plotter.export import export_plan


def verify_background_export(editor, out, wait):
    from dataclasses import replace

    from inkstruct.editor.export_job import ExportJob
    from inkstruct.plotter.options import ExportOptions, prepare_export

    editor.flow = replace(editor.flow, template=None, template_bindings=(), glyph_corrections=(),
                          images=(), image_overrides=())
    editor.page = replace(editor.page, width_mm=210, height_mm=100, margin_mm=10)
    editor.editor.setPlainText(('1234567890 ' * 6 + '\n\n') * 8 +
                              '|12|34|\n|---|---|\n|56|78|\n\n$1+2=3$\n\n![12](missing.png)')
    wait(lambda: editor.snapshot and editor.canvas.isEnabled() and not editor.worker and not editor.timer.isActive())
    snapshot = editor.snapshot
    assert can_export_with_image_omission(snapshot)
    assert len(snapshot.pages) > 1
    choices = editor.resolver.selection_records()
    options = ExportOptions(tuple(range(len(snapshot.pages))), table_contents=False,
                            scale_x=1.32293, scale_y=1.32293, registration=True)
    plan, scope = prepare_export(snapshot, editor.markdown_document, editor.flow, options)
    assert sum(len(p.strokes) for p in plan.pages) >= 512
    export_plan(plan, out/'background-serial', optimize=True, export_scope=scope, page_indices=options.pages)
    old_configure, old_choose = editor.configure_svg_export, QtWidgets.QFileDialog.getSaveFileName
    old_confirm, old_warnings = editor.confirm_image_omissions, editor.show_font_warnings
    original_init = ExportJob.__init__
    class Unavailable:
        def Pipe(self):
            raise OSError('packaged fallback acceptance')
    reports = []
    try:
        editor.configure_svg_export = lambda s: (options, True)
        editor.confirm_image_omissions = lambda s: True
        editor.show_font_warnings = lambda: True
        editor.build_cache.routes.clear()
        for name in ('parallel', 'cached', 'cancelled', 'fallback'):
            output = out/('background-'+name)
            QtWidgets.QFileDialog.getSaveFileName = lambda *a, output=output: (str(output), '')
            if name == 'fallback':
                editor.build_cache.routes.clear()
                def fail_spawn(self, *a, **kw):
                    original_init(self, *a, **kw)
                    self.router.context = Unavailable()
                ExportJob.__init__ = fail_spawn
            editor.export_machine()
            ExportJob.__init__ = original_init
            job = editor.export_job
            assert job is not None
            if name == 'cancelled':
                job.control.cancel()
            wait(lambda: editor.export_job is None)
            result = editor.last_export_result
            assert not result['error'], result
            reports.append({'case': name, **result})
            if name == 'cancelled':
                assert result['cancelled'] and not output.exists()
            else:
                assert {p.name: p.read_bytes() for p in output.iterdir()} == {
                    p.name: p.read_bytes() for p in (out/'background-serial').iterdir()}
            if name == 'parallel':
                assert result['routing']['workers'] > 1 and result['routing']['fallback'] is None
            if name == 'cached':
                assert result['routing']['workers'] == 0 and result['routing']['cache_hits'] == len(plan.pages)
            if name == 'fallback':
                assert 'packaged fallback acceptance' in result['routing']['fallback']
        assert choices == editor.resolver.selection_records() and editor.snapshot is snapshot
    finally:
        ExportJob.__init__ = original_init
        editor.configure_svg_export, QtWidgets.QFileDialog.getSaveFileName = old_configure, old_choose
        editor.confirm_image_omissions, editor.show_font_warnings = old_confirm, old_warnings
    (out/'background-export-results.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), 'utf-8')
    return {'real_font': True, 'same_frozen_snapshot': True, 'all_export_settings_exact': True,
            'parallel_cache_cancel_verified': True, 'results': reports}


def verify_math_digits(editor, out, wait):
    from dataclasses import replace

    from inkstruct.math.handwritten import measure_math
    from inkstruct.math.style import MathStyle
    from inkstruct.renderers.pages import page_svg

    editor.flow = replace(editor.flow, template=None, template_bindings=(), glyph_corrections=(),
                          math=MathStyle.handwriting(), images=(), image_overrides=())
    editor.editor.setPlainText(
        '$$\n1111\\quad 11.1111\\quad 1.1\\times10^{-11}\n$$\n\n'
        '$$\n\\frac{1111}{11}\\qquad\\sqrt{11.1}\\qquad1:4:16\n$$\n\n'
        '|1111|11.1111|\n|---|---|\n|11|1.11|')
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    snapshot = editor.snapshot
    assert snapshot.plotter_exportable, snapshot.diagnostics
    document = editor.parse_current_source()
    boxes = [measure_math(n.math, editor.resolver, owner=n.node_id, style=editor.flow.math)
             for root in document.nodes for n in root.walk() if n.math]
    choices = editor.resolver.selection_records()
    widths = []
    for box in boxes:
        for g in box.glyphs:
            if g.occurrence.text == '1':
                l, _, r, _ = g.glyph.layout_bounds
                old = (r-l+.08)*g.em_mm+editor.style.stroke_width_mm
                assert g.advance_mm >= .315*g.em_mm-1e-9
                assert abs((g.origin_offset_mm+g.glyph.layout_bounds[0]*g.em_mm)
                           - (editor.style.stroke_width_mm/2+.04*g.em_mm+(g.advance_mm-old)/2)) < 1e-8
                widths.append({'em_mm': g.em_mm, 'before_mm': old, 'after_mm': g.advance_mm})
    assert widths and any(w['after_mm']>w['before_mm']+1e-8 for w in widths)
    # Table and body geometry are independent from the formula spacing policy.
    other = layout_markdown(document, editor.resolver, page=editor.page, style=editor.style,
                            flow=replace(editor.flow, math=MathStyle()))
    table_ids = {n.node_id for root in document.nodes for n in root.walk() if n.kind == 'table'}
    table_spans = [n.span for root in document.nodes for n in root.walk() if n.node_id in table_ids]
    in_table = lambda f: any(s.start <= f.span.start and f.span.end <= s.end for s in table_spans)
    a = [f for f in snapshot.fragments if in_table(f)]
    b = [f for f in other.fragments if in_table(f)]
    # Earlier formulas can change y; table's relative layout and bearings cannot.
    assert a and len(a) == len(b)
    assert [(f.text, f.advance_mm, f.glyph_em_mm, f.glyph_origin_offset_mm) for f in a] == [
        (f.text, f.advance_mm, f.glyph_em_mm, f.glyph_origin_offset_mm) for f in b]
    path = out/'math-digits.inkdoc'
    save_package(path, editor.source_session, editor.resolver, editor.page, editor.style,
                 flow=editor.flow, optimize=True)
    loaded = load_package(path)
    reopened = layout_markdown(parse_markdown(loaded.session), loaded.resolver,
                               page=loaded.page, style=loaded.style, flow=loaded.flow)
    assert loaded.resolver.selection_records() == choices
    assert [page_svg(reopened,i) for i in range(len(reopened.pages))] == [
        page_svg(snapshot,i) for i in range(len(snapshot.pages))]
    export_plan(plan_from_snapshot(reopened), out/'math-digits-svg', optimize=True)
    wait(lambda: editor.canvas.viewport_ready(), 30)
    editor.grab().save(str(out/'math-digits.png'))
    return {'real_font': True, 'digit_floor_verified': True, 'glyph_size_unchanged': True,
            'table_profile_unchanged': True, 'frozen_choices_exact': True,
            'reopen_svg_exact': True, 'one_widths': widths}


def verify_compact_math(editor, out, wait):
    from dataclasses import replace

    from inkstruct.math.handwritten import measure_math
    from inkstruct.math.style import MathStyle
    from inkstruct.renderers.pages import page_svg

    formulas = (
        r'\sigma_2=\frac{1}{4}\rho g\bar h\left(\bar h+\frac{\bar d}{6}\right)',
        r'\frac{997.044\times9.79338\times0.000983}{4}\left(0.024074+\frac{0.000983}{6}\right)',
        r'u_{\mathrm{A部分}}(\sigma_1)=\sigma_1\sqrt{\left(\frac{0.21587}{32.24}\right)^2+\left(\frac{42.4061}{205.4\times10^9}\right)^2}=0.00159\ \mathrm{N/m}',
    )
    old_style = MathStyle(radical_source='sample', delimiter_source='sample')
    editor.flow = replace(editor.flow, template=None, template_bindings=(), glyph_corrections=(),
                          math=old_style, images=(), image_overrides=())
    editor.editor.setPlainText('\n\n'.join('$$\n'+f+'\n$$' for f in formulas))
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    document = editor.parse_current_source()
    nodes = [n for root in document.nodes for n in root.walk() if n.math]
    old = [measure_math(n.math, editor.resolver, owner=n.node_id, style=old_style) for n in nodes]
    assert all(b.ready for b in old), [b.diagnostics for b in old]
    choices = editor.resolver.selection_records()
    wait(lambda: editor.canvas.viewport_ready(), 30)
    editor.grab().save(str(out/'math-before.png'))
    new_style = MathStyle.handwriting()
    editor.flow = replace(editor.flow, math=new_style)
    editor.schedule_layout()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    new = [measure_math(n.math, editor.resolver, owner=n.node_id, style=new_style) for n in nodes]
    assert all(b.ready for b in new), [b.diagnostics for b in new]
    assert editor.snapshot.plotter_exportable, editor.snapshot.diagnostics
    assert choices == editor.resolver.selection_records()
    for a, b in zip(old, new, strict=True):
        assert b.width < a.width and b.ascent+b.descent < a.ascent+a.descent
        assert [(g.glyph, g.em_mm) for g in a.glyphs] == [(g.glyph, g.em_mm) for g in b.glyphs]
        structural = [r for r in b.rules if any(role in r.occurrence_id
                      for role in ('fraction', 'radical', 'delimiter'))]
        assert structural and all(r.asset_id and r.sample_id and r.transform for r in structural)
    path = out/'compact-math.inkdoc'
    save_package(path, editor.source_session, editor.resolver, editor.page, editor.style,
                 flow=editor.flow, optimize=True)
    loaded = load_package(path)
    reopened = layout_markdown(parse_markdown(loaded.session), loaded.resolver,
                               page=loaded.page, style=loaded.style, flow=loaded.flow)
    assert loaded.flow.math == new_style and loaded.session.atom_ids == editor.source_session.atom_ids
    assert loaded.resolver.selection_records() == choices
    assert [page_svg(reopened,i) for i in range(len(reopened.pages))] == [
        page_svg(editor.snapshot,i) for i in range(len(editor.snapshot.pages))]
    export_plan(plan_from_snapshot(reopened), out/'compact-math-svg', optimize=True)
    wait(lambda: editor.canvas.viewport_ready(), 30)
    editor.grab().save(str(out/'math-after.png'))
    return {'real_font': True, 'frozen_choices_exact': True, 'glyphs_and_scales_unchanged': True,
            'recorded_structures': True, 'reopen_svg_exact': True,
            'formula_dimensions_mm': [{'old_width': a.width, 'new_width': b.width,
                'old_height': a.ascent+a.descent, 'new_height': b.ascent+b.descent}
                for a,b in zip(old,new,strict=True)]}


def verify_punctuation_spacing(editor, out, wait):
    """Real font punctuation spacing, frozen samples and route-only optimization."""
    from dataclasses import replace

    from inkstruct.plotter.export import route_page
    from inkstruct.renderers.pages import page_svg

    editor.flow = replace(editor.flow, template=None, template_bindings=(),
                          glyph_corrections=(), punctuation_spacing="capture")
    editor.editor.setPlainText("123，456。123（456）ABC,DEF.(ABC)")
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    old = editor.snapshot
    assert old.exportable, old.diagnostics
    choices = editor.resolver.selection_records()
    editor.flow = replace(editor.flow, punctuation_spacing="handwriting")
    editor.schedule_layout()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    new = editor.snapshot
    assert new.exportable, new.diagnostics
    assert choices == editor.resolver.selection_records()
    old_width = sum(f.advance_mm for f in old.fragments)
    new_width = sum(f.advance_mm for f in new.fragments)
    assert new_width < old_width
    editor.optimize.setChecked(True)
    path = out/'punctuation-spacing.inkdoc'
    save_package(path, editor.source_session, editor.resolver, editor.page, editor.style,
                 flow=editor.flow, optimize=editor.optimize.isChecked())
    loaded = load_package(path)
    assert loaded.optimize and loaded.flow.schema_version in {'inkstruct_flow_style_v4', 'inkstruct_flow_style_v5'}
    reopened = layout_markdown(parse_markdown(loaded.session), loaded.resolver,
                               page=loaded.page, style=loaded.style, flow=loaded.flow)
    assert loaded.resolver.selection_records() == choices
    assert page_svg(reopened, 0) == page_svg(new, 0)
    plan = plan_from_snapshot(reopened)
    routed = [route_page(page, optimize=True) for page in plan.pages]
    for page, route in zip(plan.pages, routed, strict=True):
        assert route.after_mm <= route.before_mm
        assert sorted(min(s.points, s.points[::-1]) for s in page.strokes) == sorted(
            min(s.points, s.points[::-1]) for s in route.page.strokes)
    export_plan(plan, out/'punctuation-optimized-svg', optimize=True)
    editor.grab().save(str(out/'punctuation-spacing.png'))
    return {"real_font": True, "capture_width_mm": old_width, "handwriting_width_mm": new_width,
            "frozen_choices_exact": True, "reopen_svg_exact": True, "optimize_saved": True,
            "routing_preserves_geometry": True,
            "travel_before_mm": sum(r.before_mm for r in routed),
            "travel_after_mm": sum(r.after_mm for r in routed)}


def verify_letter_spacing(editor, out, wait):
    """Use real recorded Latin samples and the exact packaged sidebar."""
    from dataclasses import replace

    from inkstruct.renderers.pages import page_svg

    editor.flow = replace(editor.flow, template=None, template_bindings=(),
                          glyph_corrections=(), latin_spacing="capture")
    editor.editor.setPlainText("minimum William iii ill WWW")
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    old = editor.snapshot
    assert old.exportable, old.diagnostics
    choices = editor.resolver.selection_records()
    editor.flow = replace(editor.flow, latin_spacing="handwriting")
    editor.schedule_layout()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    new = editor.snapshot
    assert new.exportable, new.diagnostics
    assert editor.resolver.selection_records() == choices
    old_width = sum(f.advance_mm for f in old.fragments)
    new_width = sum(f.advance_mm for f in new.fragments)
    assert new_width < old_width
    inspector = editor.glyph_inspector
    editor.select_fragment(new.fragments[4])
    inspector.scope.setCurrentIndex(inspector.scope.findData('occurrence'))
    assert len(inspector.preview.context) == 7
    before = page_svg(new, 0)
    inspector.controls['dy_em'].setValue(5)
    groups = inspector.preview.drawing_groups()
    assert sum(color == '#245cec' for _, color in groups) == 1
    assert sum(color == '#374151' for _, color in groups) == 6
    expected = next(strokes for strokes, color in groups if color == '#245cec')
    inspector.apply()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    fragment = inspector.fragment
    actual = tuple(op.points for op in editor.snapshot.pages[0].paint_ops
                   if op.occurrence_id == fragment.occurrence_id)
    assert expected == actual
    editor.grab().save(str(out/'letter-context.png'))
    path = out/'latin-spacing.inkdoc'
    save_package(path, editor.source_session, editor.resolver, editor.page, editor.style, flow=editor.flow)
    loaded = load_package(path)
    reopened = layout_markdown(parse_markdown(loaded.session), loaded.resolver, page=loaded.page,
                               style=loaded.style, flow=loaded.flow)
    assert page_svg(reopened, 0) == page_svg(editor.snapshot, 0)
    assert loaded.resolver.selection_records() == choices
    export_plan(plan_from_snapshot(reopened), out/'latin-spacing-svg')
    inspector.undo_button.click()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert page_svg(editor.snapshot, 0) == before
    return {"real_font": True, "capture_width_mm": old_width, "handwriting_width_mm": new_width,
            "frozen_choices_exact": True, "neighbours": 7, "preview_matches_applied": True,
            "reopen_svg_exact": True, "correction_undo_exact": True}


def verify_template_partial_preview(editor, out, wait):
    from dataclasses import replace

    from inkstruct.document.flow_template import FlowTemplate, PageLayout, TextFrame
    from inkstruct.document.template import Region
    from inkstruct.renderers.pages import page_svg

    template = FlowTemplate(kind='custom',width_mm=100,height_mm=100,
                            layouts=(PageLayout('body','body',(
                                TextFrame('body','body',Region('body',10,10,45,60),'body',1),
                            )),),loop_pages=('body',))
    editor.flow = replace(editor.flow,template=template,template_bindings=(),glyph_corrections=())
    source = '123\n\n```\n'+'2'*100+'\n```\n\n456'
    editor.editor.setPlainText(source)
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    stopped = editor.snapshot
    assert ''.join(f.text for f in stopped.fragments) == '123'
    assert not stopped.exportable and not editor.machine_export.isEnabled()
    assert '后续正文尚未排版' in editor.status.text()
    error = next(d for d in stopped.diagnostics if d.code == 'template-body-no-progress')
    assert source[error.span.start:error.span.end].startswith('```')
    choices = editor.resolver.selection_records()
    saved = out/'template-partial.inkdoc'
    save_package(saved,editor.source_session,editor.resolver,editor.page,editor.style,flow=editor.flow)
    loaded = load_package(saved)
    restored = layout_markdown(parse_markdown(loaded.session,field_blocks=True),loaded.resolver,
                               page=loaded.page,style=loaded.style,flow=loaded.flow)
    assert page_svg(stopped,0,debug=True) == page_svg(restored,0,debug=True)
    assert loaded.resolver.selection_records() == choices
    editor.grab().save(str(out/'template-partial.png'))
    return {'real_font':True,'retained_fragments':len(stopped.fragments),'blocked_export':True,
            'source_location_exact':True,'frozen_reopen_svg_exact':True}


def verify_fraction_default(editor, out, wait):
    """Real-font default minus bars keep identity, vertical shape and frozen SVG."""
    from dataclasses import replace

    from inkstruct.math.handwritten import measure_math
    from inkstruct.math.style import MathStyle
    from inkstruct.renderers.pages import page_svg

    editor.flow = replace(editor.flow, template=None, template_bindings=(), glyph_corrections=(),
                          image_overrides=(), images=(), math=MathStyle())
    editor.editor.setPlainText(r'$\frac{1}{2}$' + '\n\n' + r'$\frac{12345}{2}$')
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    snapshot = editor.snapshot
    assert snapshot.plotter_exportable, snapshot.diagnostics
    nodes = [n for root in parse_markdown(editor.source_session).nodes for n in root.walk() if n.math]
    rules = [rule for node in nodes for rule in measure_math(
        node.math, editor.resolver, owner=node.node_id, style=editor.flow.math).rules]
    assert len(rules) == 2
    glyphs = {g.asset_id: g for pool in editor.resolver.pools.values() for g in pool}
    assert all(glyphs[rule.asset_id].character == '−' for rule in rules)
    a, b = rules
    # Each fraction may freeze a different recorded minus variant. Compare each
    # bar against its own source sample, rather than forcing equal selections.
    for rule in rules:
        ys = [y for _, y in rule.points]
        original = [y for _, y in glyphs[rule.asset_id].strokes[0]]
        assert len(ys) == len(original)
        assert all(abs((y-ys[0])-(z-original[0])*editor.flow.math.em_mm) < 1e-8
                   for y, z in zip(ys, original))
    assert max(x for x, _ in b.points)-min(x for x, _ in b.points) > max(x for x, _ in a.points)-min(x for x, _ in a.points)
    warnings = editor.resolver.usage_warnings()
    editor.resolver.accept_usage_warnings()
    choices = editor.resolver.selection_records()
    saved = out/'fraction-default.inkdoc'
    save_package(saved, editor.source_session, editor.resolver, editor.page, editor.style, flow=editor.flow)
    loaded = load_package(saved)
    restored = layout_markdown(parse_markdown(loaded.session), loaded.resolver, page=loaded.page,
                              style=loaded.style, flow=loaded.flow)
    assert loaded.flow.math.fraction_source == 'sample'
    assert loaded.resolver.selection_records() == choices
    assert [page_svg(restored, i) for i in range(len(restored.pages))] == [page_svg(snapshot, i) for i in range(len(snapshot.pages))]
    export_plan(plan_from_snapshot(restored), out/'fraction-default-svg')
    editor.grab().save(str(out/'fraction-default.png'))
    return {'real_font': True, 'default_source': 'sample', 'minus_asset_ids': [r.asset_id for r in rules],
            'horizontal_stretch_only': True, 'frozen_reopen_svg_exact': True,
            'source_warning_candidates_used': len(warnings)}


def verify_image_height_and_han(editor, out, wait):
    from dataclasses import replace

    from PIL import Image

    from inkstruct.document.images import ImageStyle, RasterResource
    from inkstruct.renderers.pages import export_pages, page_svg
    from inkstruct.settings_dialog import SettingsDialog

    editor.flow = replace(editor.flow, template=None, template_bindings=(), glyph_corrections=(),
                          image=ImageStyle(height_mm=60), image_overrides=(), images=())
    source = '$$\nU_{模块}=1.00297U_{万}-0.38650\n$$\n\n$\\frac{输入}{输出}$'
    editor.editor.setPlainText(source)
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert editor.snapshot.plotter_exportable, editor.snapshot.diagnostics
    assert not any(d.code.startswith('math-') and d.severity == 'error'
                   for d in editor.snapshot.diagnostics)
    math_notices = [{'code': d.code, 'message': d.message, 'severity': d.severity}
                    for d in editor.snapshot.diagnostics]
    assert {'模', '块', '万', '输', '入', '出'} <= {f.text for f in editor.snapshot.fragments}
    warnings = editor.resolver.usage_warnings()
    editor.resolver.accept_usage_warnings()
    original = [page_svg(editor.snapshot, i) for i in range(len(editor.snapshot.pages))]
    export_plan(plan_from_snapshot(editor.snapshot), out/'han-formula-svg')
    saved = out/'han-formula.inkdoc'
    save_package(saved, editor.source_session, editor.resolver, editor.page, editor.style, flow=editor.flow)
    loaded = load_package(saved)
    frozen = loaded.resolver.selection_records()
    snapshot = layout_markdown(parse_markdown(loaded.session), loaded.resolver, page=loaded.page,
                               style=loaded.style, flow=loaded.flow)
    assert [page_svg(snapshot, i) for i in range(len(snapshot.pages))] == original
    assert loaded.resolver.selection_records() == frozen
    image_path = out/'height-reference.png'
    Image.new('RGB', (120, 60), 'white').save(image_path)
    image = RasterResource.from_file(image_path, 'height-reference.png')
    editor.flow = replace(editor.flow, images=(image,))
    editor.editor.setPlainText(source+'\n\n![](height-reference.png)')
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert editor.snapshot.exportable and not editor.snapshot.plotter_exportable
    assert editor.machine_export.isEnabled()
    scope = reference_image_export_scope(editor.snapshot)
    assert len(scope['omitted_images']) == 1
    plan = plan_from_snapshot(editor.snapshot, omit_reference_images=True)
    assert tuple(s.points for page in plan.pages for s in page.strokes) == tuple(
        op.points for page in editor.snapshot.pages for op in page.paint_ops)
    export_plan(plan, out/'han-with-image-omitted-svg', export_scope=scope)
    manifest = json.loads((out/'han-with-image-omitted-svg/plotter.json').read_text(encoding='utf-8'))
    assert manifest['export_scope'] == json.loads(json.dumps(scope))
    assert all(not any(n.tag.rsplit('}', 1)[-1] == 'image' for n in ET.parse(p).iter())
               for p in (out/'han-with-image-omitted-svg').glob('*.svg'))
    image_op = next(image for page in editor.snapshot.pages for image in page.images)
    dimensions = (image_op.bounds[2]-image_op.bounds[0], image_op.bounds[3]-image_op.bounds[1])
    assert all(abs(a-b) < 1e-8 for a, b in zip(dimensions, (120, 60))), dimensions
    export_pages(editor.snapshot, out/'height-reference-pages')
    settings = SettingsDialog(editor, category='image')
    controls = settings.pages['image'].editors[None].controls
    assert controls['width_mm'].isHidden() and controls['height_mm'].value() == 60
    settings.reject()
    editor.grab().save(str(out/'han-and-image.png'))
    return {'han_math_real_font': True, 'han_reopen_svg_exact': True, 'height_mm': 60,
            'proportional_width_mm': 120, 'default_width_hidden': True,
            'reference_images_omitted_explicitly': True, 'omission_manifest_verified': True,
            'source_warning_candidates_used': len(warnings), 'math_diagnostics_retained': math_notices}


def verify_missing_raster_export(editor, out, wait):
    """Equivalent small real-font case, not the user's original nine-page document."""
    from collections import Counter
    from dataclasses import replace

    from inkstruct.document.flow_template import FlowTemplate
    from inkstruct.document.images import ImageStyle
    from inkstruct.document.template_fit import template_fit_report
    from inkstruct.editor.template_fit import TemplateFitDialog
    from inkstruct.renderers.pages import export_pages

    names = ('直流电压校准曲线.png', '直流电流校准曲线.png', '电阻校准曲线.png', '交流电压校准曲线.png')
    source = '$U_{模块}=1.00297U_{万}$\n\n' + '\n\n'.join(f'![{i}]({name})' for i, name in enumerate(names, 1))
    editor.flow = replace(editor.flow, template=FlowTemplate(), template_bindings=(), images=(),
                          image=ImageStyle(height_mm=30), image_overrides=())
    editor.editor.setPlainText(source)
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    snapshot = editor.snapshot
    assert not snapshot.exportable and not snapshot.plotter_exportable
    assert can_export_with_image_omission(snapshot) and editor.machine_export.isEnabled()
    errors = [d for d in snapshot.diagnostics if d.severity == 'error']
    assert len(errors) == 4 and all(d.code == 'image-resource-missing' for d in errors)
    scope = reference_image_export_scope(snapshot)
    assert len(scope['omitted_images']) == 4
    assert {i['display_name'] for i in scope['omitted_images']} == set(names)
    assert all(i['reason'] == 'resource-not-loaded' and i['original_sha256'] is None for i in scope['omitted_images'])
    report = template_fit_report(editor.markdown_document, editor.flow, snapshot)
    assert report['exportable'] is False and report['severity_counts']['error'] == 4
    dialog = TemplateFitDialog(report, snapshot.diagnostics, editor, omission_exportable=True)
    assert any('可确认跳过位图导出其余内容' in label.text() for label in dialog.findChildren(QtWidgets.QLabel))
    assert dialog.issues.topLevelItemCount() == len(snapshot.diagnostics)
    dialog.reject(); dialog.deleteLater()
    (out/'missing-raster-fit-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    selected = {(s.occurrence_id, s.asset_id, s.sample_id, s.metrics_key) for s in editor.resolver.selections.values()}
    source_warnings = editor.resolver.usage_warnings()
    editor.resolver.accept_usage_warnings()
    assert selected == {(s.occurrence_id, s.asset_id, s.sample_id, s.metrics_key) for s in editor.resolver.selections.values()}
    before = editor.resolver.selection_records()
    saved = out/'missing-raster.inkdoc'
    save_package(saved, editor.source_session, editor.resolver, editor.page, editor.style, flow=editor.flow)
    loaded = load_package(saved)
    restored = layout_markdown(parse_markdown(loaded.session, field_blocks=loaded.flow.named_fields), loaded.resolver,
                               page=loaded.page, style=loaded.style, flow=loaded.flow)
    assert restored.pages == snapshot.pages and restored.diagnostics == snapshot.diagnostics
    assert before == loaded.resolver.selection_records()
    assert scope == reference_image_export_scope(restored)
    plan = plan_from_snapshot(restored, omit_reference_images=True)
    assert tuple(s.points for p in plan.pages for s in p.strokes) == tuple(op.points for p in snapshot.pages for op in p.paint_ops)
    export_plan(plan, out/'missing-raster-svg', export_scope=scope)
    export_pages(snapshot, out/'missing-raster-preview', debug=True)
    editor.grab().save(str(out/'missing-raster.png'))
    return {'equivalent_small_sample_only': True, 'missing_images': 4, 'errors_retained': True,
            'frozen_choices_exact': True, 'pages_and_captions_exact': True, 'manifest_verified': True,
            'pages': len(snapshot.pages), 'source_warnings': source_warnings,
            'warning_counts': dict(Counter(d.code for d in snapshot.diagnostics if d.severity == 'warning'))}


def verify_flow_templates(editor,out,wait):
    """Small real-font v3 flow; does not regenerate the character library."""
    from dataclasses import replace

    from inkstruct.document.flow_template import FlowTemplate, NamedField, PageLayout, TextFrame
    from inkstruct.document.template import Region
    from inkstruct.document.template_fit import template_fit_report
    from inkstruct.editor.flow_template_designer import FlowTemplateDesigner
    from inkstruct.renderers.pages import page_svg
    field=TextFrame('name-box','姓名',Region('name-box',5,5,60,20),'field',field_id='name')
    layouts=[PageLayout('cover','封面',(field,))]
    for n,width in enumerate((70,90,80,100),1):
        body=TextFrame('body','正文框 1',Region('body',5,40,width,12))
        layouts.append(PageLayout('p'+str(n),'循环布局 '+str(n),(body,field)))
    template=FlowTemplate(name='包内模板流程验收',kind='custom',width_mm=120,height_mm=120,
                          layouts=tuple(layouts),start_pages=('cover',),loop_pages=('p1','p2','p3','p4'),
                          fields=(NamedField('name','姓名',True),))
    editor.flow=replace(editor.flow,template=template,template_bindings=(),glyph_corrections=())
    editor.replace_text(':::field name\n123\n:::\n\n'+'\n\n'.join(['A 123']*6))
    wait(lambda:editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert editor.snapshot.plotter_exportable,editor.snapshot.diagnostics
    assert [p.source_layout for p in editor.snapshot.pages]==['封面','循环布局 1','循环布局 2','循环布局 3','循环布局 4','循环布局 1','循环布局 2']
    lookup={g.asset_id:g for pool in editor.resolver.pools.values() for g in pool}
    assert all(lookup[f.asset_id].provider_version=='inkfont-core-v1' for f in editor.snapshot.fragments if f.text=='A')
    original=[page_svg(editor.snapshot,i) for i in range(len(editor.snapshot.pages))]
    save_package(out/'template-flow.inkdoc',editor.source_session,editor.resolver,editor.page,editor.style,flow=editor.flow)
    saved=load_package(out/'template-flow.inkdoc')
    reopened=layout_markdown(parse_markdown(saved.session,field_blocks=True),saved.resolver,page=saved.page,style=saved.style,flow=saved.flow)
    assert [page_svg(reopened,i) for i in range(len(reopened.pages))]==original
    export_plan(plan_from_snapshot(reopened),out/'template-flow-svg')
    report=template_fit_report(editor.markdown_document,editor.flow,editor.snapshot)
    assert report['schema_version']=='inkstruct_template_fit_report_v2' and report['exportable']
    (out/'template-fit-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    designer=FlowTemplateDesigner(template,editor=editor)
    designer.show()
    QtWidgets.QApplication.processEvents()
    assert designer.configuration()==template and designer.tabs.isHidden()
    assert designer.page_tree.isVisible()
    designer.grab().save(str(out/'template-designer.png'))
    designer.reject()
    designer.deleteLater()
    from inkstruct.editor.template_content import TemplateContentDialog
    before_source=editor.source_session.source
    before_ids=editor.source_session.atom_ids
    before_choices=editor.resolver.selection_records()
    form=TemplateContentDialog(template,before_source)
    form.inputs['name'].setPlainText('321')
    assert form.configuration()==before_source.replace('123','321',1)
    assert form.source.isHidden()
    form.reject();form.deleteLater()
    assert editor.source_session.source==before_source and editor.source_session.atom_ids==before_ids
    assert editor.resolver.selection_records()==before_choices
    from inkstruct.editor.template_trial import TemplateTrialDialog
    trial=TemplateTrialDialog(template,editor)
    wait(lambda:trial.snapshot is not None)
    assert [page_svg(trial.snapshot,i) for i in range(len(trial.snapshot.pages))]==original
    trial.reject();trial.deleteLater()
    assert editor.resolver.selection_records()==before_choices
    return {'version':'inkstruct_page_template_v3','pages':len(reopened.pages),'real_font':True,
            'start_and_four_layout_loop':True,'frozen_reopen_svg_exact':True,
            'field_protocol':'inkstruct_named_fields_v1','fit_report':'inkstruct_template_fit_report_v2',
            'gui_workbench':True,'field_form_cancel_exact':True,'isolated_trial_svg_exact':True}


def verify_generation(w, out, wait, profile_path):
    """Real archived source, production engines and actual frozen spawn children."""
    import gzip

    from inkstruct.application import database_path
    from inkstruct.generation_workflow import generate_v61
    from inkstruct.samples import sha256_file
    from inkstruct.structures import StructureRepository
    widget = w.generator.centralWidget()
    profile = {'path': str(profile_path), 'sha256': sha256_file(profile_path)}
    characters = list('孔正址兄礼烧止怔歪羊群')
    # Load the actual shipped catalogue, require omission review, then exercise
    # the real complete-set task with bounded cancellation (no full-library run).
    import threading

    from inkstruct.character_sets import CharacterSets
    from inkstruct.character_sets_ui import CharacterSetsDialog
    catalog = CharacterSets()
    available = StructureRepository(database_path()).characters()
    dialog = CharacterSetsDialog(available, widget)
    dialog.checkboxes['cn-tgh-2013'].setChecked(True)
    assert not dialog.accept_button.isEnabled()
    dialog.lookup.setText('说')
    assert '說' in dialog.relationship.toPlainText() and '説' in dialog.relationship.toPlainText()
    dialog.acknowledge.setChecked(True)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.grab().save(str(out/'builtin-character-sets.png'))
    dialog.accept()
    manifest = dialog.result_manifest
    catalog.validate(manifest, available)
    assert len(manifest['source']['complete_requested']) == 8105
    stop = threading.Event()
    limited = out/'builtin-cancelled'
    def builtin_progress(value):
        widget.generation_progress.emit(value)
        # Completion is intentionally unordered. Wait for the chosen prefix's
        # commit markers, not merely any twelve results, before cancellation.
        if all((limited/'demo_writer'/f'{ord(c):04X}.json').is_file() for c in manifest['requested'][:12]):
            stop.set()
    def builtin_compute():
        result = generate_v61(limited, 'demo_writer', manifest['requested'], StructureRepository(database_path()),
            profile, builtin_progress, stop.is_set, semantic=True, workers=2, target_manifest=manifest)
        return {**result, 'writer': 'demo_writer', 'output': str(limited), 'message': '完整内置字表边界与取消验收'}
    widget.submit(builtin_compute, cancellable=True)
    wait(lambda: not widget.busy, 300)
    limited_result = json.loads((limited/'summary.json').read_text('utf-8'))
    assert limited_result['status'] == 'cancelled' and limited_result['completed_count'] >= 12
    assert limited_result['execution']['workers'] == 2 and limited_result['execution']['fallback'] is None
    assert json.loads((limited/'target-manifest.json').read_text('utf-8')) == manifest
    subset = manifest['requested'][:12]
    baseline = out/'builtin-subset-serial'
    subset_result = generate_v61(baseline, 'demo_writer', subset, StructureRepository(database_path()),
        profile, None, lambda: False, semantic=True, workers=1)
    assert subset_result['completed_count'] == len(subset)
    for c in subset:
        a = json.loads(gzip.decompress((limited/'demo_writer'/f'{ord(c):04X}.json.gz').read_bytes()))
        b = json.loads(gzip.decompress((baseline/'demo_writer'/f'{ord(c):04X}.json.gz').read_bytes()))
        assert a == b  # donor choices/geometry/pressure/times/warnings unaffected by target scope
    reports = []
    authority = None
    for workers in (1, 2, 4):
        path = out/f'generation-{workers}'
        def compute(workers=workers, path=path):
            result = generate_v61(path, 'demo_writer', characters, StructureRepository(database_path()),
                                  profile, widget.generation_progress.emit, lambda: False,
                                  semantic=True, workers=workers)
            return {**result, 'writer': 'demo_writer', 'output': str(path), 'message': '真实档案生成验收完成'}
        w.tabs.setCurrentIndex(1)
        widget.submit(compute, cancellable=True)
        wait(lambda: not widget.busy, 300)
        assert path.joinpath('summary.json').is_file(), widget.log.toPlainText()
        result = json.loads(path.joinpath('summary.json').read_text('utf-8'))
        assert result['completed_count'] == len(characters) and not result['failed_count'], result
        if workers > 1:
            assert result['execution']['workers'] > 1 and result['execution']['fallback'] is None, result
        actual = {c: json.loads(gzip.decompress((path/'demo_writer'/f'{ord(c):04X}.json.gz').read_bytes())) for c in characters}
        if authority is None:
            authority = actual
        else:
            assert actual == authority
        reports.append(result)
    # Exercise the newly reachable current-document entry without touching its
    # authoritative source, selections, flow or font preferences.
    w.editor.editor.setPlainText('孔正孔 $U_{正}=1$ [止](https://example.org/网址)')
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    source = w.editor.source_session.source
    record = w.editor.source_session.identity_record()
    assert widget.target_current_button.isEnabled()
    widget.target_current_button.click()
    wait(lambda: not widget.busy)
    assert widget.target_manifest['requested'] == list('孔正止')
    assert w.editor.source_session.source == source and w.editor.source_session.identity_record() == record
    assert widget.parallelism.count() == 4
    widget.grab().save(str(out/'generation-controls.png'))
    return {'real_profile_sha256': profile['sha256'], 'results': reports,
            'builtin_sets': {'counts': {e['id']: e['count'] for e in catalog.entries},
                'complete_requested': len(manifest['source']['complete_requested']),
                'actual_requested': len(manifest['requested']),
                'explicitly_unsupported': len(manifest['source']['unsupported_in_structure_library']),
                'bounded_cancellation': limited_result, 'subset_payloads_exact': True},
            'payloads_exact': True, 'current_document_targets': widget.target_manifest,
            'source_and_identity_unchanged': True,
            'mode': 'automated real widget handlers; not optical/native focus acceptance'}


def verify_workspace_views(window):
    from inkstruct.document.schema import SourceSpan

    editor = window.editor
    views = editor.workspace_views
    original_mode = views.mode
    frozen = editor.snapshot
    source = editor.source_session.identity_record()
    choices = editor.resolver.selection_records()
    flow, page, style = editor.flow, editor.page, editor.style
    for mode in ("source", "split", "preview"):
        views.buttons[mode].click()
        QtWidgets.QApplication.processEvents()
        assert views.mode == mode
        assert views.source_pane.isHidden() == (mode == "preview")
        assert views.preview_pane.isHidden() == (mode == "source")
        assert editor.snapshot is frozen and not editor.worker and not editor.timer.isActive()
        assert editor.source_session.identity_record() == source
        assert editor.resolver.selection_records() == choices
        assert (editor.flow, editor.page, editor.style) == (flow, page, style)
    editor.navigate_span(SourceSpan(0, 1))
    assert views.mode == "split" and editor.editor.isVisible()
    views.set_mode(original_mode)
    assert editor.element_inspector.context.objectName() == "inspector_context"
    assert editor.glyph_inspector.impact.objectName() == "inspector_scope"
    return {"three_modes": True, "same_snapshot_source_and_choices": True,
            "source_navigation_reveals_pane": True, "context_summary_available": True}


def verify_real_candidates(out, profile_path, writer):
    import gzip

    from inkstruct.application import database_path
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.editing import SourceSession
    from inkstruct.document.schema import PageProfile, StyleProfile
    from inkstruct.fonts.importer import build_font
    from inkstruct.generation_workflow import generate_v61
    from inkstruct.samples import sha256_file
    from inkstruct.structures import StructureRepository

    profile = {"path": str(profile_path), "sha256": sha256_file(profile_path)}
    characters = list("嘤喳啜哮")
    authority = None
    runs = []
    for workers in (1, 2):
        dest = out / f"candidates-{workers}"
        result = generate_v61(dest, writer, characters, StructureRepository(database_path()), profile,
                              None, lambda: False, semantic=True, workers=workers, candidate_limit=4)
        assert result["completed_count"] == len(characters) and not result["failed_count"], result
        assert result["variant_character_count"] >= 2 and result["candidate_count"] > len(characters)
        assert result["execution"]["fallback"] is None
        payloads = [json.loads(gzip.decompress((dest / writer / f"{ord(c):04X}.json.gz").read_bytes()))
                    for c in characters]
        if authority is None:
            authority = payloads
        else:
            assert authority == payloads
        runs.append(result)
    font_path = out / "multi-candidate.inkfont"
    build_font(font_path, writer=writer, name="frozen candidate acceptance", run=out / "candidates-1")
    font = FontPackage(font_path)
    verification = font.verify()
    assert verification["candidates"] == runs[0]["candidate_count"]
    resolver = AssetResolver(embedded=font.glyphs())
    multi = [c for c in characters if len(font.pools[c]) > 1]
    source = SourceSession("\n\n".join(c * 48 for c in multi[:2]))
    page, style = PageProfile(145, 95, 10), StyleProfile()
    before = layout_markdown(parse_markdown(source), resolver, page=page, style=style)
    assert before.plotter_exportable
    choices = resolver.selection_records()
    assert all(len({r["sample_id"] for r in choices if r["character"] == c}) > 1 for c in multi[:2])
    save_package(out / "multi-candidate.inkdoc", source, resolver, page, style)
    restored = load_package(out / "multi-candidate.inkdoc")
    after = layout_markdown(parse_markdown(restored.session), restored.resolver,
                            page=restored.page, style=restored.style)
    assert after == before and restored.resolver.selection_records() == choices
    for label, snapshot in (("svg-before", before), ("svg-after", after)):
        export_plan(plan_from_snapshot(snapshot), out / label)
    first = {p.name: p.read_bytes() for p in (out / "svg-before").glob("*.svg")}
    assert first and first == {p.name: p.read_bytes() for p in (out / "svg-after").glob("*.svg")}
    return {"runs": runs, "font": verification, "frozen_choices": len(choices),
            "source_profile_sha256": profile["sha256"], "same_reopened_svg": True}


def verify_large_fonts(window, out, wait, paths):
    """Exercise real large archives without regeneration or unrelated fixtures."""
    import zipfile
    from dataclasses import replace

    from inkstruct.document.schema import PageProfile, StyleProfile
    from inkstruct.fonts.core import MAX_MEMBER, MAX_TOTAL
    from inkstruct.fonts.parallel_verify import verify_font
    from inkstruct.renderers.pages import page_svg

    started = time.perf_counter()
    log = out / 'large-font-progress.jsonl'

    def emit(stage, **value):
        record = {'elapsed_s': time.perf_counter() - started, 'stage': stage, **value}
        with log.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        if sys.stdout is not None:
            print(json.dumps(record, ensure_ascii=False), flush=True)

    def digest(path):
        with Path(path).open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def svg_geometry(folder):
        keys = {'d', 'points', 'x1', 'x2', 'y1', 'y2', 'x', 'y', 'width', 'height',
                'transform', 'stroke-width'}
        return {p.name: sorted((node.tag, tuple(sorted((k, v) for k, v in node.attrib.items()
                                                      if k in keys)))
                               for node in ET.fromstring(p.read_bytes()).iter())
                for p in folder.glob('*.svg')}

    workflow = window.generator.centralWidget()
    count = workflow.candidate_limit
    assert workflow.method.currentData() == 'v62' and count.minimum() == 1 and count.maximum() == 64
    window.tabs.setCurrentIndex(1)
    for value, attempts in ((8, 32), (64, 256)):
        count.setValue(value)
        assert count.value() == value and str(attempts) in workflow.candidate_hint.text()
    workflow.busy = True
    workflow.refresh()
    assert not count.isEnabled() and count.value() == 64
    workflow.busy = False
    workflow.refresh()
    for method in ('v61', 'v4'):
        workflow.method.setCurrentIndex(workflow.method.findData(method))
        assert count.value() == 1 and not count.isEnabled()
    workflow.method.setCurrentIndex(workflow.method.findData('v62'))
    assert count.value() == 64 and count.isEnabled()
    window.generator.grab().save(str(out / 'candidate-64.png'))
    count.setValue(8)
    workflow.candidate_preferences.sync()
    emit('candidate-controls', counts=[8, 64], attempt_limits=[32, 256],
         fixed_methods=['v61', 'v4'], busy_lock=True, generation_started=False)

    checked = []
    for index, path in enumerate(paths, 1):
        before = time.perf_counter()
        original_sha = digest(path)
        font = FontPackage(path, verify_all=False)
        metadata_s = time.perf_counter() - before
        with zipfile.ZipFile(path) as archive:
            sizes = {item.filename: item.file_size for item in archive.infolist()}
        checked.append((font, {'path': str(path), 'input_sha256': original_sha,
            'metadata_load_with_input_hash_s': metadata_s, 'raw_bytes': sum(sizes.values()),
            'metadata_bytes': {name: sizes[name] for name in ('manifest.json', 'index.json', 'metrics.json', 'provenance.json')}}))
        emit('metadata', font=index, candidates=len(font.records), raw_bytes=sum(sizes.values()))
    authority = max((font for font, _ in checked), key=lambda f: len(f.records))
    subset = min((font for font, _ in checked), key=lambda f: len(f.records))
    assert authority.manifest['font_id'] == subset.manifest['font_id']
    assert authority.manifest['name'] == subset.manifest['name']
    lookup = {r['candidate_id']: r for r in authority.records}
    for record in subset.records:
        cid = record['candidate_id']
        assert lookup[cid] == record
        assert authority.metrics[cid] == subset.metrics[cid]
        assert authority.provenance[cid] == subset.provenance[cid]

    # Deliberately limited to characters present in both supplied real fonts.
    # Short symbol paragraphs avoid the unrelated repeated-punctuation boundary
    # failure retained in the capacity experiment's first fixture.
    text = '\n\n'.join([*[c * 48 for c in '嘤沐果'], 'ABC123', 'A℃B', 'A～B', 'A∶B',
        'A∗B', 'AℏB', 'A．B', 'αβγ', r'$1+2=3,\quad A\circ B,\quad\hbar$',
        r'$\alpha+\beta=\gamma$'])
    (out / 'large-font-fixture.md').write_text(text, 'utf-8')
    required = set('嘤沐果ABC123℃～∶∗ℏ．αβγ∘+=,')
    assert all(required <= set(font.pools) for font, _ in checked)
    editor = window.editor
    common_choices = common_svg = None
    results = []
    for index, (font, report) in enumerate(checked, 1):
        folder = out / f'large-font-{index}'
        folder.mkdir()
        last_progress = 0.0

        def verification_progress(message, font_index=index):
            nonlocal last_progress
            if time.perf_counter() - last_progress >= 15:
                emit('verify-progress', font=font_index, message=message)
                last_progress = time.perf_counter()

        telemetry = {}
        before = time.perf_counter()
        report['verification'] = verify_font(font, workers=4, progress=verification_progress, telemetry=telemetry)
        report['verification_s'] = time.perf_counter() - before
        report['verification_runtime'] = telemetry
        assert telemetry['workers'] == 4 and len(telemetry['worker_pids']) > 1
        emit('verified', font=index, **report['verification'], wall_s=report['verification_s'])
        editor.flow = replace(editor.flow, template=None, template_bindings=(), glyph_corrections=(),
                              images=(), image_overrides=())
        editor.page, editor.loaded_style = PageProfile(145, 95, 10), StyleProfile()
        before = time.perf_counter()
        window.use_font(font.path)
        report['use_font_sync_s'] = time.perf_counter() - before
        if editor.editor.toPlainText() != text:
            editor.editor.setPlainText(text)
        wait(lambda: editor.snapshot and any(f.text == 'α' for f in editor.snapshot.fragments)
             and not editor.worker and not editor.timer.isActive() and editor.canvas.isEnabled(), 300)
        snapshot = editor.snapshot
        assert snapshot.plotter_exportable, snapshot.diagnostics
        report['diagnostics'] = [asdict(d) for d in snapshot.diagnostics]
        (folder / 'diagnostics.json').write_text(json.dumps(report['diagnostics'], ensure_ascii=False, indent=2), 'utf-8')
        for number in dict.fromkeys((1, len(snapshot.pages))):
            editor.page_picker.setValue(number)
            wait(lambda: editor.canvas.viewport_ready(), 60)
            assert not editor.canvas._errors, editor.canvas._errors
            window.grab().save(str(folder / f'preview-page-{number}.png'))
        choices = editor.resolver.selection_records()
        report['usage_warnings'] = editor.resolver.usage_warnings()
        report['selected_candidates'] = {c: len({r['sample_id'] for r in choices if r['character'] == c}) for c in '嘤沐果'}
        selected = [(r['occurrence_id'], r['character'], r['sample_id']) for r in choices]
        if common_choices is None:
            common_choices = selected
        else:
            assert selected == common_choices
        path = folder / 'mixed.inkdoc'
        save_package(path, editor.source_session, editor.resolver, editor.page, editor.style,
                     flow=editor.flow, optimize=editor.optimize.isChecked())
        restored = load_package(path)
        reopened = layout_markdown(parse_markdown(restored.session), restored.resolver,
            page=restored.page, style=restored.style, flow=restored.flow)
        assert choices == restored.resolver.selection_records()
        assert editor.source_session.atom_ids == restored.session.atom_ids
        assert [page_svg(snapshot, i) for i in range(len(snapshot.pages))] == [
            page_svg(reopened, i) for i in range(len(reopened.pages))]
        for label, value in (('before', snapshot), ('after', reopened)):
            export_plan(plan_from_snapshot(value), folder / f'svg-{label}', optimize=restored.optimize)
        svg = {p.name: p.read_bytes() for p in (folder / 'svg-before').glob('*.svg')}
        assert svg and svg == {p.name: p.read_bytes() for p in (folder / 'svg-after').glob('*.svg')}
        geometry = svg_geometry(folder / 'svg-before')
        if common_svg is None:
            common_svg = geometry
        else:
            assert geometry == common_svg
        assert digest(font.path) == report['input_sha256']
        report.update(pages=len(snapshot.pages), frozen_choices=len(choices),
            preview_first_and_last_ready=True, save_reopen_exact=True, strict_svg_bytes_exact=True,
            source_font_sha_unchanged=True)
        results.append(report)
        emit('document-verified', font=index, pages=len(snapshot.pages), choices=len(choices),
             diagnostics=report['diagnostics'])
    return {'raw_limit': MAX_TOTAL, 'member_limit': MAX_MEMBER,
        'candidate_controls': {'counts': [8, 64], 'attempt_limits': [32, 256], 'method_lock': True,
                               'busy_lock': True, 'no_generation': True},
        'common_candidates_exact': len(subset.records), 'same_occurrence_candidate_ids': True,
        'same_svg_geometry': True, 'fonts': results, 'wall_s': time.perf_counter() - started,
        'mode': 'offscreen frozen/source check; native focus, responsiveness and tablet not certified'}


def verify_windows_style(window, app, out, font_path=None):
    from PIL import Image
    from inkstruct.document.images import RasterResource
    from inkstruct.global_defaults import GlobalDefaultsStore
    from inkstruct.settings_dialog import SettingsDialog
    from inkstruct.theme import theme_preference

    assert app.platformName() == "windows"
    assert "windows11" in {name.lower() for name in QtWidgets.QStyleFactory.keys()}
    assert app.property("inkstructDesktopStyle") == "windows11"
    assert window.collector.tabs.count() == 2 and not hasattr(window.collector, "line_widget")
    jpeg = out / "synthetic-reference.jpg"
    Image.new("RGB", (120, 60), (90, 20, 150)).save(jpeg)
    raster = RasterResource.from_file(jpeg, jpeg.name)
    assert (raster.width_px, raster.height_px) == (120, 60)
    dialog = SettingsDialog(window.editor, window.collector, window, category="body")
    dialog.show()
    spin = dialog.pages["body"].style.controls["em_mm"]
    editor = window.editor
    dialog.select("math")
    math = dialog.pages["math"]
    if font_path is not None:
        math.set_preview_resources(editor.resolver, font_path)
    matrix = math.categories.findItems("矩阵与向量", QtCore.Qt.MatchFlag.MatchExactly)[0]
    math.categories.setCurrentItem(matrix)
    math.refresh_preview()
    panes = math.print_preview, math.preview
    boxes = tuple(pane.box for pane in panes)
    assert all(box is not None and box.glyphs and box.dimensions for box in boxes)
    assert any(glyph.outline for glyph in boxes[0].glyphs)
    if font_path is not None:
        assert any(glyph.glyph for glyph in boxes[1].glyphs)
    document_before = (editor.flow, editor.style, editor.page, editor.source_session.atom_ids)
    settings = GlobalDefaultsStore.make_settings()
    defaults_before = settings.value(GlobalDefaultsStore.KEY)
    system_scheme = app.styleHints().colorScheme()
    dialog.select("appearance")
    theme = dialog.pages["appearance"].theme
    assert theme.currentData() == "system"
    reports = {}
    try:
        for scheme in (QtCore.Qt.ColorScheme.Light, QtCore.Qt.ColorScheme.Dark):
            theme.setCurrentIndex(theme.findData(scheme.name.lower()))
            assert dialog.apply(), dialog.error.text()
            assert theme_preference(settings) == scheme.name.lower()
            app.processEvents()
            surface = dialog.palette().color(QtGui.QPalette.ColorRole.Window)
            dark = scheme == QtCore.Qt.ColorScheme.Dark
            assert app.styleHints().colorScheme() == scheme
            assert (surface.lightness() < 128) == dark
            assert dialog.grab().save(str(out / f"theme-{scheme.name.lower()}.png"))
            dialog.select("math")
            app.processEvents()
            assert tuple(pane.box for pane in panes) == boxes
            for control in (math.categories, math.controls[math.active_key]):
                assert (control.palette().base().color().lightness() < 128) == dark
            canvas_colors = []
            for pane in panes:
                image = pane.grab().toImage()
                background = image.pixelColor(2, 2)
                ink = pane.palette().text().color()
                assert background == pane.palette().base().color()
                assert (background.lightness() < 128) == dark
                assert (ink.lightness() > 128) == dark
                canvas_colors.append({"background": background.name(), "ink": ink.name()})
            assert dialog.grab().save(str(out / f"formula-{scheme.name.lower()}.png"))
            dialog.select("body")
            app.processEvents()
            option = QtWidgets.QStyleOptionSpinBox()
            spin.initStyleOption(option)
            step = spin.style().subControlRect(
                QtWidgets.QStyle.ComplexControl.CC_SpinBox, option,
                QtWidgets.QStyle.SubControl.SC_SpinBoxUp, spin,
            )
            before = spin.value()
            QtTest.QTest.mouseClick(spin, QtCore.Qt.MouseButton.LeftButton, pos=step.center())
            assert not step.isEmpty() and spin.value() == before + spin.singleStep()
            spin.setValue(before)
            reports[scheme.name] = {"surface": surface.name(), "stepper": [step.width(), step.height()],
                                    "formula": canvas_colors}
            dialog.select("appearance")
        dialog.reset_current()
        assert theme.currentData() == "system"
        assert dialog.apply(), dialog.error.text()
        app.processEvents()
        assert theme_preference(settings) == "system"
        assert app.styleHints().colorScheme() == system_scheme
        assert settings.value(GlobalDefaultsStore.KEY) == defaults_before
        assert document_before == (editor.flow, editor.style, editor.page, editor.source_session.atom_ids)
        record = {
            "app_version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
            "platform": app.platformName(), "style": app.property("inkstructDesktopStyle"),
            "profile": "focused-qss" if app.styleSheet() else "native",
            "dpr": dialog.devicePixelRatio(), "schemes": reports,
            "system_scheme_restored": system_scheme.name, "formula_geometry_unchanged": True,
            "handwritten_glyphs": sum(bool(glyph.glyph) for glyph in boxes[1].glyphs),
            "jpeg_reference_imported": True,
        }
        (out / "verification.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    finally:
        dialog.reject()
        window.editor.timer.stop()
        if window.editor.cancelled:
            window.editor.cancelled.set()
        window.editor.pool.waitForDone()
        QtCore.QThreadPool.globalInstance().waitForDone()
        window.editor.dirty = False
        window.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--samples", type=Path)
    parser.add_argument('--generation-profile', type=Path)
    parser.add_argument('--candidate-check', action='store_true')
    parser.add_argument('--math-settings-check', action='store_true')
    parser.add_argument('--windows-style-check', action='store_true')
    parser.add_argument('--large-font-check', action='store_true')
    parser.add_argument('--large-font', action='append', type=Path, default=[])
    parser.add_argument("--writer", default="demo_writer")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    if args.math_settings_check and any((args.samples, args.generation_profile, args.candidate_check,
                                         args.large_font_check, args.large_font, args.export_only)):
        parser.error('--math-settings-check is separate from the other checks')
    if args.windows_style_check:
        if sys.platform != "win32" or any((args.samples, args.generation_profile,
                                           args.candidate_check, args.math_settings_check,
                                           args.large_font_check, args.large_font, args.export_only)):
            parser.error('--windows-style-check is a separate Windows-only check')
        if args.font is not None and not args.font.is_file():
            parser.error('--windows-style-check requires an existing --font when supplied')
    elif args.large_font_check:
        if (len(args.large_font) != 2 or len({p.resolve() for p in args.large_font}) != 2
                or any(not p.is_file() for p in args.large_font)):
            parser.error('--large-font-check requires two distinct existing --large-font archives')
        if args.font or args.samples or args.generation_profile or args.candidate_check or args.export_only:
            parser.error('--large-font-check is separate from the legacy font/sample/generation/export checks')
    elif args.large_font:
        parser.error('--large-font requires --large-font-check')
    elif args.math_settings_check:
        if args.font is None or not args.font.is_file():
            parser.error('--math-settings-check requires an existing --font')
    elif args.generation_profile is None and (args.font is None or args.samples is None):
        parser.error('--font and --samples are required unless --generation-profile is supplied')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    if args.large_font_check or args.math_settings_check or args.windows_style_check:
        # Recovery files must be private too, not only Qt preferences/workspace.
        os.environ['INKSTRUCT_LAYOUT_PREVIEW_HOME'] = str(out / 'private')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["InkStructCheck"])
    app.setApplicationName("InkStructCheck")
    app.setOrganizationName("InkStructCheck")
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(
        QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(out / "settings")
    )
    if args.large_font_check:
        QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,
                                QtCore.QSettings.Scope.SystemScope, str(out / 'settings-system'))
    original_settings = QtCore.QSettings

    class CheckSettings(original_settings):
        def __init__(self, *values, **kwargs):
            if len(values) >= 2 and isinstance(values[0], str) and isinstance(values[1], str):
                values = (original_settings.IniFormat, original_settings.UserScope, *values)
            super().__init__(*values, **kwargs)

    QtCore.QSettings = CheckSettings
    from handwriting_collector import config as capture_config
    original_store = capture_config.UiSettingsStore

    class CheckUiSettingsStore(original_store):
        def __init__(self, path=None):
            super().__init__(path if path is not None else out / "settings/collector-ui.json")

    capture_config.UiSettingsStore = CheckUiSettingsStore
    notices = []
    QtWidgets.QMessageBox.information = lambda *a: None
    QtWidgets.QMessageBox.warning = lambda *a: notices.append(str(a[2]))
    QtWidgets.QMessageBox.critical = lambda *a: notices.append(str(a[2]))
    w = InkStructWindow(workspace=out / "workspace")
    w.show()
    if args.windows_style_check:
        verify_windows_style(w, app, out, args.font)
        return
    assert app.styleHints().colorScheme() != QtCore.Qt.ColorScheme.Dark
    assert app.palette().color(QtGui.QPalette.Window).lightness() > 230
    assert app.palette().color(QtGui.QPalette.Base).lightness() > 230

    def wait(condition, timeout=90):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if condition():
                return
            # Release the GIL for Python-heavy import/profile worker steps.
            time.sleep(0.01)
        raise AssertionError((notices, w.editor.status.text()))

    if args.math_settings_check:
        from inkstruct.editor.math_settings import GROUPS, MathSettingsDialog
        from inkstruct.math.style import MathStyle

        dialog = MathSettingsDialog(MathStyle(), font_path=args.font)
        dialog.resize(760, 510)
        dialog.show()
        assert dialog.reference and dialog.reference.font.familyName() == 'Latin Modern Math'
        dimensions = 0
        for index, (title, _example, fields, _hint) in enumerate(GROUPS):
            dialog.categories.setCurrentRow(index)
            keys = {key for key, _label in fields}
            coverage = [set(), set()]
            for example_index in range(dialog.example_choice.count()):
                dialog.example_choice.setCurrentIndex(example_index)
                dialog.refresh_preview()
                app.processEvents()
                for pane, seen in zip((dialog.print_preview, dialog.preview), coverage, strict=True):
                    seen.update(key for key in keys if pane.annotation_marks(key))
            assert all(seen == keys for seen in coverage), (title, keys, coverage)
            wait(lambda: all(dialog.controls[key].isVisible() for key in keys), timeout=4)
            assert dialog.parameter_scroll.horizontalScrollBar().maximum() == 0, title
            dimensions += len(keys)
        dialog.reject()
        w.editor.dirty = False
        w.close()
        QtCore.QThreadPool.globalInstance().waitForDone()
        assert not notices, notices
        (out / 'verification.json').write_text(json.dumps({
            'app_version': APP_VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
            'formula_categories': len(GROUPS), 'measured_dimensions': dimensions,
            'reference_font': 'Latin Modern Math', 'executable': sys.executable,
        }, ensure_ascii=False, indent=2), 'utf-8')
        return 0

    if args.large_font_check:
        result = verify_large_fonts(w, out, wait, [p.resolve() for p in args.large_font])
        (out/'verification.json').write_text(json.dumps({'app_version': APP_VERSION,
            'large_font_check': result, 'executable': sys.executable,
            'frozen': bool(getattr(sys, 'frozen', False)), 'notices': notices}, ensure_ascii=False, indent=2), 'utf-8')
        w.editor.dirty = False
        w.close()
        QtCore.QThreadPool.globalInstance().waitForDone()
        return 0
    if args.generation_profile:
        result = (verify_real_candidates(out, args.generation_profile, args.writer) if args.candidate_check
                  else verify_generation(w, out, wait, args.generation_profile))
        (out/'verification.json').write_text(json.dumps({'app_version': APP_VERSION, 'generation': result,
            'notices': notices}, ensure_ascii=False, indent=2), 'utf-8')
        w.editor.dirty = False
        w.close()
        QtCore.QThreadPool.globalInstance().waitForDone()
        assert not notices, notices
        return 0
    if args.export_only:
        w.use_font(args.font)
        w.editor.editor.setPlainText('123')
        wait(lambda: w.editor.snapshot and w.editor.canvas.isEnabled() and
             not w.editor.worker and not w.editor.timer.isActive(), 300)
        result = verify_background_export(w.editor, out, wait)
        # Reuse the preview's actual-handler checks in the standard frozen bundle.
        # These fixtures remain private and never alter user fonts or settings.
        from inkstruct_layout_smoke import verify_new_features

        from inkstruct.document.flow_template import FlowTemplate, PageLayout, TextFrame
        from inkstruct.document.template import Region
        frames = (TextFrame('a','A',Region('a',5,5,50,44),order=1),
                  TextFrame('b','B',Region('b',65,5,50,44),order=2))
        template = FlowTemplate(kind='custom',name='Integrated check',width_mm=120,height_mm=120,
                                layouts=(PageLayout('two','Two frames',frames),),loop_pages=('two',))
        def ready(*, allow_errors=False):
            wait(lambda: w.editor.snapshot and not w.editor.timer.isActive() and not w.editor.worker
                 and w.editor.canvas.isEnabled() and w.editor.canvas.viewport_ready())
            if not allow_errors:
                assert w.editor.snapshot.plotter_exportable,w.editor.snapshot.diagnostics
            return w.editor.snapshot
        new_features = verify_new_features(w.editor,out,ready,template)
        workspace = verify_workspace_views(w)
        assert any(d.code=='asset-missing' for g in w.editor.problems_panel.groups for d in g.diagnostics)
        (out/'verification.json').write_text(json.dumps({'app_version': APP_VERSION,
            'background_export': result, 'layout_features':new_features, 'workspace_views': workspace,
            'problems_panel_grouped_missing':True,'notices': notices}, ensure_ascii=False, indent=2), 'utf-8')
        w.editor.dirty = False
        w.close()
        assert not notices, notices
        return 0

    # Capture writes a real sample/task through the GUI handlers using synthetic pen input.
    from handwriting_collector.models import TrajectoryPoint

    sw = w.collector.symbol_widget
    capture_writer = sw._capture_catalog.create_writer('自检书写者')
    sw.writer_picker.reload(capture_writer)
    sw.choose_writer(capture_writer)
    from inkstruct.symbol_task_dialog import SymbolTaskDialog
    def configure_capture():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, SymbolTaskDialog)
        dialog.select_all(False)
        dialog.groups['latin_italic'].setChecked(True)
        dialog.groups['digits'].setChecked(True)
        dialog.groups['operators'].setChecked(True)
        dialog.repeats.setValue(1)
        dialog.accept()
    QtCore.QTimer.singleShot(0, configure_capture)
    sw.example_button.click()
    assert sw.task.current_item().character == "A"
    width, height = sw.canvas.width(), sw.canvas.height()
    sw.canvas.trajectory.start_stroke(TrajectoryPoint(width * .3, height * .4, 0.4, 0))
    sw.canvas.trajectory.append_point(TrajectoryPoint(width * .45, height * .7, 0.8, 50))
    sw.canvas.trajectory_changed.emit()
    assert sw.boundary_guard.status() == 'clear'
    sw.save_current()
    paths = list((out / "workspace/capture/symbol_collection/samples").rglob("*.json"))
    assert len(paths) == 1, paths
    capture = json.loads(paths[0].read_text(encoding='utf-8'))
    assert capture["variant"]["letter_style"] == "italic"
    # A published user font must retain recorded operator axes. Numeric scripts
    # alone do not exercise the operator path that previously lost this data.
    from inkstruct.fonts.importer import build_font
    for char in '12+=':
        sw.task.cursor = next(i for i,item in enumerate(sw.task.items) if item.character == char)
        sw.canvas.trajectory.start_stroke(TrajectoryPoint(width*.3,height*.4,0.4,0))
        sw.canvas.trajectory.append_point(TrajectoryPoint(width*.45,height*.7,0.8,50))
        sw.save_current()
    math_font = out/'operator-axis.inkfont'
    build_font(math_font, writer=capture['writer_id'], name='operator axis check',
               symbols=out/'workspace/capture/symbol_collection', package_kind='user')
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.editing import SourceSession
    operator_font = FontPackage(math_font)
    axis_resolver = AssetResolver(embedded=operator_font.glyphs())
    axis_session = SourceSession('$1+2=1$')
    axis_before = layout_markdown(parse_markdown(axis_session),axis_resolver)
    assert axis_before.plotter_exportable, axis_before.diagnostics
    axis_doc = out/'operator-axis.inkdoc'
    save_package(axis_doc,axis_session,axis_resolver,w.editor.page,w.editor.style)
    axis_restored=load_package(axis_doc)
    axis_after=layout_markdown(parse_markdown(axis_restored.session),axis_restored.resolver)
    assert asdict(axis_before)==asdict(axis_after)
    export_plan(plan_from_snapshot(axis_after),out/'operator-axis-svg')
    # Both pipelines start from real captures, using the actual UI worker handlers.
    workflow = w.generator.centralWidget()
    assert workflow.method.count() == 3 and workflow.method.currentData() == "v62"
    assert not workflow.generate_button.isEnabled()
    workflow.writer.setText(args.writer)
    workflow.samples.setText(str(args.samples))
    target_text = "人物理羝羚而铜伯攣盼⺼"
    target_file = out / "generation-targets.txt"
    target_file.write_text(target_text, encoding="utf-8")
    picker = QtWidgets.QFileDialog.getOpenFileName
    try:
        QtWidgets.QFileDialog.getOpenFileName = lambda *args: (str(target_file), "")
        workflow.target_file_button.click()
        wait(lambda: not workflow.busy and workflow.target_manifest is not None)
    finally:
        QtWidgets.QFileDialog.getOpenFileName = picker
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.editing import SourceSession
    generation_reports = {}
    for method in ("v62", "v61", "v4"):
        workflow.method.setCurrentIndex(workflow.method.findData(method))
        assert workflow.generate_button.isEnabled(), workflow.log.toPlainText()
        workflow.last_generated_run = None
        print(method, "prepare and generate", flush=True)
        workflow.generate_button.click()
        wait(lambda: not workflow.busy, 300)
        assert workflow.last_generated_run, workflow.log.toPlainText()
        run = Path(workflow.last_generated_run)
        workflow.publish_button.click()
        assert w.library.publication.isVisible()
        assert w.library.run.text() == str(run)
        assert w.library.writer.text() == args.writer
        w.library.name.setText("smoke " + method)
        w.library.symbols.clear()
        w.library.kind.setCurrentIndex(w.library.kind.findData("user"))
        wait(lambda: w.library.build_button.isEnabled(), 120)
        assert w.library.build_button.isEnabled()
        w.library.build_button.click()
        wait(lambda: w.library.job is None, 120)
        assert not w.library.publication.isVisible(), w.library.progress.text()
        made = w.library.selected()
        font = FontPackage(made)
        assert font.verify()["characters"] == 11
        resolver = AssetResolver(embedded=font.glyphs())
        result = layout_markdown(parse_markdown(SourceSession(target_text)), resolver)
        assert result.plotter_exportable, result.diagnostics
        generation_reports[method] = {"run": str(run), "font": font.verify(), "layout": True,
                                      "warnings": resolver.usage_warnings()}
    # User default is independent of last selection or old settings.
    from inkstruct.desktop import main as generator
    fresh = generator(["check"], create_only=True, workspace=out/"fresh", database=None)
    assert fresh.centralWidget().method.currentData() == "v62"
    fresh.close()
    # Exercise the real library handler, including the worker-to-UI summary.
    original_picker = QtWidgets.QFileDialog.getOpenFileName
    QtWidgets.QFileDialog.getOpenFileName = lambda *a, **k: (str(args.font), '')
    try:
        w.library.import_font()
    finally:
        QtWidgets.QFileDialog.getOpenFileName = original_picker
    import_progress = []
    import_start = time.monotonic()
    assert w.library.job is not None
    w.library.job.signals.progress.connect(import_progress.append)
    wait(lambda: w.library.job is None, 300)
    import hashlib
    imported_font = w.library.selected()
    assert hashlib.sha256(imported_font.read_bytes()).digest() == hashlib.sha256(args.font.read_bytes()).digest()
    assert any('正在验证字形' in text for text in import_progress)
    assert '字体已导入' in w.library.progress.text()
    import_runtime = w.library.last_result['verification_runtime']
    assert import_runtime['workers'] > 1 and len(import_runtime['worker_pids']) > 1
    import multiprocessing
    assert not multiprocessing.active_children()
    import_seconds = time.monotonic() - import_start
    # Preview the actual full font and export frozen handwriting.
    w.use_font(args.font)
    editor = w.editor
    assert editor.optimize.isChecked()
    editor.editor.setFocus()
    QtTest.QTest.keyClicks(editor.editor, "12.34")
    assert editor.editor.toPlainText() == "12.34"
    source = "# 物理实验\n\n人生 天地 ⺼\n\n|1.20|3.40|\n|---|---|\n|0.05|12.34|\n\n$12_3^4$\n"
    app.clipboard().setText(source)
    editor.editor.selectAll()
    editor.editor.paste()
    wait(
        lambda: (
            editor.snapshot
            and editor.canvas.isEnabled()
            and not editor.timer.isActive()
            and not editor.worker
        )
    )
    assert editor.editor.toPlainText() == source
    assert editor.snapshot.plotter_exportable, editor.snapshot.diagnostics
    wait(lambda: editor.canvas.viewport_ready(), 30)
    assert not editor.canvas._errors, editor.canvas._errors
    assert editor.canvas._process.process.state() == QtCore.QProcess.ProcessState.Running
    from inkstruct.settings_dialog import SettingsDialog
    assert w.settings_button.isVisible() and not editor.settings_button.isVisible()
    assert not any(a.text() == '设置' for a in w.collector.menuBar().actions())
    unchanged = (editor.flow, editor.page, editor.style, editor.source_session.atom_ids,
                 editor.resolver.selection_records())
    dialog = SettingsDialog(editor, w.collector, w, category='capture')
    dialog.show()
    for category in dialog.items:
        dialog.select(category)
        app.processEvents()
    dialog.select('body')
    body = dialog.pages['body']
    assert not body.findChildren(QtWidgets.QToolButton)
    spin = body.style.controls['em_mm']
    original_value = spin.value()
    position = QtCore.QPointF(spin.rect().center())
    wheel = QtGui.QWheelEvent(position, QtCore.QPointF(spin.mapToGlobal(position.toPoint())),
                             QtCore.QPoint(), QtCore.QPoint(0, -120), QtCore.Qt.NoButton,
                             QtCore.Qt.NoModifier, QtCore.Qt.ScrollUpdate, False)
    app.sendEvent(spin, wheel)
    assert spin.value() == original_value
    dialog.select('math')
    dialog.resize(dialog.minimumWidth(), 650)
    app.processEvents()
    math = dialog.pages['math']
    assert math.guides.isChecked() and math.preview.show_guides
    assert all(not old.isVisible() for old in math.findChildren(QtWidgets.QScrollArea, 'retired_math_scroll'))
    for index in range(math.categories.count()):
        math.categories.setCurrentRow(index)
        math.refresh_preview()
        app.processEvents()
        assert math.parameter_scroll.horizontalScrollBar().maximum() == 0
    dialog.grab().save(str(out / 'formula-settings.png'))
    assert dialog.apply(), dialog.error.text()
    assert unchanged == (editor.flow, editor.page, editor.style, editor.source_session.atom_ids,
                         editor.resolver.selection_records())
    math.categories.setCurrentRow(0)
    math.refresh_preview()
    app.processEvents()
    math.controls['em_mm'].setFocus()
    QtTest.QTest.keyClick(math.controls['em_mm'], QtCore.Qt.Key_Escape)
    app.processEvents()
    assert not dialog.isVisible() and not math.isHidden()
    dialog.show()
    app.processEvents()
    assert math.isVisible()
    dialog.reject()
    dialog.deleteLater()
    from inkstruct.global_defaults import GlobalDefaultsStore
    defaults, warning = GlobalDefaultsStore().load()
    assert warning is None and not defaults.flow.table_overrides and not defaults.flow.images
    assert not defaults.flow.image_overrides
    inspector = editor.element_inspector
    editor.properties_tabs.setCurrentIndex(0)
    w.tabs.setCurrentIndex(3)
    editor.element_properties_dock.show()
    editor.element_properties_dock.raise_()
    app.processEvents()
    assert inspector.isVisible()
    table = next(n for root in editor.markdown_document.nodes for n in root.walk() if n.kind == 'table')
    inspector.selector.setCurrentIndex(inspector.selector.findData(table.node_id))
    properties = inspector.pages['table']
    properties.custom.setChecked(True)
    properties.editors[properties.current_key].controls['width_mm'].setValue(140)
    assert inspector.apply(), inspector.error.text()
    wait(lambda: editor.snapshot and not editor.timer.isActive() and not editor.worker)
    assert editor.flow.table_for(table.node_id).width_mm == 140
    assert not GlobalDefaultsStore().load()[0].flow.table_overrides
    warnings = editor.current_font_warnings()
    assert any(x["character"] == "⺼" for x in warnings)
    editor.resolver.accept_usage_warnings()
    # Rebuild after acknowledgement so the document identity incorporates its frozen policy.
    before = layout_markdown(
        parse_markdown(editor.source_session),
        editor.resolver,
        page=editor.page,
        style=editor.style,
        flow=editor.flow,
    )
    saved = out / "mixed.inkdoc"
    save_package(
        saved, editor.source_session, editor.resolver, editor.page, editor.style, flow=editor.flow
    )
    restored = load_package(saved)
    after = layout_markdown(
        parse_markdown(restored.session),
        restored.resolver,
        page=restored.page,
        style=restored.style,
        flow=restored.flow,
    )
    assert asdict(before) == asdict(after)
    assert restored.flow.table_for(table.node_id).width_mm == 140
    assert not restored.resolver.usage_warnings(pending_only=True)
    export_plan(plan_from_snapshot(after), out / "svg", optimize=True)
    svgfiles = list((out / "svg").glob("*.svg"))
    assert svgfiles
    import re

    for file in svgfiles:
        root = ET.parse(file).getroot()
        for child in root:
            assert child.tag.endswith("path"), child.tag
            assert set(re.findall("[A-Za-z]", child.attrib["d"])) <= {"M", "L"}
    # Actual packaged glyph correction, portable reopen and derived full font.
    from inkstruct.renderers.pages import page_svg
    original_svg = [page_svg(after, i) for i in range(len(after.pages))]
    glyph_properties = editor.glyph_inspector
    selected = next(f for f in editor.snapshot.fragments if f.text == '1' and f.asset_id)
    editor.select_fragment(selected)
    assert editor.properties_tabs.currentIndex() == 1
    assert glyph_properties.isVisible() and glyph_properties.apply_button.isEnabled()
    glyph_properties.controls['dx_em'].setValue(2)
    glyph_properties.controls['scale_y'].setValue(95)
    glyph_properties.apply()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert len(editor.flow.glyph_corrections) == 1
    corrected_svg = [page_svg(editor.snapshot, i) for i in range(len(editor.snapshot.pages))]
    assert corrected_svg != original_svg and editor.snapshot.plotter_exportable
    corrected_doc = out/'glyph-corrected.inkdoc'
    save_package(corrected_doc, editor.source_session, editor.resolver, editor.page, editor.style,
                 flow=editor.flow)
    corrected = load_package(corrected_doc)
    corrected_snapshot = layout_markdown(parse_markdown(corrected.session), corrected.resolver,
        page=corrected.page, style=corrected.style, flow=corrected.flow)
    assert corrected_svg == [page_svg(corrected_snapshot, i) for i in range(len(corrected_snapshot.pages))]
    export_plan(plan_from_snapshot(corrected_snapshot), out/'glyph-corrected-svg')
    assert [glyph_properties.scope.itemData(i) for i in range(glyph_properties.scope.count())] == [
        'occurrence', 'sample', 'character']
    assert not glyph_properties.write_font.isChecked()
    glyph_properties.scope.setCurrentIndex(glyph_properties.scope.findData('character'))
    glyph_properties.write_font.setChecked(True)
    glyph_properties.start_font_job(args.font, out/'glyph-corrected.inkfont')
    assert not glyph_properties.fields.isEnabled()
    wait(lambda: glyph_properties.job is None, 300)
    assert glyph_properties.last_result, glyph_properties.message.text()
    assert glyph_properties.last_result['corrected_candidates']
    assert glyph_properties.last_result['document_applied']
    assert hashlib.sha256(args.font.read_bytes()).digest() == hashlib.sha256(imported_font.read_bytes()).digest()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert all(r.scope == 'character' for r in editor.flow.glyph_corrections)
    assert not any(r.scope == 'occurrence' for r in editor.flow.glyph_corrections)
    editor.grab().save(str(out/'glyph-correction.png'))
    glyph_properties.undo_button.click()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert editor.flow == corrected.flow
    assert [page_svg(editor.snapshot, i) for i in range(len(editor.snapshot.pages))] == corrected_svg
    glyph_properties.undo_button.click()
    wait(lambda: editor.canvas.isEnabled() and not editor.timer.isActive() and not editor.worker)
    assert not editor.flow.glyph_corrections
    assert [page_svg(editor.snapshot, i) for i in range(len(editor.snapshot.pages))] == original_svg
    punctuation_check = verify_punctuation_spacing(editor, out, wait)
    letter_spacing_check = verify_letter_spacing(editor, out, wait)
    fraction_check = verify_fraction_default(editor, out, wait)
    image_han_check = verify_image_height_and_han(editor, out, wait)
    missing_raster_check = verify_missing_raster_export(editor, out, wait)
    partial_check = verify_template_partial_preview(editor,out,wait)
    template_check=verify_flow_templates(editor,out,wait)
    compact_math_check = verify_compact_math(editor, out, wait)
    math_digits_check = verify_math_digits(editor, out, wait)
    background_export_check = verify_background_export(editor, out, wait)
    w.tabs.setCurrentIndex(3)
    app.processEvents()
    w.grab().save(str(out / "layout.png"))
    for i, label in [(0, "capture"), (1, "generate"), (2, "fonts")]:
        w.tabs.setCurrentIndex(i)
        app.processEvents()
        w.grab().save(str(out / (label + ".png")))
    report = {
        "app_version": APP_VERSION,
        "background_export": background_export_check,
        "compact_math": compact_math_check,
        "math_digits": math_digits_check,
        "fraction_default": fraction_check,
        "punctuation_spacing": punctuation_check,
        "path_optimization_default_on": True,
        "template_partial_preview": partial_check,
        "letter_spacing": letter_spacing_check,
        "image_height_and_han": image_han_check,
        "missing_raster_export": missing_raster_check,
        "template_flow_v3": template_check,
        "forced_light_theme": True,
        "font_import_exact": True,
        "font_import_progress": True,
        "parallel_font_verification": import_runtime,
        "font_import_seconds": import_seconds,
        "parameter_wheel_disabled": True,
        "body_settings_expanded": True,
        "obsolete_math_arrows_hidden": True,
        "math_guides_default_on": True,
        "embedded_settings_escape": True,
        "table_image_settings_expanded": True,
        "glyph_correction_sidebar": True,
        "glyph_correction_frozen_reopen_svg": True,
        "glyph_correction_undo_exact": True,
        "glyph_three_scopes": True,
        "glyph_batch_replaces_occurrences": True,
        "glyph_optional_font_and_document": True,
        "derived_full_font_verified": glyph_properties.last_result['verification'],
        "mode": "offscreen; native focus and physical tablet not tested",
        "tabs": [w.tabs.tabText(i) for i in range(w.tabs.count())],
        "capture_saved": True,
        "capture_letter_style": "italic",
        "capture_input": "synthetic",
        "unified_settings_gear": True,
        "settings_all_categories": True,
        "settings_noop_exact": True,
        "global_defaults_persisted": True,
        "element_properties_sidebar": True,
        "formula_settings_no_horizontal_scroll": True,
        "published_operator_font_math_axis": True,
        "operator_frozen_document_exact": True,
        "operator_formula_svg": True,
        "continuous_preview_raster_ready": True,
        "preview_companion_process": True,
        "preview_cache_within_budget": editor.canvas.preview_cache.weight <= editor.canvas.preview_cache.max_weight,
        "generation": generation_reports,
        "default_generation_method": "v62",
        "source_font": str(args.font),
        "input_and_paste": True,
        "frozen_document_exact": True,
        "source_warnings": warnings,
        "plotter_svg_paths_only_M_L": True,
        "notices": notices,
    }
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    editor.dirty = False
    editor.close()
    w.hide()
    QtCore.QThreadPool.globalInstance().waitForDone()
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
