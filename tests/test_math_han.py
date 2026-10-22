import pytest
from test_math_layout import resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, SourceSpan, StyleProfile
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.parser import parse_math
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan
from inkstruct.renderers.pages import page_svg


@pytest.mark.parametrize('expression', [
    'U_{模块}=U_{万}', '温度=1', r'\frac{输入}{输出}', r'\sqrt{电压}',
    r'\text{中文}+\mathrm{电压}', r'\begin{matrix}输入&输出\\电压&电流\end{matrix}',
    'U^{最大}_{最小}', '𠀀_{输入}',
])
def test_han_in_math_groups_scripts_and_structures_keeps_real_source_and_choices(tmp_path, expression):
    chars=''.join(dict.fromkeys(''.join(n.value for n in parse_math(expression).root.walk() if n.kind=='Symbol')))
    r=resolver(chars+'−')
    session=SourceSession('$'+expression+'$')
    before=layout_markdown(parse_markdown(session),r)
    assert before.plotter_exportable,before.diagnostics
    chosen=r.selection_records()
    for f in before.fragments:
        assert f.text==session.source[f.span.start:f.span.end]
    assert all(f.asset_id for f in before.fragments)
    target=tmp_path/'han.inkdoc'
    save_package(target,session,r,PageProfile(),StyleProfile())
    loaded=load_package(target)
    after=layout_markdown(parse_markdown(loaded.session),loaded.resolver,flow=loaded.flow)
    assert page_svg(before,0)==page_svg(after,0)
    assert loaded.resolver.selection_records()==chosen
    export_plan(plan_from_snapshot(after),tmp_path/'svg')


def test_non_bmp_han_scalar_offsets_and_missing_glyph_remain_actionable():
    expression='U_{模块}+𠀀'
    parsed=parse_math(expression,offset=7)
    assert parsed.valid
    for node in parsed.root.walk():
        if node.kind=='Symbol':
            assert node.value==expression[node.span.start-7:node.span.end-7]
    snapshot=layout_markdown(parse_markdown('$U_{模块}$'),resolver('U模'))
    missing=[d for d in snapshot.diagnostics if d.code=='asset-missing']
    assert missing and missing[0].span==SourceSpan(5,6)
    assert not snapshot.exportable


@pytest.mark.parametrize('source', ['U_{模块', r'\未知{模块}', 'U_{🙂}', 'U_{é}'])
def test_han_does_not_relax_other_protocol_errors(source):
    assert not parse_math(source).valid
