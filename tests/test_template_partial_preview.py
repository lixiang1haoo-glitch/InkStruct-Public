"""A blocked object retains placed content without claiming a complete layout."""


import pytest
from test_flow_templates import codes, frame, render, template

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import PageLayout
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.renderers.pages import page_svg


@pytest.mark.parametrize('object_source', [r'$\frac{12345678901234567890}{1}$',
                                         '```\n12345678901234567890\n```',
                                         '|12345678901234567890|\n|---|\n|1|'])
def test_blocked_objects_keep_prefix_and_stop_at_source(object_source, tmp_path):
    t = template(layouts=(PageLayout('p1', 'p1', (frame(w=35, h=40),)),))
    # Geometric fraction is explicit here so this test isolates region progress.
    flow = FlowStyle(template=t, math=MathStyle(fraction_source='geometric'))
    source = SourceSession('123\n\n' + object_source + '\n\n987')
    r = AssetResolver(builtin_numbers=True)
    result = render(source, t, resolver=r, flow=flow)
    assert 'template-body-no-progress' in codes(result)
    assert ''.join(f.text for f in result.fragments) == '123'
    assert result.pages[0].paint_ops and len(result.pages) == 1
    error = next(d for d in result.diagnostics if d.code == 'template-body-no-progress')
    assert source.source[error.span.start:error.span.end].strip() == object_source
    assert '后续正文尚未排版' in error.message
    with pytest.raises(ValueError):
        plan_from_snapshot(result)
    choices = r.selection_records()
    path = tmp_path/'stopped.inkdoc'
    save_package(path, source, r, PageProfile(), StyleProfile(), flow=flow)
    loaded = load_package(path)
    restored = render(loaded.session, t, resolver=loaded.resolver, flow=loaded.flow)
    assert loaded.session.source == source.source
    assert loaded.session.atom_ids == source.atom_ids
    assert loaded.resolver.selection_records() == choices
    assert page_svg(restored, 0, debug=True) == page_svg(result, 0, debug=True)


def test_partial_preview_keeps_multipage_prefix_and_page_order():
    t = template(loop=('p1','p2'), layouts=(
        PageLayout('p1','first',(frame(w=40,h=30),)),
        PageLayout('p2','second',(frame(w=50,h=35),)),
    ))
    result = render('1\n\n'*15 + '```\n' + '2'*100 + '\n```', t)
    assert 'template-body-no-progress' in codes(result)
    assert sum(f.text == '1' for f in result.fragments) == 15
    assert len(result.pages) > 2
    assert [p.index for p in result.pages] == list(range(len(result.pages)))
    assert [p.source_layout for p in result.pages] == [t.layout(i).label for i in range(len(result.pages))]


def test_placed_footnotes_survive_but_future_definitions_do_not_appear():
    t = template(layouts=(PageLayout('p1','p1',(frame(w=45,h=70),)),))
    result = render('1[^a]\n\n```\n' + '2'*100 + '\n```\n\n3[^b]\n\n[^a]: 456\n\n[^b]: 789', t)
    assert 'template-body-no-progress' in codes(result)
    assert any(o.execution_domain == 'page-footnotes' for p in result.pages for o in p.paint_ops)
    text = ''.join(f.text for f in result.fragments)
    assert all(c in text for c in '1456') and all(c not in text for c in '3789')


def test_valid_template_layout_has_no_preview_stop_error():
    t = template()
    result = render('123\n\n456', t)
    assert not codes(result)
    assert ''.join(f.text for f in result.fragments) == '123456'
