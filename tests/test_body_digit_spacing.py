import json
from dataclasses import replace
from zipfile import ZipFile

import pytest
from test_document_layout import provider
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import SymbolProvider, adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.layout.inline import inline_runs, measure_runs
from inkstruct.layout.justification import justify_line


TEXT = '2024年12月 A4 v6.3.1'


def resolver():
    digits = SymbolProvider([adapt_symbol(json.dumps(specimen(n, n)).encode()) for n in '0123456789'])
    return AssetResolver(generated=provider('年月Av'), symbols=digits, builtin_numbers=True)


def test_body_digit_measurement_and_justification():
    assets, style = resolver(), StyleProfile()
    doc = parse_markdown(TEXT)
    runs = inline_runs(doc.nodes[0].children[0])
    before, _ = measure_runs(runs, assets, style, latin_spacing='handwriting')
    after, _ = measure_runs(runs, assets, style, latin_spacing='handwriting', digits_follow_latin=True)
    for old, new in zip(before, after, strict=True):
        if old.run.occurrence.text in '0123456789':
            assert new.advance < old.advance
            assert (new.ascent, new.descent, new.em, new.glyph) == (old.ascent, old.descent, old.em, old.glyph)
            left, _, right, _ = new.glyph.layout_bounds
            assert new.advance == pytest.approx((right - left + .08) * new.em + style.stroke_width_mm)
        else:
            assert new == old
    _, gaps = justify_line(after, sum(box.advance for box in after) + 30)
    assert sum(gaps) == pytest.approx(30)
    for text in ('2024', '12', 'A4', 'v6.3.1'):
        start = TEXT.index(text)
        assert not any(gaps[start:start + len(text) - 1])


def test_package_round_trip_and_layout_exclusions(tmp_path):
    source = SourceSession(TEXT + '\n\n# 2024\n\n|2024|\n|---|\n|12|\n\n`2024` $2024$\n')
    parsed = parse_markdown(source)
    page, style, assets = PageProfile(), StyleProfile(), resolver()
    legacy = FlowStyle(latin_spacing='handwriting')
    compact = replace(legacy, digits_follow_latin=True)
    capture = replace(compact, latin_spacing='capture')

    def render(document, resolver, flow):
        return layout_markdown(document, resolver, page=page, style=style, flow=flow)

    full = render(parsed, assets, legacy)
    tight = render(parsed, assets, compact)
    assert full.exportable and tight.exportable
    for a, b in zip(full.fragments, tight.fragments, strict=True):
        assert (a.occurrence_id, a.asset_id, a.glyph_em_mm) == (b.occurrence_id, b.asset_id, b.glyph_em_mm)
        if a.span.start >= len(TEXT):
            assert a == b
    assert full.fragments[1].x_mm > tight.fragments[1].x_mm
    assert render(parsed, assets, capture).fragments == render(parsed, assets, FlowStyle()).fragments

    for flow in (legacy, compact, capture):
        path = tmp_path / f'{flow.schema_version}-{flow.latin_spacing}.inkdoc'
        save_package(path, source, assets, page, style, flow=flow)
        with ZipFile(path) as archive:
            stored = json.loads(archive.read('styles.json'))['flow']
        assert ('digits_follow_latin' in stored) == flow.digits_follow_latin
        loaded = load_package(path)
        assert loaded.flow == flow
        assert render(parse_markdown(loaded.session), loaded.resolver, loaded.flow) == render(parsed, assets, flow)
