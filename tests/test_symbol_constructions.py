import copy
import json

import pytest
from test_symbol_provider import specimen

from inkstruct.fonts.core import FontPackage, decode
from inkstruct.fonts.importer import build_font
from inkstruct.fonts.symbol_rules import extend_font


def sources(folder):
    folder.mkdir()
    for c in '。C−≈':
        value = specimen(c, 'source-' + str(ord(c)))
        if c == 'C':
            value['variant'] = {'letter_style': 'upright'}
        if c == '≈':
            second = copy.deepcopy(value['strokes'][0])
            second['order'] = 2
            for p in second['points']:
                p['y'] += 10
                p['t_ms'] += 100
            value['strokes'].append(second)
            value['actual_stroke_count'] = 2
        (folder/f'{ord(c)}.json').write_text(json.dumps(value), encoding='utf-8')


def test_new_font_rules_exact_reuse_two_waves_and_composite(tmp_path):
    folder = tmp_path/'sources'
    sources(folder)
    font_path = tmp_path/'new.inkfont'
    build_font(font_path, writer='fixture', name='rules', symbols=folder)
    font = FontPackage(font_path)
    font.verify()
    assert {c: len(font.pools[c]) for c in '℃–～'} == {'℃': 1, '–': 1, '～': 2}
    minus = decode(next(font.glyphs('−')).original_json)
    dash = decode(next(font.glyphs('–')).original_json)
    assert minus['trajectory']['strokes'] == dash['trajectory']['strokes']
    assert minus['metrics'] == dash['metrics']
    waves = [decode(g.original_json) for g in font.glyphs('～')]
    assert {g['summary']['symbol_construction']['sources'][0]['stroke_orders'][0] for g in waves} == {1, 2}
    assert all(len(g['trajectory']['strokes']) == 1 for g in waves)
    celsius = decode(next(font.glyphs('℃')).original_json)
    assert len(celsius['summary']['symbol_construction']['sources']) == 2
    assert celsius['summary']['source_kind'] == 'composed'
    assert celsius['summary']['author_source_status'] == 'complete'
    # Existing target candidates always take precedence; no silent replacement.
    with pytest.raises(ValueError, match='没有可添加'):
        extend_font(font_path, tmp_path/'again.inkfont', name='again')
