import json
from dataclasses import asdict

from test_pipeline import make_structure

from inkstruct.evaluate import evaluate_run
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry_audit import audit_glyph
from inkstruct.schemas import StyleProfile


def glyph_fixture(tmp_path):
    repository = make_structure(tmp_path)
    graph = repository.get('十')
    profile = StyleProfile('style_profile_v4', 'fixed', 'writer', 'fixed', 'none',
                           0, 0, {}, {}, {})
    glyph = DeterministicGenerator(profile, 'fixture').generate(graph)
    return repository, graph, glyph


def test_geometry_risks_are_independent_of_valid_protocol(tmp_path):
    _, graph, glyph = glyph_fixture(tmp_path)
    graph.strokes[0].median = [(0.1, 0.2), (0.9, 0.2)]
    graph.strokes[1].median = [(0.1, 0.8), (0.9, 0.8)]
    glyph.strokes[0].confidence = .2
    result = audit_glyph(glyph, graph)
    assert result['min_stroke_confidence'] == .2
    assert result['low_confidence_stroke_ids'] == [graph.strokes[0].stroke_id]
    assert any(w['kind'] == 'extra_strict_crossing' for w in result['geometry_warnings'])
    assert result['style_sources'][graph.strokes[0].stroke_id] == glyph.strokes[0].style_source


def test_tiny_source_and_generated_stroke_are_reported_separately(tmp_path):
    _, graph, glyph = glyph_fixture(tmp_path)
    graph.strokes[0].median = [(0.5, 0.5), (.504, .5)]
    for i, point in enumerate(glyph.strokes[0].points):
        point.x = .5 + i / (len(glyph.strokes[0].points) - 1) * .0008
        point.y = .5
    result = audit_glyph(glyph, graph)
    kinds = {w['kind'] for w in result['geometry_warnings']}
    assert {'tiny_source_stroke', 'near_point_stroke'} <= kinds
    assert result['stroke_lengths'][0]['output_length'] > 0


def test_protocol_rejects_cross_stroke_time_reversal(tmp_path):
    repository, _, glyph = glyph_fixture(tmp_path)
    run = tmp_path / 'run'
    (run / 'trajectories').mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps({'requested_count': 1, 'failed_count': 0}))
    value = asdict(glyph)
    start = value['strokes'][1]['points'][0]['t_ms']
    for point in value['strokes'][1]['points']:
        point['t_ms'] -= start
    (run / 'trajectories/U+5341.json').write_text(json.dumps(value))
    result = evaluate_run(run, repository)
    assert result['structural_failure_count'] == 1
    assert 'time is not monotonic' in result['failures'][0]['reason']
