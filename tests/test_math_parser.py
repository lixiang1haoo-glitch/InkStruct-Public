import pytest

from inkstruct.document.schema import SourceSpan
from inkstruct.document.source_map import MappedText, parser_view
from inkstruct.math.parser import COMMANDS, FUNCTIONS, MATRIX_ENVIRONMENTS, SYMBOLS, parse_math


def valid(source):
    result = parse_math(source)
    assert result.valid, result.diagnostics
    return result.root


def test_math_tree_retains_semantics_script_order_and_distinct_greek_variants():
    source = r"-x_1^2+\frac{\alpha}{\sqrt[3]{y}}\leq\varepsilon+\epsilon"
    root = valid(source)
    assert [n.kind for n in root.children] == [
        "Symbol",
        "Scripts",
        "Symbol",
        "Fraction",
        "Symbol",
        "Symbol",
        "Symbol",
        "Symbol",
    ]
    assert root.children[0].value == "−" and root.children[0].math_class == "ord"
    assert root.children[2].math_class == "bin" and root.children[4].math_class == "rel"
    scripts = root.children[1]
    assert dict(scripts.attributes) == {"sub": "1", "sup": "2"}
    assert [n.value for n in scripts.children] == ["x", "1", "2"]
    fraction = root.children[3]
    assert source[fraction.span.start : fraction.span.end] == r"\frac{\alpha}{\sqrt[3]{y}}"
    radical = next(n for n in fraction.walk() if n.kind == "Radical")
    assert dict(radical.attributes)["indexed"] == "true"
    assert [n.value for n in radical.children[0].walk() if n.kind == "Symbol"] == ["3"]
    assert root.children[5].value != root.children[7].value
    assert dict(valid("x^2_1").children[0].attributes) == {"sup": "1", "sub": "2"}


@pytest.mark.parametrize("name,value", sorted(SYMBOLS.items()))
def test_each_whitelisted_symbol_command_has_exact_semantic_value_and_source(name, value):
    root = valid("\\" + name)
    assert root.children[0].value == value
    assert root.children[0].span == SourceSpan(0, len(name) + 1)
    assert name in COMMANDS


def test_new_capture_symbols_keep_relation_spacing_and_distinct_parallel_identity():
    root = valid(r"1\ni2\uparrow3\downarrow4\perp5\parallel6")
    assert [n.value for n in root.children if n.math_class == "rel"] == list("∋↑↓⊥∥")
    assert valid(r"\emptyset\angle\prime").children[0].math_class == "ord"
    # Parallel and double vertical delimiter are distinct captured characters.
    assert valid(r"\parallel").children[0].value != valid(r"\Vert").children[0].value
    assert not parse_math(r"\varnothing").valid  # No unrecorded variant substitution.


def test_function_unit_and_text_commands_are_not_parsed_as_variable_names():
    root = valid(r"\sin x+2\,\mathrm{m/s}+\text{电压 \%}")
    operator = root.children[0]
    assert operator.kind == "Operator" and operator.math_class == "op"
    assert "".join(n.value for n in operator.children) == "sin"
    assert all(n.span == SourceSpan(0, 4) for n in operator.children)
    assert [n.value for n in root.children if n.kind == "Space"] == ["thin"]
    roman = next(n for n in root.children if dict(n.attributes).get("style") == "mathrm")
    assert "".join(n.value for n in roman.walk() if n.kind == "Symbol") == "m/s"
    texts = [n for n in root.children if n.kind == "Text"]
    assert "".join(n.value for n in texts[0].children) == "电压 %"
    assert any(n.kind == "Scripts" for n in valid(r"\mathrm{m^2}").walk())
    for name in FUNCTIONS:
        assert valid("\\" + name).children[0].math_class == "op"


@pytest.mark.parametrize("environment", sorted(MATRIX_ENVIRONMENTS))
def test_bounded_matrix_and_cases_environment(environment):
    source = r"\begin{" + environment + r"}1&x_1\\\frac{2}{3}&\sqrt{4}\end{" + environment + "}"
    root = valid(source)
    matrix = root.children[0]
    assert matrix.kind == "Matrix" and dict(matrix.attributes)["environment"] == environment
    assert [len(n.children) for n in matrix.children] == [2, 2]
    assert [n.value for n in matrix.walk() if n.kind == "Symbol"] == list("1x1234")


def test_delimiters_nested_environments_and_operator_limits_are_structural():
    root = valid(r"\left\{\sum\limits_{i=1}^{n}x_i+\int\nolimits_0^1 f(x)\right.")
    outer = root.children[0]
    assert outer.kind == "Delimited" and dict(outer.attributes)["left"] == "{"
    assert dict(outer.attributes)["right"] == "."
    scripts = [n for n in outer.walk() if n.kind == "Scripts"]
    assert dict(scripts[0].children[0].attributes)["limits"] == "limits"
    assert dict(scripts[2].children[0].attributes)["limits"] == "nolimits"
    matrix = valid(r"\begin{matrix}\begin{matrix}1&2\end{matrix}&3\end{matrix}")
    assert len([n for n in matrix.walk() if n.kind == "Matrix"]) == 2


@pytest.mark.parametrize(
    "source,code,lexeme",
    [
        (r"x+\input{secret}", "math-command-unsupported", r"\input"),
        (r"\newcommand{\a}{1}", "math-command-unsupported", r"\newcommand"),
        ("x^1^2", "math-script", "^"),
        ("x_", "math-script", "_"),
        ("{x", "math-group", "{x"),
        ("x}", "math-unexpected", "}"),
        (r"\frac{1}", "math-argument", r"\frac{1}"),
        (r"\frac{}{2}", "math-empty", r"\frac{}{2}"),
        (r"\text{\alpha}", "math-text-command", r"\alpha"),
        (r"x\limits_1", "math-limits", r"\limits"),
        (r"\left(x", "math-delimiter", r"\left(x"),
        (r"\right)", "math-unexpected", r"\right"),
        (r"\begin{flalign}x\end{flalign}", "math-environment", r"\begin{flalign}"),
        (r"\begin{matrix}1&2\\3\end{matrix}", "math-matrix", r"\begin{matrix}1&2\\3\end{matrix}"),
        ("x% comment", "math-symbol", "%"),
        ("🙂", "math-symbol", "🙂"),
    ],
)
def test_invalid_syntax_fails_closed_and_points_to_the_exact_source(source, code, lexeme):
    result = parse_math(source, offset=17)
    assert not result.valid and result.root is None and result.source == source
    error = result.diagnostics[0]
    assert error.code == code
    assert source[error.span.start - 17 : error.span.end - 17] == lexeme


def test_crlf_and_entity_mapping_is_preserved_without_substring_search():
    raw = "x\r\n+\\alpha"
    view = parser_view(raw)
    root = parse_math(view).root
    assert root is not None
    assert root.children[-1].span == SourceSpan(4, 10)
    mapped = MappedText("x<y", (SourceSpan(10, 11), SourceSpan(11, 15), SourceSpan(15, 16)))
    root = parse_math(mapped).root
    assert root.children[1].span == SourceSpan(11, 15)


def test_depth_size_and_matrix_budgets_terminate_with_diagnostics():
    for source in [
        "{" * 40 + "x" + "}" * 40,
        "1" * 4097,
        r"\begin{matrix}" + "&".join("1" * 9) + r"\end{matrix}",
    ]:
        result = parse_math(source)
        assert not result.valid
        assert "budget" in result.diagnostics[0].code or result.diagnostics[0].code == "math-depth"
