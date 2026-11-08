import json
from dataclasses import asdict

from inkstruct.assets.resolver import AssetResolver
from inkstruct.cli import main
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.table_export import table_export_view
from inkstruct.layout.blocks import layout_markdown


def maths(doc):
    return [n for root in doc.nodes for n in root.walk() if n.kind in {"math_inline", "math_block"}]


def test_inline_math_owns_markup_and_preserves_original_crlf_scalar_ranges():
    source = "𠀀 $x_1+\\frac{2}{3}$ 与 $\\alpha*2$\r\n"
    doc = parse_markdown(source)
    nodes = maths(doc)
    assert len(nodes) == 2
    assert source[nodes[0].span.start : nodes[0].span.end] == "$x_1+\\frac{2}{3}$"
    assert nodes[0].raw_content == r"x_1+\frac{2}{3}"
    assert [o.text for o in nodes[0].occurrences] == list("x1+23")
    assert [o.text for o in nodes[1].occurrences] == ["α", "∗", "2"]
    assert not doc.diagnostics
    assert not any(n.kind == "em" for root in doc.nodes for n in root.walk())


def test_display_math_and_nested_markdown_block_boundaries():
    source = "前\r\n\r\n> $$\r\n> \\frac{1}{2}\r\n> $$\r\n\r\n后"
    doc = parse_markdown(source)
    node = maths(doc)[0]
    assert node.kind == "math_block" and node.math.children[0].kind == "Fraction"
    assert source[node.span.start : node.span.end].startswith("$$\r\n> ")
    assert [source[o.span.start : o.span.end] for o in node.occurrences] == ["1", "2"]
    listing = parse_markdown("- $$\n  x_1\n  $$\n\n- 后")
    assert len(maths(listing)) == 1
    assert maths(listing)[0].math.children[0].kind == "Scripts"


def test_code_and_escaped_dollars_remain_literal_and_unclosed_math_is_diagnostic():
    source = r"\$x\$ `$$x_1$$`" + "\n\n```tex\n$$\n\\input{x}\n$$\n```\n\n    $x$\n"
    doc = parse_markdown(source)
    assert not maths(doc) and not any(d.code.startswith("math-") for d in doc.diagnostics)
    for source in ("$x", "$$x$$", "$$\nx", "$\nnext", "$ $"):
        doc = parse_markdown(source)
        assert any(d.code in {"math-delimiter", "math-empty"} for d in doc.diagnostics)
        assert not layout_markdown(doc, AssetResolver(builtin_numbers=True)).exportable


def test_pipe_and_html_cells_share_math_symbols_without_decoding_tex_as_markdown():
    source = r"|$x_1$|$\frac{2}{3}$|" + "\n|---|---|\n|4|5|"
    assert len(maths(parse_markdown(source))) == 2
    html = "<table><tr><td>$x&lt;y$</td><td><strong>$\\alpha$</strong></td><td><code>$x$</code></td></tr></table>"
    doc = parse_markdown(html)
    nodes = maths(doc)
    assert len(nodes) == 2 and [o.text for o in nodes[0].occurrences] == list("x<y")
    less = nodes[0].occurrences[1]
    assert html[less.span.start : less.span.end] == "&lt;"
    assert nodes[1].math.children[0].value == "α"
    assert any(o.text == "$" for o in doc.occurrences)  # Literal code survived.
    selected, report = table_export_view(doc, doc.nodes[0], numbers_only=True)
    assert len(report["omitted_cells"]) == 3
    assert layout_markdown(selected, AssetResolver(builtin_numbers=True)).exportable


def test_formula_cannot_cross_html_markup_boundary_or_escape_unknown_command_error():
    source = "<table><tr><td>$x<em>+y</em>$</td></tr></table>"
    assert any(d.code == "math-delimiter" for d in parse_markdown(source).diagnostics)
    source = r"before $x+\unknown{1}$ after"
    doc = parse_markdown(source)
    error = next(d for d in doc.diagnostics if d.code == "math-command-unsupported")
    assert source[error.span.start : error.span.end] == r"\unknown"
    assert maths(doc)[0].math is None
    assert maths(doc)[0].raw_content == r"x+\unknown{1}"
    assert not maths(doc)[0].occurrences


def test_math_occurrence_identity_is_stable_distinct_and_reversible():
    session = SourceSession(r"$\sin x_1$ $\sin x_1$")
    original = parse_markdown(session)
    before = [o.occurrence_id for n in maths(original) for o in n.occurrences]
    assert len(before) == len(set(before)) == 10
    assert len({o.span for o in maths(original)[0].occurrences[:3]}) == 1
    session.apply(0, 0, "前文\r\n\r\n")
    after = parse_markdown(session)
    assert [o.occurrence_id for n in maths(after) for o in n.occurrences] == before
    session.undo()
    assert asdict(parse_markdown(session)) == {**asdict(original), "revision": session.revision}
    session.apply(session.source.index("x"), session.source.index("x"), "y+")
    assert set(before) <= {
        o.occurrence_id for n in maths(parse_markdown(session)) for o in n.occurrences
    }


def test_cli_resource_scan_uses_math_symbols_and_unknown_commands_block_csv(tmp_path, capsys):
    source = tmp_path / "math.md"
    csv = tmp_path / "math.csv"
    source.write_text(r"$\frac{\epsilon}{\varepsilon}+\phi+\varphi$")
    assert main(["document", "resources", str(source), "--capture-csv", str(csv)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {g["character"] for g in report["gaps"]} == {"ϵ", "ε", "ϕ", "φ", "+", "−"}
    assert not any(g["character"] in {"f", "r", "a", "c"} for g in report["gaps"])
    assert not report["machine_export_ready"]
    source.write_text(r"$\input{secret}$")
    other = tmp_path / "bad.csv"
    assert main(["document", "resources", str(source), "--capture-csv", str(other)]) == 2
    assert not other.exists()
