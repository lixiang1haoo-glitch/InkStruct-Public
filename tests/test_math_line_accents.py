"""Line accents reuse frozen minus samples and preserve physical clearance."""

import pytest
from test_math_sample_constructions import measure, resolver

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.resources import construction_requirements, inspect_resources
from inkstruct.document.schema import StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot


@pytest.mark.parametrize("name", ["bar", "overline", "underline"])
def test_line_accent_uses_minus_with_fixed_waviness_and_real_ink_clearance(name):
    r, style = resolver(), MathStyle(accent_clearance_em=0)
    before = {g.asset_id: g.original_json for pool in r.pools.values() for g in pool}
    short = measure(SourceSession("$\\" + name + "{1}$"), r, style)
    wide = measure(SourceSession("$\\" + name + "{12345}$"), r, style)
    assert short.ready and wide.ready
    a, b = short.rules[0], wide.rules[0]
    assert a.asset_id and a.sample_id and a.transform == "sample-minus-length-v1"
    assert b.transform == a.transform
    assert len(a.points) == len(b.points) == 3
    assert [y for _, y in a.points] == pytest.approx([y for _, y in b.points])
    assert max(y for _, y in a.points) > min(y for _, y in a.points)
    if name == "bar":
        assert b.points[-1][0] - b.points[0][0] <= .65 * style.em_mm + 1e-9
    else:
        assert b.points[-1][0] - b.points[0][0] > a.points[-1][0] - a.points[0][0]
    for box in (short, wide):
        ys = [y for rule in box.rules for _, y in rule.points]
        if name == "underline":
            content_edge = max(g.baseline_mm + g.descent_mm for g in box.glyphs)
            assert min(ys) - .15 - content_edge >= .45 - 1e-9
        else:
            content_edge = min(g.baseline_mm - g.ascent_mm for g in box.glyphs)
            assert content_edge - max(ys) - .15 >= .45 - 1e-9
    assert before == {g.asset_id: g.original_json for pool in r.pools.values() for g in pool}


@pytest.mark.parametrize("name", ["bar", "overline", "underline"])
def test_missing_minus_is_a_reported_requirement_and_blocks_export(name):
    session = SourceSession("$\\" + name + "{12}$")
    doc, r = parse_markdown(session), AssetResolver(builtin_numbers=True)
    required = construction_requirements(doc, MathStyle())
    assert len(required) == 1 and required[0].text == "−"
    assert required[0].span.start == 1 and required[0].span.end == len(session.source) - 1
    inspection = inspect_resources(doc, r)
    assert [g["character"] for g in inspection["gaps"]] == ["−"]
    assert not r.selections
    box = measure(session, r, MathStyle())
    assert not box.ready and any(d.code == "math-construction-sample-invalid" for d in box.diagnostics)
    geometric = MathStyle(fraction_source="geometric")
    assert not construction_requirements(doc, geometric)
    assert measure(session, r, geometric).ready


def test_nested_line_accents_roundtrip_machine_paths_and_keep_frozen_choices(tmp_path):
    session = SourceSession(r"$\overline{\underline{12}}$")
    r, flow = resolver(), FlowStyle(math=MathStyle())
    doc = parse_markdown(session)
    before = layout_markdown(doc, r, flow=flow)
    assert before.plotter_exportable, before.diagnostics
    plan = plan_from_snapshot(before)
    required = construction_requirements(doc, flow.math)
    choices = {o.occurrence_id: r.selections[o.occurrence_id] for o in required}
    assert len(required) == 2 and len(choices) == 2
    assert all(rule.asset_id for rule in measure(session, r, flow.math).rules)
    path = tmp_path / "line-accents.inkdoc"
    save_package(path, session, r, before.page_profile, StyleProfile(), flow=flow)
    loaded = load_package(path)
    after = layout_markdown(parse_markdown(loaded.session), loaded.resolver, flow=loaded.flow)
    assert after == before and plan_from_snapshot(after) == plan
    pos = session.source.index("12")
    session.apply(pos, pos + 2, "12345")
    expanded = layout_markdown(parse_markdown(session), r, flow=flow)
    assert expanded.plotter_exportable
    assert choices == {key: r.selections[key] for key in choices}
    session.undo()
    restored = layout_markdown(parse_markdown(session), r, flow=flow)
    assert restored.pages == before.pages
    assert plan_from_snapshot(restored).pages == plan.pages
