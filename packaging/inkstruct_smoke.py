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
    from inkstruct.editor.export_check import check_export
    from inkstruct.plotter.options import ExportOptions
    from inkstruct.plotter.parallel import ExportControl
    from inkstruct.renderers.visual_export import export_visual

    editor.flow = replace(editor.flow, template=None, template_bindings=(), glyph_corrections=(),
                          images=(), image_overrides=())
    editor.page = replace(editor.page, width_mm=210, height_mm=100, margin_mm=10)
    editor.editor.setPlainText(('1234567890 ' * 6 + '\n\n') * 8 +
                              '|12|34|\n|---|---|\n|56|78|\n\n$1+2=3$\n\n![12](missing.png)')
    wait(lambda: editor.snapshot and editor.canvas.isEnabled() and not editor.worker and not editor.timer.isActive())
    snapshot = editor.snapshot
    assert can_export_with_image_omission(snapshot)
    assert len(snapshot.pages) > 1
    # Exercise the frozen PDF backend and visual exporters inside the actual bundle.
    visual = replace(snapshot, pages=tuple(replace(p, images=()) for p in snapshot.pages[:2]),
                     diagnostics=())
    for name, pages, format in (('page.png', (0,), 'png'), ('page.svg', (1,), 'svg'),
                                ('whole-document.pdf', (0, 1), 'pdf')):
        export_visual(visual, out / name, pages, format, control=ExportControl(), progress=lambda *_: None)
    assert (out/'page.png').read_bytes().startswith(b'\x89PNG')
    assert ET.parse(out/'page.svg').getroot().tag.endswith('}svg')
    assert (out/'whole-document.pdf').read_bytes().count(b'/MediaBox') == 2
    choices = editor.resolver.selection_records()
    options = ExportOptions(tuple(range(len(snapshot.pages))), table_contents=False,
                            scale_x=1.32293, scale_y=1.32293, registration=True)
    check = check_export(snapshot, editor.markdown_document, editor.flow, options, machine=True)
    assert not check.errors and check.images and check.machine is not None
    plan, scope = check.machine.plan, check.machine.scope
    assert sum(len(p.strokes) for p in plan.pages) >= 512
    export_plan(plan, out/'background-serial', optimize=True, export_scope=scope, page_indices=check.machine.pages)
    old_configure, old_choose = editor.configure_document_export, QtWidgets.QFileDialog.getSaveFileName
    old_warnings = editor.show_font_warnings
    original_init = ExportJob.__init__
    class Unavailable:
        def Pipe(self):
            raise OSError('packaged fallback acceptance')
    reports = []
    try:
        editor.configure_document_export = lambda s: ('machine', check, check.machine, True)
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
            editor.export_document()
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
        editor.configure_document_export, QtWidgets.QFileDialog.getSaveFileName = old_configure, old_choose
        editor.show_font_warnings = old_warnings
    (out/'background-export-results.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), 'utf-8')
    return {'real_font': True, 'same_frozen_snapshot': True, 'all_export_settings_exact': True,
            'visual_exports': ['png', 'svg', 'pdf'],
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
    assert not stopped.exportable and editor.export_button.isEnabled()
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
    assert editor.export_button.isEnabled()
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
    assert can_export_with_image_omission(snapshot) and editor.export_button.isEnabled()
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
    from inkstruct.generation_parallel import WORKER_PRESETS
    assert [widget.parallelism.itemData(i) for i in range(widget.parallelism.count())] == [
        "auto", 1, *WORKER_PRESETS, "max"
    ]
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
    assert workflow.method.currentData() == 'v63' and count.minimum() == 1 and count.maximum() == 64
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


def verify_recommended_recording(window, app, out):
    from inkstruct.capture_management import CaptureCatalog
    from inkstruct.capture_task_dialog import CaptureTaskDialog
    from inkstruct.recommended_capture import recording_stages

    han = window.collector.single_widget
    assert han.new_task_button.text() == "新建任务…"
    assert han.capture_workspace.stack.currentIndex() == 0
    assert not han.findChild(QtWidgets.QPushButton, "capture_recommended_starter32")
    stages = recording_stages()
    counts = [len(stage.entries) for stage in stages.values()]
    assert counts == [32, 100, 400]
    catalog = CaptureCatalog(out / "recommended")
    char = stages["starter32"].entries[0][0]
    folder = catalog.root / "samples" / "legacy" / f"U+{ord(char):04X}"
    folder.mkdir(parents=True)
    strokes, tick = [], 0
    for stroke in han.structures.get(char).strokes:
        points = [{"x":30+150*x, "y":30+150*y, "t_ms":tick+i}
                  for i,(x,y) in enumerate(stroke.median)]
        strokes.append({"points":points})
        tick += len(points)
    (folder / "specimen.json").write_text(json.dumps({
        "schema_version":"handwriting_single_v1", "sample_id":"synthetic",
        "writer_id":"legacy", "character":char, "task":{"source":"old-list.csv"},
        "capture":{"canvas_width":220, "canvas_height":220}, "strokes":strokes,
    }), encoding="utf-8")
    owner = QtWidgets.QWidget(han)
    owner._capture_catalog, owner._capture_kind, owner.structures = catalog, "han", han.structures
    owner.writer_edit = QtWidgets.QLineEdit("legacy", owner)
    dialogs = []
    try:
        dialog = CaptureTaskDialog(owner, stage_key="starter32")
        dialogs.append(dialog)
        deadline = time.monotonic()+10
        while dialog.job is not None and time.monotonic()<deadline:
            app.processEvents()
            time.sleep(.005)
        assert dialog.job is None and dialog.start.isEnabled(), dialog.error.text()
        existing = len(dialog.entries)
        assert existing == 31
        remaining = []
        for key, count in zip(stages, [31,99,399], strict=True):
            dialog.select_stage(key)
            assert len(dialog.entries) == count
            remaining.append(count)
        owner.writer_edit.setText(catalog.create_writer("Synthetic new writer"))
        fresh_dialog = CaptureTaskDialog(owner, stage_key="starter32")
        dialogs.append(fresh_dialog)
        deadline = time.monotonic()+10
        while fresh_dialog.job is not None and time.monotonic()<deadline:
            app.processEvents()
            time.sleep(.005)
        fresh = len(fresh_dialog.entries)
        assert fresh == 32
    finally:
        for dialog in dialogs:
            dialog.dispose()
    return {"stage_counts":counts, "legacy_remaining":existing,
            "other_writer_remaining":fresh, "cumulative_remaining":remaining}


def verify_new_task_writers(window, app, out):
    from inkstruct.capture_management import CaptureCatalog
    from inkstruct.capture_task_dialog import CaptureTaskDialog

    owner = QtWidgets.QWidget(window)
    catalog = owner._capture_catalog = CaptureCatalog(out / "task-writers")
    owner._capture_kind = "symbol"
    owner.writer_edit = QtWidgets.QLineEdit(owner)
    existing = catalog.create_writer("Synthetic writer")
    dialog = CaptureTaskDialog(owner)

    def wait_until(condition):
        deadline = time.monotonic() + 10
        while not condition() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert condition(), dialog.error.text()

    try:
        dialog.show()
        wait_until(lambda: dialog.writer_picker.findData(existing) > 0)
        assert not dialog.writer and dialog.import_selection is None
        assert not any(dialog.selection.characters.values())
        dialog.selection.groups["digits"].setChecked(True)
        dialog.selection.repeats.setValue(1)
        assert dialog.counts["existing"].text() == "—" and not dialog.start.isEnabled()
        dialog.writer_picker.setText(existing)
        wait_until(dialog.start.isEnabled)
        assert len(dialog.entries) == 10
        input_dialog = QtWidgets.QInputDialog.getText
        try:
            QtWidgets.QInputDialog.getText = lambda *_: ("Created in the dialog", True)
            dialog.add_writer_button.click()
        finally:
            QtWidgets.QInputDialog.getText = input_dialog
        wait_until(dialog.start.isEnabled)
        assert dialog.writer != existing and dialog.writer == dialog.writer_picker.currentData()
        assert catalog.writers()[dialog.writer]["name"] == "Created in the dialog"
        assert len(dialog.entries) == 10 and not owner.writer_edit.text()
        dialog.sources.setCurrentIndex(1)
        assert dialog.selection.available is dialog.import_selection.available
    finally:
        dialog.reject()
        dialog.dispose()
    return {"choose_existing": True, "create_new": True, "lazy_controls": True, "shared_inventory": True}


def verify_about_page(dialog, app):
    dialog.select("about")
    app.processEvents()
    page = dialog.pages["about"]
    assert page.product.text() == "InkStruct 墨构" and page.version.text() == APP_VERSION
    assert page.qq_number.isVisible() and page.qq_number.isReadOnly()
    assert page.qq_number.text() == "1035966437"
    assert dialog.reset.isHidden() and dialog.save_button.isHidden() and dialog.copy_button.isHidden()

    opened = []
    open_url = QtGui.QDesktopServices.openUrl
    clipboard = app.clipboard()
    previous = clipboard.text()
    try:
        QtGui.QDesktopServices.openUrl = lambda url: opened.append(url.toString()) or True
        page.github.click()
        page.docs.click()
        assert opened == ["https://github.com/lixiang1haoo-glitch/InkStruct-Public",
                          "https://lixiang1haoo-glitch.github.io/InkStruct-Public/"]
        page.qq_number.setFocus()
        page.qq_number.selectAll()
        QtTest.QTest.keyClick(page.qq_number, QtCore.Qt.Key.Key_C, QtCore.Qt.KeyboardModifier.ControlModifier)
        assert page.qq_number.selectedText() == page.qq_number.text() == clipboard.text()
        page.copy_qq.click()
        assert clipboard.text() == page.qq_number.text()
    finally:
        QtGui.QDesktopServices.openUrl = open_url
        clipboard.setText(previous)
    palette = page.qq_number.palette()
    return {"version": page.version.text(), "links": opened, "qq_group": page.qq_number.text(),
            "background": palette.base().color().name(), "ink": palette.text().color().name()}


def verify_experience_resources(window, directory, wait):
    font = directory / "InkStruct 示例手写体.inkfont"
    template = directory / "双页预印教案.json"
    if not font.is_file() or not template.is_file():
        raise ValueError("体验资源目录缺少示例字体或教案模板")
    editor, library = window.editor, window.library
    templates = window.template_library
    assert not any(library.root.glob("*.inkfont")) and not templates.store.entries()
    document_before = (editor.run_path, editor.flow.template)
    original = QtWidgets.QFileDialog.getOpenFileName
    try:
        QtWidgets.QFileDialog.getOpenFileName = lambda *args: (str(font), "")
        library.import_button.click()
        assert library.job is not None
        wait(lambda: library.job is None, timeout=600)
        imported = library.last_result
        assert imported and imported["verification"]["characters"] > 0
        with Path(imported["original_path"] or imported["path"]).open("rb") as stream:
            font_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        with font.open("rb") as stream:
            assert font_hash == hashlib.file_digest(stream, "sha256").hexdigest()

        QtWidgets.QFileDialog.getOpenFileName = lambda *args: (str(template), "")
        button = next(b for b in templates.findChildren(QtWidgets.QPushButton) if b.text() == "导入模板…")
        button.click()
        wait(lambda: (templates.selected() or {}).get("managed") and templates.template is not None)
        selected = templates.template
        assert (selected.width_mm, selected.height_mm, selected.mode) == (183, 259, "preprinted")
        assert len(selected.layouts) == 2 and len(selected.fields) == 13
        assert (editor.run_path, editor.flow.template) == document_before
    finally:
        QtWidgets.QFileDialog.getOpenFileName = original
    return {"font_sha256": font_hash, "font_characters": imported["verification"]["characters"],
            "template_pages": len(selected.layouts), "template_fields": len(selected.fields),
            "template_mm": [selected.width_mm, selected.height_mm]}


def verify_capture_input(window, app):
    collector = window.collector
    han, symbol = collector.single_widget, collector.symbol_widget
    tabs = (han, symbol)
    previous_page = window.tabs.currentIndex()
    window.tabs.setCurrentIndex(0)
    collector.tabs.setCurrentWidget(han)
    app.processEvents()
    from handwriting_collector.tasks import CollectionTask, TaskRepository

    def verify_writing_actions(tab):
        def position(widget):
            return QtCore.QRect(widget.mapTo(tab, QtCore.QPoint()), widget.size())

        canvas = position(tab.canvas)
        if tab is symbol:
            canvas = canvas.intersected(position(symbol.canvas_scroll.viewport()))
        column = position(tab.findChild(QtWidgets.QWidget, "captureWritingActions"))
        assert not canvas.isEmpty() and canvas.left() - column.right() - 1 == 12, (canvas, column)
        assert [button.accessibleDescription() for button in
                (tab.undo_button, tab.clear_button, tab.skip_button, tab.save_button)] == [
                    "Ctrl+Z", "Delete", "Shift+Enter", "Enter"]

    writer = han._capture_catalog.create_writer("Synthetic input check")
    task = CollectionTask.create("Input check", "synthetic-check", writer, [("一",1,0)])
    TaskRepository(han._capture_catalog.root).save(task)
    han.choose_writer(writer)
    recent = han.capture_workspace.recent
    assert recent.headerItem().text(2) == "操作" and recent.topLevelItemCount() == 1
    resume = recent.itemWidget(recent.topLevelItem(0), 2).findChild(QtWidgets.QPushButton)
    assert resume.width() < recent.header().sectionSize(2)
    resume.click()
    assert resume.text() == "正在打开…" and not resume.isEnabled()
    deadline = time.monotonic() + 10
    while han.task is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert han.task and han.task.task_id == task.task_id
    app.processEvents()
    assert han.canvas.isVisible()
    verify_writing_actions(han)
    mouse, no_mod = QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier
    start, stop = QtCore.QPoint(60, 60), QtCore.QPoint(120, 90)

    def choose(tab, mode):
        picker = tab.input_mode_picker
        picker.setCurrentIndex(picker.findData(mode))
        picker.activated.emit(picker.currentIndex())

    assert all(tab.input_mode_picker.currentData() == "tablet" for tab in tabs)
    hint = han.findChild(QtWidgets.QFrame, "captureInputHint")
    assert hint.isHidden()
    QtTest.QTest.mouseClick(han.canvas, mouse, no_mod, start)
    assert hint.isVisible() and hint.message.text() == "收到鼠标输入"
    assert han.canvas.trajectory.point_count == 0
    hint.action.click()
    assert hint.isHidden()
    assert all(tab.input_mode_picker.currentData() == "mouse" for tab in tabs)
    persisted, error = collector.ui_settings_store.load()
    assert not error and persisted.input_mode == "mouse"
    QtTest.QTest.mousePress(han.canvas, mouse, no_mod, start)
    QtTest.QTest.mouseRelease(han.canvas, mouse, no_mod, stop)
    assert han.canvas.trajectory.input_type == "mouse" and not han.canvas.trajectory.pressure_available
    assert han.canvas.trajectory.point_count == 2
    han.canvas.clear()

    touch = QtTest.QTest.createTouchDevice(QtGui.QInputDevice.DeviceType.TouchScreen)

    def touch_stroke():
        # Address the test window even when another desktop window covers the canvas.
        target = window.windowHandle()
        QtTest.QTest.touchEvent(target, touch).press(0, han.canvas.mapTo(window, start), target).commit()
        QtTest.QTest.touchEvent(target, touch).release(0, han.canvas.mapTo(window, stop), target).commit()

    touch_stroke()
    assert hint.isVisible() and hint.message.text() == "收到触屏输入"
    assert han.canvas.trajectory.point_count == 0
    hint.action.click()
    assert hint.isHidden() and all(tab.input_mode_picker.currentData() == "finger" for tab in tabs)
    touch_stroke()
    assert han.canvas.trajectory.input_type == "finger" and not han.canvas.trajectory.pressure_available
    assert han.canvas.trajectory.point_count == 2
    han.canvas.clear()
    choose(han, "tablet")
    han.pause_task()
    collector.tabs.setCurrentWidget(symbol)
    view_task = CollectionTask.create("Canvas layout check", "synthetic-check", writer, [(".", 1, 0)])
    TaskRepository(symbol._capture_catalog.task_root("symbol")).save(view_task)
    symbol.set_task(view_task)
    app.processEvents()
    verify_writing_actions(symbol)
    symbol.pause_task()
    window.tabs.setCurrentIndex(previous_page)
    app.processEvents()
    return {"mouse": "Qt event injection", "touch": "Qt event injection", "shared_mode_saved": True,
            "mismatch_suggests_switch": True, "continue_task_background": True,
            "actions_left_of_both_canvases": True}


def verify_plotter_controls(panel, out):
    from dataclasses import replace
    from tempfile import TemporaryDirectory

    from inkstruct.editor.machine_devices import DeviceDialog
    from inkstruct.plotter.profiles import DeviceDatum, DeviceProfile, PageAlignment, PlotterProfiles

    dialog = DeviceDialog(panel, panel)
    try:
        assert not dialog.datum_register.isEnabled()
        assert not dialog.datum_recover.isEnabled()
        for pad in (dialog.nudge, panel.nudge):
            assert [pad.step.itemData(i) for i in range(pad.step.count())] == [.1,.5,1,2,5,10,20,50,100]
            assert [pad.feed.itemData(i) for i in range(7)] == [200,500,1000,2000,2500,3500,5000]
            assert not pad.step.isEditable() and not pad.feed.isEditable()
        assert not dialog.use_range.isChecked()
    finally:
        dialog.deleteLater()
    with TemporaryDirectory(dir=out) as directory:
        store = PlotterProfiles(directory)
        profile = DeviceProfile.create("Smoke fixture", "SIM")
        assert not profile.limit_area_enabled and profile.feed == 2500
        profile = replace(profile, datum=DeviceDatum.create(profile, "A4 左上角"), feed=200)
        store.save(profile)
        alignment = PageAlignment((15, 15))
        store.place(profile, "sheet", "fixture", alignment, (42., 53.), (0., 0.), alignment,
                    connection="before", datum_origin=(12., 8.), select_fixture=True)
        reloaded = PlotterProfiles(directory)
        profile, = reloaded.devices()
        assert profile.feed == 200 and not profile.limit_area_enabled
        assert reloaded.fixture_setup(profile, "sheet", alignment) == "fixture"
        record = reloaded.place(profile, "sheet", "fixture", alignment)
        assert reloaded.placed_position(profile, record, connection="after", offset=(0., 0.)) is None
        assert reloaded.placed_position(profile, record, connection="after", offset=(0., 0.),
                                        datum_origin=(-4., 2.)) == (26., 47.)


def verify_exchange_import(library, source, wait):
    original_picker = QtWidgets.QFileDialog.getOpenFileName

    def import_via_button(path):
        QtWidgets.QFileDialog.getOpenFileName = lambda *args, **kwargs: (str(path), "")
        library.import_button.click()
        assert library.job is not None
        wait(lambda: library.job is None)
        result = library.last_result
        assert result and Path(result["path"]).is_file()
        return result

    try:
        result = import_via_button(source)
        active = Path(result["path"])
        if result["migration"]:
            with Path(result["original_path"]).open("rb") as backup, source.open("rb") as supplied:
                assert hashlib.file_digest(backup, "sha256").digest() == hashlib.file_digest(supplied, "sha256").digest()
        package = FontPackage(active)
        assert package.manifest["format_version"] == 1
        assert next(package.glyphs(package.records[0]["character"])).strokes
        repeated = import_via_button(active)
        assert not repeated["migration"] and Path(repeated["path"]) == active
        local = source.with_name("synthetic-local.inkfont")
        confirmed = []
        if local.exists():
            timer = QtCore.QTimer()
            def accept_consent():
                box = QtWidgets.QApplication.activeModalWidget()
                if isinstance(box, QtWidgets.QMessageBox) and box.windowTitle() == "使用本机大容量字体？":
                    for button in box.buttons():
                        if button.text() == "继续导入":
                            confirmed.append(True)
                            button.click()
                            return
            timer.timeout.connect(accept_consent)
            timer.start(20)
            try:
                installed = import_via_button(local)
                assert installed["local_capacity"] and len(confirmed) == 1
                assert FontPackage(installed["path"]).records
            finally:
                timer.stop()
        return {"migrated": bool(result["migration"]), "candidates": len(package.records),
                "native_reimport": True, "local_import": bool(confirmed)}
    finally:
        QtWidgets.QFileDialog.getOpenFileName = original_picker


def verify_windows_style(window, app, out, wait, font_path=None):
    from types import SimpleNamespace

    from PIL import Image
    from inkstruct.document.images import RasterResource
    from inkstruct.editor.document_export_dialog import DocumentExportDialog
    from inkstruct.global_defaults import GlobalDefaultsStore
    from inkstruct.settings_dialog import SettingsDialog
    from inkstruct.theme import theme_preference

    from inkstruct.capture_management import CaptureCatalog
    from inkstruct.sample_library import SampleLibrary, export_bundle, inventory, open_bundle

    assert app.platformName() == "windows"
    assert "windows11" in {name.lower() for name in QtWidgets.QStyleFactory.keys()}
    assert app.property("inkstructDesktopStyle") == "windows11"
    export = window.editor.export_button
    assert export.text() == '导出…' and not export.icon().isNull()
    assert export.toolButtonStyle() == QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    from PySide6.QtSerialPort import QSerialPort
    machine = window.editor.machine_dock
    assert machine.windowTitle() == "写字机"
    assert machine.widget() is window.editor.machine_panel
    assert set(window.editor.tabifiedDockWidgets(machine)) == {
        window.editor.problems_dock, window.editor.element_properties_dock,
    }
    assert QSerialPort.BaudRate.Baud115200 == 115200
    exchange = verify_exchange_import(window.library, font_path, wait) if font_path else None
    verify_plotter_controls(machine.widget(), out)
    export_options = DocumentExportDialog(SimpleNamespace(pages=(None,)), None, None, 0, True, window.editor)
    assert not export_options.advanced_panel.isHidden() and not export_options.advanced_panel.isCheckable()
    export_options.purpose.setCurrentIndex(export_options.purpose.findData('pdf'))
    assert export_options.advanced_panel.isHidden()
    export_options.purpose.setCurrentIndex(export_options.purpose.findData('machine'))
    assert not export_options.advanced_panel.isHidden()
    export_options.deleteLater()
    assert window.collector.tabs.count() == 2 and not hasattr(window.collector, "line_widget")
    assert all(tab.findChild(QtWidgets.QPushButton, 'capture_sample_library')
               for tab in (window.collector.single_widget, window.collector.symbol_widget))
    capture_input = verify_capture_input(window, app)
    new_task_writers = verify_new_task_writers(window, app, out)
    recommended_recording = verify_recommended_recording(window, app, out)
    source = window.collector.single_widget._capture_catalog
    target = CaptureCatalog(out / 'sample-target')
    writer = source.create_writer('Synthetic sample writer')
    reader = target.create_writer('Synthetic receiving writer')
    folder = source.task_root('symbol') / 'samples' / writer / 'U+3002'
    folder.mkdir(parents=True)
    for number in (1, 2):
        (folder / f'source-{number}.json').write_text(
            json.dumps({'schema_version': 'inkstruct_symbol_sample_v1', 'character': '。',
                        'sample_id': f'synthetic-{number}', 'writer_id': writer,
                        'capture': {'coordinate_space': 'logical_px'},
                        'guides': {'em_px': 100 * number, 'origin_x_px': 10 * number,
                                   'baseline_y_px': 80 * number},
                        'strokes': [{'points': [{'x': 16 * number, 'y': 70 * number},
                                                {'x': 22 * number, 'y': 78 * number}]}]}), encoding='utf-8')
    library = window.sample_library
    click = window.collector.symbol_widget.findChild(QtWidgets.QPushButton, 'capture_sample_library')
    window.collector.symbol_widget.writer_picker.reload(writer)
    window.navigation_buttons[0].click()
    click.click()
    assert window.tabs.currentWidget() is library and library.writer.text() == writer
    assert library.preview_message.isVisible() and library.preview_message.text() == '正在读取样本库…'
    for _ in range(500):
        app.processEvents()
        if library.job is None:
            break
        QtTest.QTest.qWait(10)
    assert library.table.topLevelItemCount() == 1, library.status.text()
    assert not library.preview_message.isVisible()
    library.table.setCurrentItem(library.table.topLevelItem(0))
    assert library.preview.value['sample_id'] == 'synthetic-1'
    assert library.variants.count() == 2 and not library.selected_samples()
    assert library.variants.isWrapping()
    assert library.variants.resizeMode() == QtWidgets.QListView.Adjust
    assert library.variants.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff
    library.compare_button.click()
    assert library.compare_preview.value['sample_id'] == 'synthetic-2'
    first, second = library.preview, library.compare_preview
    QtTest.QTest.qWait(30)
    assert first.mapTo(library, QtCore.QPoint()).y() == second.mapTo(library, QtCore.QPoint()).y()
    original_view = first.drawing_transform()
    assert original_view == second.drawing_transform()
    ink = original_view.map(first.drawing.ink).boundingRect()
    assert ink == original_view.map(second.drawing.ink).boundingRect()
    assert 0 < ink.height() < 10 and ink.top() > first.height() / 2
    position = QtCore.QPointF(first.width() / 3, first.height() / 3)
    anchor = original_view.inverted()[0].map(position)
    wheel = QtGui.QWheelEvent(position, QtCore.QPointF(first.mapToGlobal(position.toPoint())),
                              QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.NoButton,
                              QtCore.Qt.ControlModifier, QtCore.Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(first, wheel)
    assert library.zoom_button.text() == '120%' and first.drawing_transform() == second.drawing_transform()
    assert QtCore.QLineF(first.drawing_transform().map(anchor), position).length() < 1e-7
    start, stop = QtCore.QPoint(38, 40), QtCore.QPoint(56, 45)
    QtTest.QTest.mousePress(second, QtCore.Qt.LeftButton, pos=start)
    move = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(stop),
                             QtCore.QPointF(second.mapToGlobal(stop)), QtCore.Qt.NoButton,
                             QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
    app.sendEvent(second, move)
    QtTest.QTest.mouseRelease(second, QtCore.Qt.LeftButton, pos=stop)
    assert first.drawing_transform() == second.drawing_transform()
    assert QtCore.QLineF(first.drawing_transform().map(anchor) - position, QtCore.QPointF(stop - start)).length() < 1e-7
    library.zoom_button.click()
    assert library.zoom_button.text() == '100%' and first.drawing_transform() == second.drawing_transform() == original_view
    window.navigation_buttons[3].click()
    window.navigation_buttons[window.tabs.indexOf(library)].click()
    assert window.tabs.currentWidget() is library and library.writer.text() == writer
    for _ in range(500):
        if library.job is None:
            break
        QtTest.QTest.qWait(10)
    assert library.job is None
    window.navigation_buttons[3].click()
    rows, errors = inventory(source, writer)
    assert not errors
    bundle_path = out / 'synthetic.inkcapture'
    assert export_bundle(bundle_path, writer, 'Synthetic sample writer', rows) == 2
    bundle = open_bundle(bundle_path)
    destination = SampleLibrary(target)
    assert destination.import_confirmed(bundle, reader, destination.review(bundle, reader)) == 2
    assert len(destination.review(bundle, reader).duplicates) == 2
    jpeg = out / "synthetic-reference.jpg"
    Image.new("RGB", (120, 60), (90, 20, 150)).save(jpeg)
    raster = RasterResource.from_file(jpeg, jpeg.name)
    assert (raster.width_px, raster.height_px) == (120, 60)
    editor = window.editor
    window.tabs.setCurrentWidget(editor)
    views = editor.workspace_views
    workspace_before = views.mode, views.splitter.sizes(), editor.source_session.source
    for key in ("body", "page", "more"):
        assert editor.findChild(QtWidgets.QToolButton, "document_settings_" + key) is None
    dialog = SettingsDialog(editor, window.collector, window)
    dialog.show()
    for key in ("page", "body"):
        dialog.select(key)
        app.processEvents()
        assert dialog.scope == "document" and dialog.current == key
        assert dialog.scope_info.text().startswith("当前文档")
        assert dialog.save_button.text() == "应用到当前文档" and not dialog.save_button.isEnabled()
        assert dialog.copy_button.text() == "设为新建默认…"
        assert (views.mode, views.splitter.sizes(), editor.source_session.source) == workspace_before
    dialog.select("body", scope="defaults")
    assert dialog.save_button.text() == "保存新建默认" and dialog.copy_button.isHidden()
    dialog.select("body", scope="document")
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
            about = verify_about_page(dialog, app)
            assert (QtGui.QColor(about["background"]).lightness() < 128) == dark
            assert (QtGui.QColor(about["ink"]).lightness() > 128) == dark
            reports[scheme.name] = {"surface": surface.name(), "stepper": [step.width(), step.height()],
                                    "about": about,
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
            "jpeg_reference_imported": True, "sample_library_handoff": True,
            "sample_library_capture_viewport": True,
            "sample_library_variant_wrap": True,
            "inkfont_v1": exchange,
            "layout_export_controls": True,
            "document_layout_controls": True,
            "machine_control_entry": True,
            "paper_corner_recovery": True,
            "plotter_motion_settings": True,
            "recommended_recording": recommended_recording,
            "new_task_writers": new_task_writers,
            "capture_input_modes": capture_input,
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


def verify_v631(window, out, wait):
    from inkstruct.application import database_path
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.editing import SourceSession
    from inkstruct.document.schema import PageProfile, StyleProfile
    from inkstruct.fonts.importer import build_font, generated_records
    from inkstruct.generation_history import Recording, StrokeSource
    from inkstruct.generation_workflow import GenerationWorkflow, read, write
    from inkstruct.samples import sha256_file
    from inkstruct.structures import StructureRepository
    from inkstruct.v631.engine import ENGINE_VERSION

    widget = window.generator.centralWidget()
    assert widget.method.currentData() == 'v63'
    assert [widget.method.itemData(i) for i in range(widget.method.count())] == [
        'v63', 'v62', 'v61', 'v4', 'v631',
    ]
    for method in ('v63', 'v631'):
        widget.method.setCurrentIndex(widget.method.findData(method))
        assert widget.candidate_limit.isEnabled() and widget.candidate_limit.maximum() == 64
        assert widget.same_character.isChecked() and not widget.same_character.isHidden()

    database = database_path()
    repo = StructureRepository(database)
    source = out / 'samples'
    writer = 'fixture'
    characters = '明林休'
    for character in characters:
        graph = repo.get(character)
        for variant in range(2):
            traces = [stroke.median for stroke in graph.strokes]
            if character == '明' and variant:
                traces[:2] = [tuple(traces[0]) + tuple(traces[1])]
            strokes, stamp = [], 0
            for trace in traces:
                points = []
                for i, (x, y) in enumerate(trace):
                    points.append({'x': x * 80 + 10, 'y': y * 80 + 10 + (i % 2) * variant * 1.2,
                                   'pressure': 0.45, 't_ms': stamp})
                    stamp += 20
                strokes.append({'points': points})
                stamp += 60
            sample_id = f'{ord(character):04x}-{variant}'
            write(source / f'{sample_id}.json', {'schema_version': 'handwriting_single_v1',
                  'sample_id': sample_id, 'character': character, 'writer_id': writer,
                  'capture': {'canvas_width': 100, 'canvas_height': 100}, 'strokes': strokes})

    service = GenerationWorkflow(window.workspace, database)
    legacy = service.generate(writer, source, 'v63', characters, workers=1, candidate_limit=4,
                              preparation=lambda *_: None)
    assert read(Path(legacy['output']) / 'protocol.json')['method'] == 'v6.3 exp'
    state = service.state(writer, source)
    profile = state['profiles']['v63']
    paths = [Path(path) for path in (profile['path'], profile['connected']['path'], state['import']['index'],
                                     service.state_path(writer, source))]
    hashes = {path: sha256_file(path) for path in paths}
    fresh = GenerationWorkflow(out / 'new-workspace', database)
    fresh.update_samples(writer, source, 'v631')
    fresh_profile = fresh.state(writer, source)['profiles']['v631']
    assert fresh_profile['workflow_version'] == 'desktop-connected-v63-2'
    assert fresh_profile['connected']['whole'] >= 1

    outputs = []
    score_results = []
    for workers in (1, 2):
        stages = []
        result = service.generate(writer, source, 'v631', characters, workers=workers, candidate_limit=4,
                                  source_score=True, diversity_score=True,
                                  preparation=lambda stage, _: stages.append(stage))
        assert '沿用档案' in stages and result['failed_count'] == 0
        assert result['completed_count'] == len(characters)
        folder = Path(result['output'])
        protocol = read(folder / 'protocol.json')
        assert protocol['method'] == 'v6.3.1' and protocol['version'] == ENGINE_VERSION
        assert protocol['execution']['workers'] == workers and protocol['execution']['fallback'] is None, protocol['execution']
        code = {name: digest for name, digest in protocol['code'].items() if name.startswith('v631/')}
        package = Path(getattr(sys, '_MEIPASS', repo.path.parents[2] / 'src')) / 'inkstruct/v631'
        assert code == {f'v631/{path.name}': sha256_file(path) for path in package.glob('*.py')}
        assert 'v631/engine.py' in code
        score_results.append(read(folder / "generation-scores.json"))
        outputs.append(folder)
    assert score_results[0] == score_results[1] and score_results[0]["covered_count"] == len(characters)

    def character_files(folder):
        return {path.name: sha256_file(path) for path in (folder / writer).glob('*.json*')}

    serial, parallel = outputs
    files = character_files(parallel)
    assert len(files) == 2 * len(characters) and character_files(serial) == files
    assert all(sha256_file(path) == digest for path, digest in hashes.items())
    records = [record for record, *_ in generated_records(parallel, writer)]
    assert len(records) > len(characters)
    assert any(record.get('method') == 'same_character' and record.get('segments') for record in records)
    assert any(not record.get('segments') for record in records)
    font_path = out / 'v631.inkfont'
    build_font(font_path, writer=writer, name='Synthetic v6.3.1', run=parallel)
    font = FontPackage(font_path)
    font.verify()
    assets = list(font.glyphs())
    assert {asset.font_metadata['summary']['generation_method'] for asset in assets} == {'v6.3.1'}
    session = SourceSession(characters * 2)
    resolver = AssetResolver(embedded=assets)
    layout = layout_markdown(parse_markdown(session), resolver)
    assert layout.exportable
    path = out / 'v631.inkdoc'
    save_package(path, session, resolver, PageProfile(), StyleProfile())
    saved = load_package(path)
    assert layout_markdown(parse_markdown(saved.session), saved.resolver) == layout
    assert saved.resolver.selection_records() == resolver.selection_records()
    window.tabs.setCurrentWidget(window.generator)
    widget.writer.setText(writer)
    assert widget.last_generated_run is None and widget.history_button.isEnabled()
    widget.history_button.click()
    history = widget.history_dialog
    try:
        assert history.isVisible() and not history.isModal()
        wait(lambda: len(history.visible) == 3 and bool(history.strokes))
        assert history.writers.currentData() == writer
        history.search.setText('明')
        wait(lambda: bool(history.strokes))
        assert history.current_character() == '明' and history.candidate.count() > 1
        history.search.clear()
        history.character.setCurrentIndex(history.character_model.index(history.characters.index('林')))
        wait(lambda: history.current_character() == '林' and bool(history.strokes))
        history.character.setCurrentIndex(history.character_model.index(history.characters.index('明')))
        wait(lambda: history.current_character() == '明' and bool(history.strokes))
        joined = next(i for i, item in enumerate(history.candidates) if any(len(s.slots) > 1 for s in item[1]))
        history.candidate.setCurrentIndex(joined)
        wait(lambda: any(len(stroke.slots) > 1 for stroke in history.strokes))
        row, stroke = next((i, s) for i, s in enumerate(history.strokes) if len(s.slots) > 1)
        history.stroke_table.setCurrentCell(row, 0)
        assert history.source_cards[stroke.key].preview.selected == stroke.raw_order - 1
        assert history.recordings[stroke.key].status == '原录制'
        history.copy.click()
        assert ' + '.join(stroke.slots) in QtWidgets.QApplication.clipboard().text()
        small = StrokeSource(('dot',), ((.2, .2), (.23, .23), (.24, .2)), '单笔拼接',
                             '林', 'synthetic-dot', 'synthetic-dot', raw_order=1)
        recording = Recording((((740, 110), (750, 122), (760, 110)), ((734, 80), (850, 165))),
                              '原录制', (1600, 260))
        history.show_strokes([stroke, small], {stroke.key: history.recordings[stroke.key], small.key: recording})
        QtWidgets.QApplication.processEvents()
        first, other = (history.source_cards[s.key] for s in (stroke, small))
        assert first.isVisible() and other.isVisible()
        assert other.preview.display_path(0).boundingRect().height() < other.preview.height() / 10
        box_side = min(other.preview.width(), other.preview.height())
        assert other.preview.display_path(1).boundingRect().width() > box_side / 2
        assert other.preview.paths[0].elementAt(2).isCurveTo()
        assert history.generated.paths[1].elementAt(2).isCurveTo()
        history.stroke_table.setCurrentCell(1, 0)
        assert other.button.isChecked() and other.preview.selected == 0 and not first.button.isChecked()
        rect = QtCore.QRectF(history.generated.rect())
        history.view.zoom_at(rect, history.generated.margin, rect.center(), 1)
        assert history.zoom_button.text() == '120%' and other.preview.view.zoom == history.generated.view.zoom
        history.zoom_button.click()
        assert history.view.zoom == 1 and history.zoom_button.text() == '100%'
    finally:
        history.close()
    return {'app_version': APP_VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
            'method': 'v6.3.1', 'engine': ENGINE_VERSION, 'characters': len(characters),
            'candidates': len(assets), 'implementation_hashes': code, 'workers': [1, 2], 'scoring_serial_parallel_exact': True,
            'fallback': None, 'matching_character_files': len(files), 'old_archive_reused': True,
            'fresh_archive_verified': True, 'frozen_document_reopened': True,
            'generation_history': {'batches': 3, 'nonmodal': True, 'candidate_switch': True,
                                   'connected_recording_highlight': True, 'copy_review': True,
                                   'character_list': True, 'source_grid': True, 'shared_frame_zoom': True,
                                   'wide_recording_framing': True, 'rounded_preview_paths': True}}


def verify_score_replay(batch, output):
    from inkstruct.generation_scores import evaluate
    from inkstruct.generation_workflow import read, write

    run = batch.resolve()
    protocol = read(run / "protocol.json")
    requested = read(run / "target-manifest.json")["requested"]
    expected = read(run / "generation-scores.json")
    if output.resolve().is_relative_to(run):
        raise ValueError("请在批次目录外保存复测结果")
    for preset in (1, "auto"):
        start = time.perf_counter()
        result = evaluate(run, protocol["writers"][0], requested, source="source_score" in expected,
                          diversity="diversity_score" in expected, completed=len(protocol["characters"]),
                          workers=preset)
        write(output / f"score-{preset}.json", result)
        elapsed = time.perf_counter() - start
        if result != expected:
            raise ValueError("复测评分与原批次不符")
        write(output / f"timing-{preset}.json", {"seconds": elapsed, "exact": True, "scores": result})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--samples", type=Path)
    parser.add_argument('--generation-profile', type=Path)
    parser.add_argument('--candidate-check', action='store_true')
    parser.add_argument('--math-settings-check', action='store_true')
    parser.add_argument('--windows-style-check', action='store_true')
    parser.add_argument('--v631-check', action='store_true')
    parser.add_argument('--large-font-check', action='store_true')
    parser.add_argument('--large-font', action='append', type=Path, default=[])
    parser.add_argument('--experience-resources', type=Path)
    parser.add_argument("--writer", default="demo_writer")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument('--score-replay', type=Path, help="验证既有协议批次的评分和耗时")
    args = parser.parse_args()
    if args.score_replay is not None:
        verify_score_replay(args.score_replay, args.output)
        return
    if args.math_settings_check and any((args.samples, args.generation_profile, args.candidate_check,
                                         args.large_font_check, args.large_font, args.export_only)):
        parser.error('--math-settings-check is separate from the other checks')
    if args.experience_resources is not None:
        if any((args.font, args.samples, args.generation_profile, args.candidate_check, args.math_settings_check,
                args.windows_style_check, args.v631_check, args.large_font_check, args.large_font, args.export_only)):
            parser.error('--experience-resources is a separate manual import check')
    elif args.v631_check:
        if any((args.font, args.samples, args.generation_profile, args.candidate_check, args.math_settings_check,
                args.windows_style_check, args.large_font_check, args.large_font, args.export_only)):
            parser.error('--v631-check is a separate synthetic generation check')
    elif args.windows_style_check:
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
    if (args.large_font_check or args.math_settings_check or args.windows_style_check or args.v631_check
            or args.experience_resources):
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

    def wait(condition, timeout=90):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if condition():
                return
            # Release the GIL for Python-heavy import/profile worker steps.
            time.sleep(0.01)
        raise AssertionError((notices, w.editor.status.text()))

    if args.v631_check:
        try:
            result = verify_v631(w, out, wait)
            (out / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        finally:
            w.close()
        return
    if args.windows_style_check:
        verify_windows_style(w, app, out, wait, args.font)
        return
    if args.experience_resources:
        try:
            result = verify_experience_resources(w, args.experience_resources.resolve(), wait)
            assert not notices, notices
            record = {"app_version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)), **result}
            (out / "verification.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        finally:
            w.editor.timer.stop()
            if w.editor.cancelled:
                w.editor.cancelled.set()
            w.editor.pool.waitForDone()
            QtCore.QThreadPool.globalInstance().waitForDone()
            w.editor.dirty = False
            w.close()
        return
    assert app.styleHints().colorScheme() != QtCore.Qt.ColorScheme.Dark
    assert app.palette().color(QtGui.QPalette.Window).lightness() > 230
    assert app.palette().color(QtGui.QPalette.Base).lightness() > 230

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
    sw.writer_picker.reload()
    from inkstruct.capture_task_dialog import CaptureTaskDialog
    def configure_capture():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, CaptureTaskDialog)
        assert not dialog.writer and dialog.import_selection is None
        assert not any(dialog.selection.characters.values())
        dialog.writer_picker.setText(capture_writer)
        dialog.selection.select_all(False)
        dialog.selection.groups['latin_italic'].setChecked(True)
        dialog.selection.groups['digits'].setChecked(True)
        dialog.selection.groups['operators'].setChecked(True)
        dialog.selection.repeats.setValue(1)
        deadline = time.monotonic() + 10
        while dialog.symbol_inventory is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert dialog.start.isEnabled(), dialog.error.text()
        dialog.accept()
    QtCore.QTimer.singleShot(0, configure_capture)
    sw.new_task_button.click()
    assert sw.task.writer_id == capture_writer and sw.writer_edit.text() == capture_writer
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
    assert [workflow.method.itemData(i) for i in range(workflow.method.count())] == [
        "v63", "v62", "v61", "v4", "v631"
    ]
    assert workflow.method.currentData() == "v63"
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
    imported_font = Path(w.library.last_result["original_path"] or w.library.selected())
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
