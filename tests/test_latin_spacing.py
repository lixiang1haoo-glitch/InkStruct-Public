import json
from dataclasses import replace

import pytest
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.glyph_corrections import GlyphCorrection
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.layout.measurement_cache import MeasurementCache, measurement_scope
from inkstruct.renderers.pages import page_svg


def captured(char, left):
    value = specimen(char, char)
    value['strokes'][0]['points'][0]['x'] = 10 + left * 100
    value['strokes'][0]['points'][1]['x'] = 10 + (left + .1) * 100
    return adapt_symbol(json.dumps(value).encode())


def test_capture_position_is_not_a_letter_bearing_and_cache_tracks_policy(tmp_path):
    session = SourceSession('iiWW 11\n\n`ii`\n\n$i$')
    resolver = AssetResolver(embedded=[captured('i', .4), captured('W', -.2), captured('1', .3)])
    doc = parse_markdown(session)
    flow = FlowStyle(latin_spacing='handwriting')
    cache = MeasurementCache()
    with measurement_scope(cache):
        old = layout_markdown(doc, resolver)
        chosen = resolver.selection_records()
        new = layout_markdown(doc, resolver, flow=flow)
        assert new == layout_markdown(doc, resolver, flow=flow)
        assert old == layout_markdown(doc, resolver)
    assert cache.reused > 0
    assert resolver.selection_records() == chosen
    assert flow.schema_version == 'inkstruct_flow_style_v3'
    # One tenth em ink, .08 em clearance and the physical stroke width.
    assert new.fragments[0].advance_mm == pytest.approx(.18 * 6 + .3)
    assert new.fragments[0].ink_bounds[0] - new.fragments[0].x_mm == pytest.approx(.04 * 6)
    assert new.fragments[1].ink_bounds[0] - new.fragments[0].ink_bounds[2] == pytest.approx(.08 * 6)
    # Off-centre narrow and wide letter captures receive equal clearance.
    assert [f.advance_mm for f in new.fragments[:4]] == pytest.approx([1.38] * 4)
    # Spaces, digits, inline code and mathematics retain their own rules.
    for a, b in zip(old.fragments[4:], new.fragments[4:]):
        assert a.advance_mm == b.advance_mm
    path = tmp_path / 'letters.inkdoc'
    save_package(path, session, resolver, PageProfile(), StyleProfile(), flow=flow)
    loaded = load_package(path)
    reopened = layout_markdown(parse_markdown(loaded.session), loaded.resolver, flow=loaded.flow)
    assert page_svg(new, 0) == page_svg(reopened, 0)
    assert loaded.resolver.selection_records() == chosen


def test_reflow_tables_fields_corrections_and_no_font_mutation(tmp_path):
    resolver = AssetResolver(embedded=[captured('i', .4)])
    before = tuple(g.original_json for g in resolver.pools['i'])
    source = 'ii ii ii ii ii ii\n\n|ii|\n|---|\n|ii|'
    session = SourceSession(source)
    page = PageProfile(50, 150, 10)
    doc = parse_markdown(session)
    old = layout_markdown(doc, resolver, page=page)
    flow = FlowStyle(latin_spacing='handwriting')
    new = layout_markdown(doc, resolver, page=page, flow=flow)
    assert len({f.line_index for f in new.fragments if f.container_id is None}) < len(
        {f.line_index for f in old.fragments if f.container_id is None})
    assert new.fragments[-1].advance_mm < old.fragments[-1].advance_mm
    f = new.fragments[0]
    rule = GlyphCorrection(character='i', occurrence_id=f.occurrence_id, asset_id=f.asset_id, dx_em=.05)
    corrected = layout_markdown(doc, resolver, page=page, flow=replace(flow, glyph_corrections=(rule,)))
    assert corrected.fragments[0].x_mm == f.x_mm
    assert corrected.fragments[0].advance_mm == f.advance_mm
    assert corrected.fragments[0].ink_bounds[0] == pytest.approx(f.ink_bounds[0]+.3)
    assert tuple(g.original_json for g in resolver.pools['i']) == before


def test_named_field_project_preserves_new_style(tmp_path):
    from inkstruct.document.flow_template import FlowTemplate

    template = FlowTemplate(**json.loads(__import__('pathlib').Path('configs/templates/simple-v3.json').read_text(encoding='utf-8')))
    session = SourceSession('iiii')
    resolver = AssetResolver(embedded=[captured('i', .4)])
    flow = FlowStyle(template=template, latin_spacing='handwriting')
    snapshot = layout_markdown(parse_markdown(session, field_blocks=True), resolver, flow=flow)
    output = tmp_path / 'v3-template.inkdoc'
    save_package(output, session, resolver, template.page, StyleProfile(), flow=flow)
    loaded = load_package(output)
    assert loaded.flow == flow
    assert page_svg(snapshot, 0, debug=True) == page_svg(layout_markdown(
        parse_markdown(loaded.session, field_blocks=True), loaded.resolver, flow=loaded.flow), 0, debug=True)


@pytest.mark.parametrize('value', ['unknown', None, 3])
def test_unknown_policy_rejected(value):
    with pytest.raises(ValueError):
        FlowStyle(latin_spacing=value)
