"""Literal code provenance, fixed columns, tab stops and line-preserving pagination."""

from dataclasses import replace

import pytest
from test_math_layout import resolver

from inkstruct.document.code_style import CodeStyle
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg


@pytest.mark.parametrize(
    "source,content",
    [
        ("```x\r\n1\t2  \r\n\r\n3\r\n```", "1\t2  \n\n3\n"),
        ("    1\t2\n    3", "1\t2\n3"),
        ("\t1\n\t2\n", "1\n2\n"),
        ("> ```\n> 1\t2\n> ```", "1\t2\n"),
        ("- 1\n\n  ```\n  2\t3\n  ```", "2\t3\n"),
    ],
)
def test_code_mapping_is_exact_without_invented_end_newline(source, content):
    doc = parse_markdown(source)
    code = next(n for root in doc.nodes for n in root.walk() if n.kind in {"fence", "code_block"})
    assert code.raw_content == content
    assert "".join(o.text for o in code.occurrences) == content
    for o in code.occurrences:
        assert source[o.span.start : o.span.end].replace("\r\n", "\n") == o.text
    assert not any(n.math for root in doc.nodes for n in root.walk())


def test_fixed_advance_tabs_blank_rows_and_trailing_spaces():
    doc = parse_markdown("```\n1\t2  \n\n12\t3\n```")
    result = layout_markdown(doc, resolver())
    assert result.exportable, result.diagnostics
    fs = result.fragments
    assert "".join(f.text for f in fs) == "1\t2  \n\n12\t3\n"
    assert fs[1].advance_mm == 15
    assert fs[2].x_mm - fs[0].x_mm == 20
    assert fs[9].text == "\t" and fs[9].advance_mm == 10
    assert fs[2].x_mm == fs[10].x_mm
    assert len({(f.page_index, f.line_index) for f in fs}) == 3
    assert all(f.advance_mm == 5 for f in fs if f.text not in "\t\n")


def test_code_does_not_wrap_or_apply_prose_punctuation_rules():
    source = "```\n" + ")" + "1" * 12 + "\n2\n```"
    doc = parse_markdown(source)
    r = resolver("12)")
    result = layout_markdown(doc, r, page=PageProfile(50, 70, 5))
    assert not result.exportable
    issue = next(d for d in result.diagnostics if d.code == "code-line-width-overflow")
    assert source[issue.span.start : issue.span.end] == ")" + "1" * 12 + "\n"
    assert not any(d.code == "forbidden-line-boundary" for d in result.diagnostics)
    assert len({f.line_index for f in result.fragments if f.text in ")1"}) == 1
    with pytest.raises(ValueError):
        plan_from_snapshot(result)


def test_code_literal_markup_missing_assets_and_too_small_cells():
    source = "```python\n$1$ **2** &amp; <3>\n```"
    doc = parse_markdown(source)
    assert "".join(o.text for o in doc.occurrences) == "$1$ **2** &amp; <3>\n"
    assert not any(n.math for root in doc.nodes for n in root.walk())
    missing = layout_markdown(doc, resolver())
    assert not missing.exportable
    flow = FlowStyle(code=CodeStyle(advance_mm=0.2))
    bad = layout_markdown(parse_markdown("```\n1\n```"), resolver(), flow=flow)
    assert any(d.code == "code-cell-overflow" for d in bad.diagnostics)


def test_code_identity_pagination_and_package_preserve_every_line(tmp_path):
    session = SourceSession("```\n" + "1\t2  \n" * 20 + "```")
    before = parse_markdown(session)
    session.apply(0, 0, "3\n\n")
    after = parse_markdown(session)
    assert [o.occurrence_id for o in after.occurrences[1:]] == [
        o.occurrence_id for o in before.occurrences
    ]
    session.undo()
    r = resolver()
    page = PageProfile(60, 55, 5)
    flow = FlowStyle(code=CodeStyle(em_mm=3.25, advance_mm=4.25, tab_columns=3))
    result = layout_markdown(parse_markdown(session), r, page=page, flow=flow)
    assert result.exportable and len(result.pages) > 1
    assert [f.occurrence_id for f in result.fragments] == [
        o.occurrence_id for o in before.occurrences
    ]
    for p in plan_from_snapshot(result).pages:
        page_svg(p)
    file = tmp_path / "code.inkdoc"
    save_package(file, session, r, page, StyleProfile(), flow=flow)
    loaded = load_package(file)
    assert loaded.flow.code == flow.code
    assert (
        layout_markdown(
            parse_markdown(loaded.session),
            loaded.resolver,
            page=loaded.page,
            style=loaded.style,
            flow=loaded.flow,
        )
        == result
    )


def test_code_configuration_rejects_invalid_tabs():
    with pytest.raises(ValueError):
        CodeStyle(tab_columns=0)
    with pytest.raises(ValueError):
        CodeStyle(tab_columns=2.5)
    with pytest.raises(ValueError):
        replace(CodeStyle(), advance_mm=float("nan"))


def test_normalized_null_and_control_spaces_never_silently_disappear():
    for char in ("\x00", "\x85", "\x7f", "\x0b"):
        doc = parse_markdown("```\n1" + char + "2\n```")
        result = layout_markdown(doc, resolver("12\ufffd"))
        assert not result.exportable
        assert any(d.code == "code-control-character" for d in result.diagnostics)


def test_partially_consumed_indent_tab_retains_distinct_source_anchors():
    source = "  ```\n\t1\n  ```"
    doc = parse_markdown(source)
    assert doc.nodes[0].raw_content == "  1\n"
    a, b, _one, _newline = doc.occurrences
    assert a.span == b.span and source[a.span.start : a.span.end] == "\t"
    assert a.occurrence_id != b.occurrence_id
    result = layout_markdown(doc, resolver())
    assert result.exportable and result.fragments[2].x_mm - result.fragments[0].x_mm == 10
    assert doc.source == source


def test_explicit_wrap_preserves_characters_and_marks_every_continuation_across_pages():
    source = "```\n" + "1234567890" * 5 + "\n2\n```"
    doc = parse_markdown(source)
    flow = FlowStyle(code=CodeStyle(wrap_lines=True))
    result = layout_markdown(doc, resolver(), page=PageProfile(40, 35, 5), flow=flow)
    assert result.exportable, result.diagnostics
    assert len(result.pages) > 1
    assert [f.occurrence_id for f in result.fragments] == [o.occurrence_id for o in doc.occurrences]
    marks = [
        p
        for page in result.pages
        for p in page.paint_ops
        if ":code-continuation:" in p.occurrence_id
    ]
    assert len(marks) == 9
    assert len({p.occurrence_id for p in marks}) == 9
    assert "".join(f.text for f in result.fragments) == "1234567890" * 5 + "\n2\n"
    for p in plan_from_snapshot(result).pages:
        page_svg(p)
