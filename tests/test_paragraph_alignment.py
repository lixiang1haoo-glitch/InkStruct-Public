from dataclasses import replace

import pytest
from test_document_layout import provider

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import FlowTemplate, PageLayout, TextFrame
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Region
from inkstruct.layout.blocks import body_blocks, layout_markdown


def scoped(mode, text):
    return f"\\begin{{paragraphalign}}{{{mode}}}\n{text}\n\\end{{paragraphalign}}"


def lines(snapshot):
    result = []
    for page in snapshot.pages:
        groups = {}
        for fragment in page.fragments:
            if fragment.ink_bounds:
                groups.setdefault(fragment.line_index, []).append(fragment)
        result.append(tuple(tuple(group) for group in groups.values()))
    return result


@pytest.mark.parametrize('dialect', ['markdown', 'obsidian'])
def test_independent_controls_and_exclusions(dialect):
    inside = '# 甲\n\n乙\n\n|甲|\n|---|\n|乙|\n\n![甲](a.png)\n\n$$\n1\n$$\n\n> 甲\n\n- 乙\n\n```\n\\end{paragraphalign}\n```\n\n丙'
    source = '甲\n' + scoped('right', inside) + '\n丁'
    document = parse_markdown(source, dialect=dialect)
    assert [b.paragraph_align for b in body_blocks(document) if b.node.kind == 'paragraph'] == [
        'left', 'right', 'left', 'left', 'right', 'left']
    assert not any(d.code.startswith('paragraph-align') for d in document.diagnostics)
    assert 'paragraphalign' not in ''.join(o.text for o in document.occurrences if o.span.start < source.index('```'))


@pytest.mark.parametrize(('text', 'diagnostic', 'line'), [
    ('\\begin{paragraphalign}{left}\n甲', 'missing-end', 0),
    (scoped('invalid', '甲'), 'option', 0),
    ('\\begin{paragraphalign}{left\n甲\n\\end{paragraphalign}', 'option', 0),
    (scoped('center', '甲\n' + scoped('right', '甲') + '\n甲'), 'nested', 2),
    ('\\end{paragraphalign}\n甲', 'unexpected-end', 0),
])
def test_invalid_range_keeps_default_and_reports_source_line(text, diagnostic, line):
    source = text.replace('\n', '\r\n')
    document = parse_markdown(source)
    expected = next(d for d in document.diagnostics if d.code == 'paragraph-align-' + diagnostic)
    assert source[expected.span.start:expected.span.end] == text.splitlines()[line]
    assert all(block.paragraph_align == 'justify' for block in body_blocks(document, FlowStyle(paragraph_align='justify')))


@pytest.mark.parametrize('mode', ['left', 'center', 'right', 'justify'])
def test_placement_indent_and_wrapping_across_pages(mode):
    document = parse_markdown(scoped(mode, '甲' * 31) + '\n\n乙')
    resolver = AssetResolver(generated=provider('甲乙'))
    page = PageProfile(50, 35, 5)
    style = StyleProfile(em_mm=6, line_height_mm=8)
    flow = FlowStyle(first_line_indent_mm=10)
    result = layout_markdown(document, resolver, page=page, style=style, flow=flow)
    by_page = lines(result)
    assert len(by_page) >= 2
    visible = [line for group in by_page for line in group if line[0].text == '甲']
    assert sum(len(line) for line in visible) == 31
    assert len(visible) >= 5 and len(visible[0]) < 31
    assert next(f for f in result.fragments if f.text == '乙').x_mm == pytest.approx(15)
    if mode in {'center', 'right'}:
        assert len(visible[0]) == len(visible[1])
        for line in visible:
            left, right = line[0].logical_bounds[0], line[-1].logical_bounds[2]
            assert (left + right) / 2 == pytest.approx(25) if mode == 'center' else right == pytest.approx(45)
    else:
        assert len(visible[0]) < len(visible[1])
        assert visible[0][0].x_mm == pytest.approx(15)
        assert all(line[0].x_mm == pytest.approx(5) for line in visible[1:])
        if mode == 'justify':
            assert visible[0][-1].logical_bounds[2] == pytest.approx(45)
            assert visible[-1][-1].logical_bounds[2] < 45


def test_frame_width_and_saved_source_round_trip(tmp_path):
    frames = (TextFrame('first', 'First', Region('first', 5, 5, 33, 15)),
              TextFrame('second', 'Second', Region('second', 45, 5, 48, 35), order=2))
    template = FlowTemplate(kind='custom', width_mm=100, height_mm=70,
                            layouts=(PageLayout('body', 'Body', frames),), loop_pages=('body',))
    flow = FlowStyle(template=template, first_line_indent_mm=9)
    session = SourceSession(scoped('right', '甲甲甲\n\\framebreak\n甲甲') + '\n\n乙')
    style = StyleProfile()
    resolver = AssetResolver(generated=provider('甲乙'))

    def render(session, assets, flow):
        return layout_markdown(parse_markdown(session, field_blocks=True), assets, style=style, flow=flow)

    before = render(session, resolver, flow)
    assert before.exportable
    han = [line for group in lines(before) for line in group if line[0].text == '甲']
    assert [line[-1].logical_bounds[2] for line in han] == pytest.approx([38, 93])
    path = tmp_path / 'alignment.inkdoc'
    save_package(path, session, resolver, template.page, style, flow=flow)
    loaded = load_package(path)
    assert loaded.session.source == session.source
    assert render(loaded.session, loaded.resolver, loaded.flow) == before
    legacy = replace(flow, template=None)
    assert body_blocks(parse_markdown('甲'), legacy)[0].paragraph_align == 'left'
