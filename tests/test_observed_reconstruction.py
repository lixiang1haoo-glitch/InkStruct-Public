import copy
import json
from dataclasses import asdict

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.cli import build_parser
from inkstruct.exemplar_generation import SIMPLIFICATION_EPSILON, SourceComponentGenerator
from inkstruct.generate import generate_run
from inkstruct.observed_reconstruction import ObservedSourceGenerator
from inkstruct.trajectory_experiment import (
    crossing_pairs,
    invariants,
    point_distances,
    protected_indices,
)


def test_complete_capture_reconstruction_keeps_all_coordinates_pressure_and_order(tmp_path):
    graphs, repo, base, profile, _ = fixture(tmp_path)
    capture = profile.source_trajectories['池']
    before = asdict(capture)
    output, meta = ObservedSourceGenerator(base, profile, repo).generate(graphs['池'])
    assert meta['observed_reconstruction']['used']
    assert not invariants(output, graphs['池'])
    assert asdict(capture) == before
    for stroke, original in zip(output.strokes, capture.strokes, strict=True):
        assert [(p.x, p.y) for p in stroke.points] == original.points
        assert [p.pressure for p in stroke.points] == original.pressure
        np.testing.assert_array_equal(np.diff([p.t_ms for p in stroke.points]), np.diff(original.t_ms))
    assert output.strokes[0].points[-1].t_ms < output.strokes[1].points[0].t_ms
    assert output.canvas_fit['source_points_unrounded']


def test_simplified_preserves_same_source_topology_protected_points_and_error_bound(tmp_path):
    graphs, repo, base, profile, _ = fixture(tmp_path)
    raw, raw_meta = ObservedSourceGenerator(base, profile, repo).generate(graphs['池'])
    simplified, meta = ObservedSourceGenerator(base, profile, repo, mode='source-simplified').generate(graphs['池'])
    assert raw_meta['components'][0]['selection']['selected'] == meta['components'][0]['selection']['selected']
    left = [[(p.x, p.y) for p in s.points] for s in raw.strokes]
    right = [[(p.x, p.y) for p in s.points] for s in simplified.strokes]
    assert crossing_pairs(left) == crossing_pairs(right)
    for i, (a, b) in enumerate(zip(left, right, strict=True)):
        kept = meta['components'][0]['retained_source_indices'][i]
        assert protected_indices(a).issubset(kept)
        assert b == [a[j] for j in kept]
        assert point_distances(a, b).max() <= SIMPLIFICATION_EPSILON + 1e-12


def test_whitelist_excludes_entire_target_character_before_reconstruction(tmp_path):
    graphs, repo, base, profile, _ = fixture(tmp_path)
    profile.source_trajectories['duplicate'] = copy.deepcopy(profile.source_trajectories['池'])
    original, _ = SourceComponentGenerator(base, profile, repo, allowed_characters={'沱'}).generate(graphs['池'])
    reconstructed, meta = ObservedSourceGenerator(base, profile, repo, allowed_characters={'沱'}).generate(graphs['池'])
    assert asdict(original) == asdict(reconstructed)
    assert not meta['observed_reconstruction']['used'] and not meta['observed_reconstruction']['checked_sources']
    assert all(c['selection']['selected']['candidate']['character'] == '沱' for c in meta['components'])


@pytest.mark.parametrize('invalid', ['confidence', 'nonfinite', 'pressure', 'time', 'mapping', 'ambiguous'])
def test_rejected_capture_returns_existing_cross_character_result(tmp_path, invalid):
    graphs, repo, base, profile, _ = fixture(tmp_path)
    generator = ObservedSourceGenerator(base, profile, repo)
    original, _ = SourceComponentGenerator(base, profile, repo).generate(graphs['池'])
    capture = profile.source_trajectories['池']
    if invalid == 'confidence':
        capture.strokes[0].confidence = .1
    elif invalid == 'nonfinite':
        capture.strokes[0].points[0] = (float('nan'), 0.)
    elif invalid == 'pressure':
        capture.strokes[0].pressure[0] = 1.5
    elif invalid == 'time':
        capture.strokes[0].t_ms[1] = capture.strokes[0].t_ms[0]-1
    elif invalid == 'mapping':
        capture.strokes[0].standard_stroke_id = capture.strokes[1].standard_stroke_id
    else:
        capture.stroke_order_status = 'ambiguous'
    result, meta = generator.generate(graphs['池'])
    assert asdict(result) == asdict(original)
    assert not meta['observed_reconstruction']['used']
    assert meta['observed_reconstruction']['checked_sources'][0]['rejection_reason']


def test_run_identity_resume_and_explicit_activation(tmp_path):
    _, repo, _, _, paths = fixture(tmp_path)
    options = {'output_root': tmp_path / 'runs', 'run_id': 'observed', 'png': False,
               'trajectory_mode': 'source-raw', 'source_profile_path': paths[1], 'source_observed': True}
    first, run = generate_run('writer', ['池'], repo, paths[0], **options)
    trajectory = run / 'trajectories/U+6C60.json'
    expected = trajectory.read_bytes()
    assert first['source_components']['by_character']['池']['observed_reconstruction']['used']
    generate_run('writer', ['池'], repo, paths[0], **options)
    assert trajectory.read_bytes() == expected
    manifest = (run / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='identity'):
        generate_run('writer', ['池'], repo, paths[0], **{**options, 'source_observed': False})
    assert (run / 'manifest.json').read_bytes() == manifest and trajectory.read_bytes() == expected
    assert json.loads(expected)['source_components']['run_identity']['observed_reconstruction']
    with pytest.raises(ValueError, match='explicit source'):
        generate_run('writer', ['池'], repo, paths[0], source_observed=True)
    parsed = build_parser().parse_args(['generate', '--writer', 'writer', '--text', '池'])
    assert not parsed.source_observed
