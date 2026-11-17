"""Forced exports omit invalid ink explicitly, without mutating frozen geometry."""
import json
from dataclasses import asdict, replace

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import Diagnostic, SourceSpan
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan
from inkstruct.plotter.forced import force_plan
from inkstruct.plotter.options import ExportOptions, prepare_export
from inkstruct.plotter.svg import page_svg
from inkstruct.scene.schema import PaintOp


def snapshot(source="1汉2"):
    resolver=AssetResolver(builtin_numbers=True)
    document=parse_markdown(source)
    result=layout_markdown(document,resolver)
    return document,resolver,result


def test_force_keeps_real_paths_leaves_missing_blank_and_writes_issue_files(tmp_path):
    doc,resolver,source=snapshot()
    before=asdict(source);choices=resolver.selection_records()
    assert not source.exportable
    with pytest.raises(ValueError):plan_from_snapshot(source)
    plan,scope=prepare_export(source,doc,None,ExportOptions((0,),force=True))
    valid={f.occurrence_id for f in source.fragments if f.asset_id}
    assert plan.pages[0].strokes
    assert {s.occurrence_id for s in plan.pages[0].strokes}<=valid
    assert scope['forced'] and not scope['complete_document'] and scope['omitted_strokes']
    export_plan(plan,tmp_path/'forced',export_scope=scope)
    report=json.loads((tmp_path/'forced/issues.json').read_text(encoding='utf-8'))
    assert any(d['code']=='asset-missing' for d in report['diagnostics'])
    assert '仅导出可用笔迹' in (tmp_path/'forced/issues.txt').read_text(encoding='utf-8')
    assert json.loads((tmp_path/'forced/plotter.json').read_text(encoding='utf-8'))['export_scope']['forced']
    svg=(tmp_path/'forced/page-001.svg').read_text()
    assert '<path' in svg and '#dc2626' not in svg and '<text' not in svg
    assert asdict(source)==before and resolver.selection_records()==choices
    assert not source.exportable
    with pytest.raises(FileExistsError):export_plan(plan,tmp_path/'forced',export_scope=scope)


@pytest.mark.parametrize('source',[r'1 $\unknown{2}$ 3','1\n\n![2](missing.png)\n\n3'])
def test_partial_math_and_missing_images_keep_available_ink_and_do_not_emit_placeholders(source):
    doc,_resolver,result=snapshot(source)
    plan,scope=prepare_export(result,doc,None,ExportOptions(tuple(range(len(result.pages))),force=True))
    assert any(page.strokes for page in plan.pages)
    assert scope['diagnostics']
    assert '#dc2626' not in ''.join(page_svg(p) for p in plan.pages)
    if 'missing.png' in source:assert len(scope['omitted_images'])==1


@pytest.mark.parametrize('bad',[((-1,1),(2,2)),((1,1),),((1,1),(1,1)),((float('nan'),1),(2,2))])
def test_force_skips_bad_strokes_but_preserves_valid_strokes(bad):
    _,_,base=snapshot('12')
    page=base.pages[0]
    invalid=PaintOp('invalid',bad,.3)
    error=Diagnostic('line-width-overflow','fixture',SourceSpan(0,1))
    result=replace(base,pages=(replace(page,paint_ops=(*page.paint_ops,invalid)),),diagnostics=(error,))
    plan,scope=force_plan(result)
    assert [s.points for s in plan.pages[0].strokes]==[op.points for op in page.paint_ops]
    assert any(o['occurrence_id']=='invalid' for o in scope['omitted_strokes'])


def test_content_area_error_does_not_discard_valid_ink_within_physical_page():
    _,_,base=snapshot('12')
    broken=replace(base,diagnostics=(Diagnostic('ink-overflow','Outside content margin',SourceSpan(0,1)),))
    plan,scope=force_plan(broken)
    assert plan.pages==plan_from_snapshot(base).pages
    assert scope['diagnostics'][0]['code']=='ink-overflow'


def test_invalid_after_scale_is_reported_instead_of_clipped():
    doc,_,base=snapshot('12')
    op=PaintOp('edge',((.15,1),(.15,2)),.3)
    source=replace(base,pages=(replace(base.pages[0],paint_ops=(op,)),))
    plan,scope=prepare_export(source,doc,None,ExportOptions((0,),scale_x=.1,scale_y=.1,force=True))
    assert not plan.pages[0].strokes
    assert scope['omitted_strokes'][0]['reason']=='scaled-stroke-outside-physical-page'


def test_forced_table_filter_and_selected_pages_are_still_honoured():
    doc,_,base=snapshot('|1|2|\n|---|---|\n|汉|3|\n\n4\\newpage5')
    plan,scope=prepare_export(base,doc,None,ExportOptions((0,),table_contents=False,force=True))
    assert scope['page_numbers']==[1] and scope['omitted_table_strokes']
    assert all(o['page_index']==0 for o in scope['omitted_strokes'])
    cell_ids={o.occurrence_id for n in doc.nodes[0].walk() for o in n.occurrences}
    assert not any(s.occurrence_id in cell_ids for s in plan.pages[0].strokes)
    assert any(s.source_stroke_id is None for s in plan.pages[0].strokes)


def test_force_option_is_typed_and_regular_export_remains_strict():
    with pytest.raises(ValueError):ExportOptions((0,),force='yes')
    doc,_,base=snapshot()
    with pytest.raises(ValueError):prepare_export(base,doc,None,ExportOptions((0,)))


def test_force_can_export_the_retained_prefix_of_a_stopped_template_flow():
    from test_break_commands import multi_frame

    from inkstruct.document.styles import FlowStyle
    source="1\n\n$$\n"+"1"*100+"\n$$\n\n2"
    document=parse_markdown(source,field_blocks=True)
    snapshot=layout_markdown(document,AssetResolver(builtin_numbers=True),flow=FlowStyle(template=multi_frame()))
    assert any(d.code=='template-body-no-progress' for d in snapshot.diagnostics)
    plan,scope=force_plan(snapshot)
    assert any(p.strokes for p in plan.pages)
    assert any(d['code']=='template-body-no-progress' for d in scope['diagnostics'])
