"""LaTeX single-token math arguments, scope, provenance and syntax audit."""

import pytest

from inkstruct.document.schema import SourceSpan
from inkstruct.math.parser import ACCENTS, COMMANDS, parse_math


def valid(source, *, offset=0):
    result = parse_math(source, offset=offset)
    assert result.valid, result.diagnostics
    return result.root


def test_unbraced_root_consumes_one_token_and_keeps_its_exact_source():
    source = r"\sqrt6+7"
    root = valid(source, offset=17)
    assert [node.kind for node in root.children] == ["Radical", "Symbol", "Symbol"]
    radical = root.children[0]
    assert radical.span == SourceSpan(17, 23)
    assert radical.children[0].span == SourceSpan(22, 23)
    assert radical.children[0].value == "6"
    assert root.children[1].value == "+"


@pytest.mark.parametrize("command", ["frac", "dfrac", "tfrac"])
@pytest.mark.parametrize("arguments", ["12", "{1}2", "1{2}", "{1}{2}", " 1 2"])
def test_fraction_accepts_mixed_grouped_or_single_token_arguments(command, arguments):
    fraction = valid("\\" + command + arguments).children[0]
    assert fraction.kind == "Fraction"
    assert dict(fraction.attributes) == {"style": command}
    assert [
        [n.value for n in argument.walk() if n.kind == "Symbol"] for argument in fraction.children
    ] == [["1"], ["2"]]


def test_unbraced_greek_and_nested_structures_are_complete_arguments():
    fraction = valid(r"\frac\sqrt9\alpha").children[0]
    assert [node.kind for node in fraction.children] == ["Radical", "Symbol"]
    assert fraction.children[1].value == "\N{GREEK SMALL LETTER ALPHA}"
    root = valid(r"\sqrt[3]8x")
    radical = root.children[0]
    assert dict(radical.attributes) == {"indexed": "true"}
    assert [node.value for node in radical.walk() if node.kind == "Symbol"] == ["3", "8"]
    assert root.children[1].value == "x"


def test_following_scripts_attach_outside_unbraced_arguments():
    root = valid(r"\sqrt6^2+\frac12_3+\mathrm m^2")
    scripts = [node for node in root.children if node.kind == "Scripts"]
    assert [node.children[0].kind for node in scripts] == ["Radical", "Fraction", "Group"]
    assert [dict(node.attributes) for node in scripts] == [{"sup": "1"}, {"sub": "1"}, {"sup": "1"}]
    roman = scripts[-1].children[0]
    assert dict(roman.attributes) == {"style": "mathrm"}
    assert [n.value for n in roman.walk() if n.kind == "Symbol"] == ["m"]


def test_roman_single_structure_preserves_inner_fraction_style_and_outer_script_scope():
    scripts = valid(r"\mathrm\dfrac12^3").children[0]
    assert scripts.kind == "Scripts"
    assert dict(scripts.children[0].attributes) == {"style": "mathrm"}
    fraction = next(n for n in scripts.children[0].walk() if n.kind == "Fraction")
    assert dict(fraction.attributes) == {"style": "dfrac"}
    assert [n.value for n in fraction.walk() if n.kind == "Symbol"] == ["1", "2"]
    assert scripts.children[1].value == "3"


def test_unknown_command_argument_keeps_the_unsupported_command_source_span():
    source = r"\sqrt\unknown"
    result = parse_math(source, offset=17)
    assert not result.valid
    error = result.diagnostics[0]
    assert error.code == "math-command-unsupported"
    assert source[error.span.start - 17 : error.span.end - 17] == r"\unknown"


def test_missing_fraction_argument_does_not_consume_the_matching_right_delimiter():
    source = r"\left(\frac1\right)"
    result = parse_math(source)
    assert not result.valid
    error = result.diagnostics[0]
    assert error.code == "math-argument"
    assert "denominator" in error.message
    assert source[error.span.start : error.span.end] == r"\frac1"


@pytest.mark.parametrize(
    "source,role",
    [
        (r"\frac1", "denominator argument"),
        (r"\frac{1}", "denominator argument"),
        (r"\frac", "numerator argument"),
        (r"\sqrt", "radicand argument"),
        (r"\sqrt[3]", "radicand argument"),
        (r"\mathrm", "argument"),
    ],
)
def test_missing_arguments_report_the_missing_role_without_inventing_content(source, role):
    result = parse_math(source, offset=17)
    assert not result.valid and result.root is None and result.source == source
    error = result.diagnostics[0]
    assert error.code == "math-argument"
    assert "Missing " + role in error.message
    assert error.span == SourceSpan(17, 17 + len(source))


@pytest.mark.parametrize("source", [r"\sqrt{}", r"\frac{}1", r"\frac1{}"])
def test_explicit_empty_arguments_remain_invalid(source):
    result = parse_math(source)
    assert not result.valid and result.diagnostics[0].code == "math-empty"


@pytest.mark.parametrize(
    "source", [r"\sqrt" * 40 + "6", r"\frac1" * 40 + "2", r"\mathrm " * 40 + "x"]
)
def test_ungrouped_recursive_arguments_obey_the_existing_depth_budget(source):
    result = parse_math(source)
    assert not result.valid and result.diagnostics[0].code == "math-depth"


def test_hbar_and_fullwidth_period_preserve_semantics_and_source_spans():
    root = valid(r"\hbar" + "\N{FULLWIDTH FULL STOP}" + "1.5", offset=17)
    assert [node.value for node in root.children] == [
        "\N{PLANCK CONSTANT OVER TWO PI}",
        ".",
        "1",
        ".",
        "5",
    ]
    assert root.children[0].span == SourceSpan(17, 22)
    assert root.children[1].span == SourceSpan(22, 23)
    assert "hbar" in COMMANDS


@pytest.mark.parametrize("command", sorted(ACCENTS))
def test_audit_all_existing_accent_commands_with_unbraced_arguments(command):
    assert valid("\\" + command + " x").children[0].kind == "Accent"


@pytest.mark.parametrize(
    "source",
    [
        r"\sin x+\cos y+\tan z+\log_2 x+\ln x+\exp x",
        r"\sum\limits_{i=1}^n i+\prod_{i=1}^n i+\int_0^1 x+\oint x",
        r"\left\{\frac12\right.",
        r"\text{unit}+\mathrm{m^2}+\operatorname{rank} A",
        r"\begin{pmatrix}1&2\\3&4\end{pmatrix}",
        r"\begin{cases}1&x>0\\0&x=0\end{cases}",
        r"\begin{aligned}x&=\sqrt6\\y&=\frac12\end{aligned}",
        r"\begin{array}{r|c}\hline 1&2\\\cline{1-2}\end{array}",
        r"\begin{equation}x=1\label{eq:x}\end{equation}+\eqref{eq:x}",
    ],
)
def test_common_supported_syntax_audit(source):
    valid(source)


@pytest.mark.parametrize(
    "source",
    [
        r"\mathbf{x}",
        r"\mathit{x}",
        r"\mathbb{R}",
        r"\mathcal{F}",
        r"\binom{n}{k}",
        r"\overbrace{x}",
        r"\underbrace{x}",
        r"\overset{a}{b}",
        r"\underset{a}{b}",
        r"\iint x",
        r"\!x",
        r"\bigl(x\bigr)",
    ],
)
def test_common_extensions_outside_the_controlled_grammar_fail_explicitly(source):
    result = parse_math(source)
    assert not result.valid and result.diagnostics[0].code == "math-command-unsupported"


@pytest.mark.parametrize("row_break", [r"\\[2pt]", r"\\*"])
def test_matrix_row_options_are_rejected_instead_of_becoming_visible_math(row_break):
    source = r"\begin{matrix}1" + row_break + r"2\end{matrix}"
    result = parse_math(source)
    assert not result.valid
    error = result.diagnostics[0]
    assert error.code == "math-matrix-option"
    assert source[error.span.start : error.span.end] == row_break[2]


def test_matrix_literal_leading_bracket_after_row_break_can_be_grouped():
    matrix = valid(r"\begin{matrix}1\\{[2]}\end{matrix}").children[0]
    assert [[n.value for n in row.walk() if n.kind == "Symbol"] for row in matrix.children] == [
        ["1"],
        ["[", "2", "]"],
    ]
