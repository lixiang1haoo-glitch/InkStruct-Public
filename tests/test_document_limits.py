"""Whole-document caps reject oversized work without truncation or cache bypass."""

from dataclasses import replace

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document import limits
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import SemanticNode, parse_markdown
from inkstruct.document.schema import PageProfile, SourceSpan
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.schema import MathNode
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.renderers.pages import export_pages, page_svg, preview_key


def limited(monkeypatch, **values):
    monkeypatch.setattr(limits, "DEFAULT_LIMITS", replace(limits.DEFAULT_LIMITS, **values))


def tree_size(nodes):
    stack = list(nodes)
    count = 0
    while stack:
        node = stack.pop()
        count += 1
        stack.extend(node.children)
        if getattr(node, "math", None):
            stack.append(node.math)
    return count


def test_total_semantic_and_math_nodes_and_token_counts(monkeypatch):
    session = SourceSession("1\n\n2\n\n$\\frac{12}{3}$")
    original = session.identity_record()
    expected = parse_markdown(session)
    count = tree_size(expected.nodes)
    with monkeypatch.context() as patch:
        limited(patch, nodes=count)
        assert parse_markdown(session) == expected
        limited(patch, nodes=count - 1)
        with pytest.raises(limits.DocumentLimitError, match="节点") as error:
            parse_markdown(session)
        assert error.value.kind == "nodes"
    with monkeypatch.context() as patch:
        limited(patch, tokens=6)
        with pytest.raises(limits.DocumentLimitError) as error:
            parse_markdown(session)
        assert error.value.kind == "tokens" and error.value.actual == 7
    assert session.identity_record() == original
    assert parse_markdown(session) == expected  # Failed request leaves no active budget.


def test_prebuilt_deep_tree_rejected_before_recursive_layout():
    node = SemanticNode("leaf", "text", SourceSpan(0, 1))
    for i in range(1000):
        node = SemanticNode(str(i), "blockquote", SourceSpan(0, 1), (node,))
    doc = replace(parse_markdown("1"), nodes=(node,))
    with pytest.raises(limits.DocumentLimitError) as error:
        layout_markdown(doc, AssetResolver(builtin_numbers=True))
    assert error.value.kind == "depth"
    math = MathNode("Symbol", SourceSpan(0, 1), value="1")
    for _ in range(70):
        math = MathNode("Group", SourceSpan(0, 1), (math,))
    with pytest.raises(limits.DocumentLimitError):
        limits.validate_nodes((SemanticNode("math", "math_inline", SourceSpan(0, 1), math=math),))


def test_existing_block_token_and_parser_depth_limits_use_draft_safe_error():
    from types import SimpleNamespace

    from inkstruct.document._markdown_mapping import LocatedBlockState

    with pytest.raises(limits.DocumentLimitError) as error:
        LocatedBlockState.push(SimpleNamespace(tokens=range(50_000)), "paragraph_open", "p", 1)
    assert error.value.kind == "block_tokens"
    with pytest.raises(limits.DocumentLimitError) as error:
        parse_markdown("> " * 40 + "1")
    assert error.value.kind == "parser_depth"


def test_page_limit_exact_boundary_and_source_preservation(monkeypatch):
    session = SourceSession("12.50\n\n" * 20)
    doc = parse_markdown(session)
    page = PageProfile(40, 40, 5)

    def build():
        return layout_markdown(doc, AssetResolver(builtin_numbers=True), page=page)

    expected = build()
    assert len(expected.pages) > 2
    limited(monkeypatch, pages=len(expected.pages))
    assert build() == expected
    limited(monkeypatch, pages=len(expected.pages) - 1)
    with pytest.raises(limits.DocumentLimitError) as error:
        build()
    assert error.value.kind == "pages" and error.value.actual == len(expected.pages)
    assert session.source == "12.50\n\n" * 20


@pytest.mark.parametrize(
    "source", ["12.50", "$\\frac{12}{34}$", "|12|34|\n|---|---|\n|5.6|7.8|", "12[^a]\n\n[^a]: 34"]
)
def test_geometry_limits_cover_mixed_elements(source, monkeypatch):
    from test_math_sample_constructions import resolver

    doc = parse_markdown(source)

    def build():
        return layout_markdown(doc, resolver())

    expected = build()
    points = sum(len(o.points) for p in expected.pages for o in (*p.paint_ops, *p.preview_ops))
    assert points > 10 and expected.exportable
    limited(monkeypatch, points=points - 1)
    with pytest.raises(limits.DocumentLimitError) as error:
        build()
    assert error.value.kind == "points"


def test_repeated_template_fields_count_toward_document_points(monkeypatch):
    from test_template_fields import setup

    _, doc, r, flow = setup(repeat=True, mode="blank")
    expected = layout_markdown(doc, r, flow=flow)
    points = sum(len(o.points) for p in expected.pages for o in (*p.paint_ops, *p.preview_ops))
    limited(monkeypatch, points=points - 1)
    with pytest.raises(limits.DocumentLimitError) as error:
        layout_markdown(doc, r, flow=flow)
    assert error.value.kind == "points"


def test_nested_footnote_passes_share_expansion_budget(monkeypatch):
    doc = parse_markdown("12[^a]\n\n[^a]: 34")
    observed = {}
    original = limits.WorkBudget.add

    def add(self, kind, count):
        original(self, kind, count)
        if kind == "expanded_points":
            observed[id(self)] = self.expanded_points

    monkeypatch.setattr(limits.WorkBudget, "add", add)
    expected = layout_markdown(doc, AssetResolver(builtin_numbers=True))
    assert len(observed) == 1
    total = next(iter(observed.values()))
    assert total > sum(len(o.points) for p in expected.pages for o in p.paint_ops)
    limited(monkeypatch, expanded_points=total - 1)
    with pytest.raises(limits.DocumentLimitError) as error:
        layout_markdown(doc, AssetResolver(builtin_numbers=True))
    assert error.value.kind == "expanded_points"


def test_export_and_preview_cannot_bypass_current_limits_with_old_snapshot(tmp_path, monkeypatch):
    s = layout_markdown(parse_markdown("12.50"), AssetResolver(builtin_numbers=True))
    limited(monkeypatch, points=1)
    for call in [
        lambda: plan_from_snapshot(s),
        lambda: page_svg(s, 0),
        lambda: page_svg(s, 0, debug=True),
        lambda: preview_key(s, 0),
    ]:
        with pytest.raises(limits.DocumentLimitError):
            call()
    with pytest.raises(limits.DocumentLimitError):
        export_pages(s, tmp_path / "new", png=False)
    assert not (tmp_path / "new").exists()


def test_content_cache_policy_change_cannot_reuse_oversized_result(monkeypatch):
    pytest.importorskip("PySide6")
    from test_build_cache import args

    from inkstruct.editor.build_cache import MarkdownBuildCache
    from inkstruct.editor.mixed import build_markdown

    inputs = args()
    c = MarkdownBuildCache()
    build_markdown(**inputs, cache=c)
    limited(monkeypatch, points=1)
    with pytest.raises(limits.DocumentLimitError):
        build_markdown(**inputs, cache=c)
    assert c.layouts.statistics()["hits"] == 0


def test_cli_over_budget_does_not_create_partial_output(tmp_path, monkeypatch):
    from inkstruct.cli import build_parser
    from inkstruct.document.cli import run_document_command

    source = tmp_path / "large.md"
    source.write_text("12.50")
    output = tmp_path / "not-created"
    args = build_parser().parse_args(
        [
            "document",
            "render",
            str(source),
            "--mode",
            "markdown",
            "--plotter",
            "--output",
            str(output),
        ]
    )
    limited(monkeypatch, points=1)
    code, report = run_document_command(args)
    assert code == 2 and not report["exportable"] and "超限" in report["error"]
    assert not output.exists() and source.read_text() == "12.50"
