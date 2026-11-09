"""Recorded structural glyphs stretch explicitly, persist and retain their provenance."""

import json
from dataclasses import replace

import pytest
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import SymbolProvider, adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.sample_constructions import radical_sample_paths
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot


def assets():
    paths = {
        "−": (((0, 0.4), (0.3, 0.42), (0.7, 0.39)),),
        "√": (((0.25, 0.1), (0.6, 0.11), (1, 0.1)), ((0.25, 0.1), (0.2, 1), (0.1, 0.8), (0, 0.9))),
        "(": (((0.3, 0), (0.1, 0.2), (0, 0.6), (0.2, 1)),),
        ")": (((0, 0), (0.2, 0.3), (0.3, 0.7), (0.1, 1)),),
        "[": (((0.3, 0), (0, 0), (0, 1), (0.3, 1)),),
        "]": (((0, 0), (0.3, 0), (0.3, 1), (0, 1)),),
        "{": (((0.3, 0), (0.15, 0.3), (0, 0.5), (0.15, 0.7), (0.3, 1)),),
        "}": (((0, 0), (0.15, 0.3), (0.3, 0.5), (0.15, 0.7), (0, 1)),),
        "|": (((0, 0), (0.01, 0.3), (0, 1)),),
    }
    result = []
    for char, strokes in paths.items():
        data = specimen(char=char, sid=char)
        data["strokes"] = [
            {"points": [{"x": x * 100 + 10, "y": y * 100} for x, y in stroke]} for stroke in strokes
        ]
        data["guides"]["math_axis_em"] = 0.25
        result.append(adapt_symbol(json.dumps(data).encode()))
    return result


def resolver():
    return AssetResolver(symbols=SymbolProvider(assets()), builtin_numbers=True)


STYLE = MathStyle(fraction_source="sample", radical_source="sample", delimiter_source="sample")


def measure(session, r, style=STYLE):
    doc = parse_markdown(session)
    node = next(n for root in doc.nodes for n in root.walk() if n.math)
    return measure_math(node.math, r, owner=node.node_id, style=style)


@pytest.mark.parametrize(
    "source",
    [
        r"\frac{12}{3}",
        r"\sqrt{123}",
        r"\sqrt[3]{\frac{12}{34}}",
        r"\left(\frac{1}{2}\right)",
        r"\begin{bmatrix}1&2\\3&4\end{bmatrix}",
        r"\begin{cases}1&2\\3&4\end{cases}",
    ],
)
def test_sample_constructions_keep_semantic_coverage_and_roundtrip(source, tmp_path):
    session, r = SourceSession("$" + source + "$"), resolver()
    original = {g.asset_id: g.original_json for pool in r.pools.values() for g in pool}
    box = measure(session, r)
    assert box.ready, box.diagnostics
    assert box.rules and all(
        rule.asset_id and rule.sample_id and rule.transform for rule in box.rules
    )
    flow = FlowStyle(math=STYLE)
    before = layout_markdown(parse_markdown(session), r, flow=flow)
    assert before.plotter_exportable, before.diagnostics
    assert len(before.fragments) == len(parse_markdown(session).occurrences)
    plan_from_snapshot(before)
    path = tmp_path / "sample.inkdoc"
    save_package(path, session, r, PageProfile(), StyleProfile(), flow=flow)
    loaded = load_package(path)
    after = layout_markdown(parse_markdown(loaded.session), loaded.resolver, flow=loaded.flow)
    assert after == before and loaded.resolver.selection_records() == r.selection_records()
    assert original == {
        g.asset_id: g.original_json for pool in loaded.resolver.pools.values() for g in pool
    }


def test_minus_length_changes_without_amplifying_its_vertical_variation():
    r = resolver()
    a = measure(SourceSession(r"$\frac{1}{2}$"), r)
    b = measure(SourceSession(r"$\frac{12345}{2}$"), r)
    pa, pb = a.rules[0].points, b.rules[0].points
    assert len(pa) == len(pb) == 3
    assert [y for _, y in pa] == [y for _, y in pb]
    assert pb[-1][0] > pa[-1][0]
    upper, lower = min(y for _, y in pa), max(y for _, y in pa)
    numerator, denominator = a.glyphs
    clearance = 0.12 * STYLE.em_mm
    assert upper - 0.15 - (numerator.baseline_mm + numerator.descent_mm) >= clearance - 1e-9
    assert denominator.baseline_mm - denominator.ascent_mm - lower - 0.15 >= clearance - 1e-9


@pytest.mark.parametrize("continuous", [False, True])
def test_radical_bar_extends_while_hook_and_stroke_order_stay_fixed(continuous):
    glyph = next(g for g in assets() if g.character == "√")
    if continuous:
        glyph = replace(glyph, strokes=(tuple(reversed(glyph.strokes[1])) + glyph.strokes[0][1:],))
    kw = {"start": 0, "hook_width": 3, "bar_bottom": -8, "bottom": 1, "radius": 0.15}
    a = radical_sample_paths(glyph, width=20, **kw)
    b = radical_sample_paths(glyph, width=40, **kw)
    assert len(a) == len(b) == len(glyph.strokes)
    if continuous:
        assert a[0][:4] == b[0][:4]
    else:
        assert a[1] == b[1]  # Complete hook/stem stroke.
    assert [y for _, y in a[0]] == [y for _, y in b[0]]
    assert b[0][-1][0] - a[0][-1][0] == pytest.approx(20)
    if not continuous:
        assert max(y for _, y in a[0]) == pytest.approx(-8)


def test_structural_selection_survives_offsets_content_edits_and_added_pool_members():
    session, r = SourceSession(r"$\sqrt{12}+\frac{3}{4}$"), resolver()
    # The plus is deliberately missing; structural selection still remains stable.
    a = measure(session, r)
    choices = {rule.occurrence_id: rule.asset_id for rule in a.rules}
    session.apply(0, 0, "12\n\n")
    b = measure(session, r)
    assert {rule.occurrence_id: rule.asset_id for rule in b.rules} == choices
    pos = session.source.index("{12}") + 1
    session.apply(pos, pos + 2, "12345")
    c = measure(session, r)
    assert {rule.occurrence_id: rule.asset_id for rule in c.rules} == choices
    session.undo()
    assert measure(session, r).rules == b.rules
    raw = json.loads(next(g for g in assets() if g.character == "√").original_json)
    raw["sample_id"] = "added-root-variant"
    expanded = AssetResolver(
        symbols=SymbolProvider([*assets(), adapt_symbol(json.dumps(raw).encode())]),
        builtin_numbers=True,
        selections=tuple(r.selections.values()),
    )
    assert measure(session, expanded).rules == b.rules


def test_missing_or_degenerate_selected_sample_blocks_export_without_substitution():
    session = SourceSession(r"$\sqrt{12}$")
    empty = AssetResolver(builtin_numbers=True)
    snapshot = layout_markdown(parse_markdown(session), empty, flow=FlowStyle(math=STYLE))
    assert not snapshot.exportable
    assert any(d.code == "math-construction-sample-invalid" for d in snapshot.diagnostics)
    r = resolver()
    measure(session, r)
    missing = AssetResolver(builtin_numbers=True, selections=tuple(r.selections.values()))
    assert not measure(session, missing).ready
    bad = replace(assets()[1], strokes=(((0, 0), (0, 1)),))
    with pytest.raises(ValueError):
        radical_sample_paths(
            bad, start=0, hook_width=3, width=20, bar_bottom=-8, bottom=1, radius=0.15
        )


def test_old_style_uses_geometric_shapes_and_unknown_mode_is_rejected():
    old = MathStyle(em_mm=6, fraction_source="geometric")
    assert old.fraction_source == old.radical_source == old.delimiter_source == "geometric"
    for key in ["fraction_source", "radical_source", "delimiter_source"]:
        with pytest.raises(ValueError):
            MathStyle(**{key: "guess"})
