import copy
import math

import pytest
from test_symbol_provider import specimen

from inkstruct.fonts.core import semantic_hash, trajectory_hashes, validate_summary
from inkstruct.fonts.importer import make_symbol
from inkstruct.fonts.symbol_rules import _recorded_math_constructions
from inkstruct.math.parser import symbol_class


def candidates(chars=('−', '−', '−', '。', '：', ':')):
    records, values = [], {}
    for index, char in enumerate(chars):
        raw = specimen(char, str(index))
        raw['guides']['math_axis_em'] = .4 if char == '−' else .25
        points = [(20, 45), (35, 44-index*.1), (60, 45)] if char == '−' else [
            (30, 45), (35, 40), (40, 45), (35, 50), (30, 45)]
        raw['strokes'][0]['points'] = [{'x': x, 'y': y, 't_ms': i*10, 'pressure': .2+i*.1,
                                      'pen_state': 'down' if i < len(points)-1 else 'end'}
                                      for i, (x, y) in enumerate(points)]
        from inkstruct.fonts.core import encoded
        trajectory, metrics, summary = make_symbol(encoded(raw), raw)
        cid = f'candidate-{index}'
        record = {'candidate_id': cid, 'character': char, 'enabled': True,
                  **trajectory_hashes(trajectory), 'metrics_id': semantic_hash(metrics),
                  'source_summary_hash': semantic_hash(summary)}
        records.append(record)
        values[cid] = (trajectory, metrics, summary)
    return records, values


def generate(records, values, diagnostics=None):
    return list(_recorded_math_constructions(records, lambda r: values[r['candidate_id']], diagnostics))


@pytest.mark.parametrize('count', [1, 2, 3, 5])
def test_star_bounded_deterministic_distinct_pairing_and_full_dynamic_ink(count):
    records, values = candidates(('−',)*count)
    before = copy.deepcopy(values)
    made = generate(records, values)
    assert made == generate(list(reversed(records)), values)
    stars = [v for v in made if v[0]['character'] == '*']
    math_stars = [v for v in made if v[0]['character'] == '∗']
    assert len(stars) == len(math_stars) == count
    for (trajectory, metrics, summary, _), other in zip(stars, math_stars, strict=True):
        assert trajectory['strokes'] == other[0]['strokes']
        assert summary['symbol_construction']['construction_id'] == other[2]['symbol_construction']['construction_id']
        construction = summary['symbol_construction']
        assert len({r['candidate_id'] for r in construction['sources']}) == min(3, count)
        assert construction['repeated_source_count'] == max(0, 3-count)
        assert summary['source_kind'] == 'composed' and 'capture_guides' not in summary
        validate_summary(summary, 3)
        for source, affine, shift, stroke in zip(construction['sources'], construction['component_affines_em'],
                                                construction['component_time_shifts_ms'], trajectory['strokes'], strict=True):
            original = values[source['candidate_id']][0]['strokes'][0]
            assert source['stroke_refs'] == [original['stroke_ref']]
            assert stroke['dynamic_origin']['time'] == 'inherited_retimed'
            for point, old in zip(stroke['points'], original['points'], strict=True):
                xx, xy, yx, yy, dx, dy = affine
                assert (point['x'], point['y']) == pytest.approx((xx*old['x']+xy*old['y']+dx,
                                                               yx*old['x']+yy*old['y']+dy))
                assert point['pressure'] == old['pressure']
                assert point['pen_state'] == old['pen_state']
                assert point['t_ms'] == old['t_ms']+shift
            a, b, c, d = (min(p['x'] for p in original['points']), min(p['y'] for p in original['points']),
                           max(p['x'] for p in original['points']), max(p['y'] for p in original['points']))
            assert (affine[0]*(a+c)/2+affine[1]*(b+d)/2+affine[4],
                    affine[2]*(a+c)/2+affine[3]*(b+d)/2+affine[5]) == pytest.approx(
                        (.04+construction['shortened_extent_em']/2, metrics['baseline']-.4))
        assert all(math.hypot(a[0], a[2]) < 1 for a in construction['component_affines_em'])
    assert values == before


@pytest.mark.parametrize('chars,expected', [(('：', ':'), '：'), ((':',), ':')])
def test_ratio_source_priority_complete_ink_uniform_transform_and_time_exact(chars, expected):
    records, values = candidates(chars)
    target = next(v for v in generate(records, values) if v[0]['character'] == '∶')
    trajectory, _, summary, _ = target
    construction = summary['symbol_construction']
    assert construction['sources'][0]['character'] == expected
    original = values[construction['sources'][0]['candidate_id']][0]
    assert len(trajectory['strokes']) == len(original['strokes'])
    affine = construction['component_affines_em'][0]
    assert affine[0] == affine[3] > 0 and affine[1] == affine[2] == 0
    assert construction['component_time_shifts_ms'] == [0]
    assert [p['t_ms'] for s in trajectory['strokes'] for p in s['points']] == [
        p['t_ms'] for s in original['strokes'] for p in s['points']]


def test_circ_uniform_circle_on_axis_and_parser_classes_unchanged():
    records, values = candidates(('。',))
    trajectory, metrics, summary, _ = next(v for v in generate(records, values) if v[0]['character'] == '∘')
    ys = [p['y'] for s in trajectory['strokes'] for p in s['points']]
    assert (min(ys)+max(ys))/2 == pytest.approx(metrics['baseline']-.25)
    assert summary['symbol_construction']['sources'][0]['character'] == '。'
    assert symbol_class('∘') == 'ord' and symbol_class('∗') == 'bin'
    assert symbol_class('∶') == 'rel' and symbol_class(':') == 'punct'


def test_existing_targets_and_missing_rejected_degenerate_sources_fail_closed():
    records, values = candidates(('−', '。', '：', ':', '*', '∗', '∶', '∘'))
    assert not generate(records, values)
    records, values = candidates(('−', '。', '：'))
    values['candidate-0'][2]['review_status'] = 'rejected'
    values['candidate-1'][0]['strokes'][0]['points'] = [{'x': 0, 'y': 0, 't_ms': 0}]
    values['candidate-2'][2]['source_kind'] = 'generated'
    diagnostics = []
    assert not generate(records, values, diagnostics)
    assert {d['target'] for d in diagnostics} == {'*/∗', '∘', '∶'}
    assert any('degenerate' in d['reason'] for d in diagnostics)
    assert generate([], {}) == []


def test_source_warnings_partitions_gaps_and_machine_points_not_erased():
    records, values = candidates(('：',))
    summary = values['candidate-0'][2]
    summary.update(author_strokes=[], reference_strokes=[1], author_source_status='reference_only',
                   warnings=['original warning'], gaps=[{'order': 1, 'reason': 'reference gap'}])
    made = generate(records, values)[0]
    assert made[2]['warnings'] == ['original warning']
    assert made[2]['gaps'] == summary['gaps']
    assert made[2]['author_source_status'] == 'reference_only'


@pytest.mark.parametrize('axis', [True, '0.25', -1, float('nan')])
def test_constructed_axis_is_validated(axis):
    records, values = candidates(('。',))
    summary = generate(records, values)[0][2]
    summary['symbol_construction']['math_axis_em'] = axis
    with pytest.raises(ValueError, match='数学轴'):
        validate_summary(summary, 1)


def test_ineligible_fullwidth_colon_falls_back_without_unicode_replacement():
    records, values = candidates(('：', ':'))
    values['candidate-0'][2]['review_status'] = 'rejected'
    diagnostics = []
    made = generate(records, values, diagnostics)
    assert len(made) == 1 and made[0][0]['character'] == '∶'
    assert made[0][2]['symbol_construction']['sources'][0]['character'] == ':'
    assert any(d['target'] == '∶' and d['source_candidate'] == 'candidate-0' for d in diagnostics)
    assert [r['character'] for r in records] == ['：', ':']


def test_ratio_single_point_strokes_still_require_explicit_machine_adapter():
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.fonts.core import resolved_candidate
    from inkstruct.math.handwritten import measure_math
    from inkstruct.math.parser import parse_math

    records, values = candidates(('：',))
    trajectory, _, summary = values['candidate-0']
    first = copy.deepcopy(trajectory['strokes'][0])
    first['points'] = [first['points'][0]]
    second = copy.deepcopy(first)
    second.update(order=2, stroke_ref='stroke-2')
    second['points'][0]['y'] += .2
    second['points'][0]['t_ms'] += 100
    trajectory['strokes'] = [first, second]
    summary['author_strokes'] = [1, 2]
    records[0].update(**trajectory_hashes(trajectory), source_summary_hash=semantic_hash(summary))
    t, m, s, _ = generate(records, values)[0]
    record = {**records[0], 'candidate_id': 'ratio', 'character': '∶', 'letter_style': 'not_applicable', 'priority': 0,
              **trajectory_hashes(t), 'metrics_id': semantic_hash(m), 'source_summary_hash': semantic_hash(s)}
    glyph = resolved_candidate(record, t, m, s, {'writer_alias': 'fixture'})
    assert [len(stroke) for stroke in glyph.strokes] == [1, 1]
    assert glyph.machine_capability == 'point-adaptation-required'
    box = measure_math(parse_math('∶').root, AssetResolver(embedded=[glyph]), owner='math')
    assert not box.ready
    assert any(d.code == 'point-adaptation-required' for d in box.diagnostics)


def test_only_missing_star_identity_is_added_and_formula_star_semantics_unchanged():
    from inkstruct.math.parser import parse_math

    records, values = candidates(('−', '*'))
    made = generate(records, values)
    assert [v[0]['character'] for v in made] == ['∗']
    parsed = parse_math(r'1*2\circ3')
    assert parsed.valid
    symbols = [node.value for node in parsed.root.walk() if node.kind == 'Symbol']
    assert '∗' in symbols and '*' not in symbols and '∘' in symbols and '°' not in symbols


def test_independent_circ_keeps_legacy_placement_but_constructed_circ_tracks_math_axis():
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.fonts.core import resolved_candidate
    from inkstruct.math.handwritten import measure_math
    from inkstruct.math.parser import parse_math
    from inkstruct.math.style import MathStyle

    records, values = candidates(('∘', '。'))
    original, metrics, summary = values['candidate-0']
    summary['capture_guides']['math_axis_em'] = .4
    record = {**records[0], 'letter_style': 'not_applicable', 'priority': 0,
              'source_summary_hash': semantic_hash(summary)}
    independent = resolved_candidate(record, original, metrics, summary, {'writer_alias': 'fixture'})
    root = parse_math(r'\circ').root
    box = measure_math(root, AssetResolver(embedded=[independent]), owner='legacy', style=MathStyle(axis_em=.25))
    assert box.ready and box.glyphs[0].baseline_mm == 0
    t, m, s, _ = next(v for v in generate(records[1:], values) if v[0]['character'] == '∘')
    record = {**records[1], 'candidate_id': 'constructed-circ', 'character': '∘', 'priority': 0,
              'letter_style': 'not_applicable', **trajectory_hashes(t), 'metrics_id': semantic_hash(m),
              'source_summary_hash': semantic_hash(s)}
    composed = resolved_candidate(record, t, m, s, {'writer_alias': 'fixture'})
    box = measure_math(root, AssetResolver(embedded=[composed]), owner='new', style=MathStyle(axis_em=.4))
    assert box.ready and box.glyphs[0].baseline_mm == pytest.approx((.25-.4)*6)
