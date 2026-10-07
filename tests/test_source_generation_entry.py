import copy
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_component_generation import make_graph

from inkstruct.cli import build_parser
from inkstruct.component_style import component_context_key
from inkstruct.exemplar_generation import SIMPLIFICATION_EPSILON, SourceComponentGenerator
from inkstruct.generate import DeterministicGenerator, generate_run
from inkstruct.schemas import SourceTrajectorySample, SourceTrajectoryStroke, StyleProfile
from inkstruct.source_trajectory import arc_parameters
from inkstruct.trajectory_experiment import (
    SharedTransform,
    invariants,
    point_distances,
    protected_indices,
)


def fixture(tmp_path):
    graphs = {c: make_graph(c, '也') for c in ('池', '沱')}
    database = tmp_path / 'fixture.db'
    database.write_text('fixture')
    repository = SimpleNamespace(get=lambda c: graphs[c], path=database,
        content_sha256=lambda: 'fixture-structure', metadata=lambda: {'source_version': 'fixture'})
    profile = StyleProfile('style_profile_v4', 'fixture', 'writer', 'fixed', 'none', 0, 0, {}, {}, {})
    baseline = DeterministicGenerator(profile, 'fixture')
    source_profile = copy.deepcopy(profile)
    source_profile.trajectory_schema = 'source_trajectory_v1'
    source_profile.build_identity = {'structure_sha256': repository.content_sha256()}
    for char, graph in graphs.items():
        glyph = baseline.generate(graph)
        strokes = []
        for i, s in enumerate(glyph.strokes):
            points = [(p.x, p.y) for p in s.points]
            # Reverse capture order across strokes, while each pen-down remains monotonic.
            times = [(7 - i) * 1000 + j * 3 for j in range(len(points))]
            strokes.append(SourceTrajectoryStroke(s.standard_stroke_id, len(glyph.strokes) - i,
                points, [.4 + j * .001 for j in range(len(points))], times, arc_parameters(points), .9))
        sample = SourceTrajectorySample(char, char, 'a' * 64, 'corrected', strokes)
        source_profile.source_trajectories[char] = sample
    paths = []
    for name, value in [('base', profile), ('source', source_profile)]:
        path = tmp_path / f'{name}.json'
        path.write_text(json.dumps(asdict(value)))
        paths.append(path)
    return graphs, repository, baseline, source_profile, paths


def test_raw_and_simplified_use_same_whole_donors_and_keep_geometry_time_contract(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    raw, raw_meta = SourceComponentGenerator(baseline, profile, repo).generate(graphs['池'])
    simple, simple_meta = SourceComponentGenerator(baseline, profile, repo, mode='source-simplified').generate(graphs['池'])
    assert raw_meta['accepted_component_count'] == simple_meta['accepted_component_count'] == 2
    assert not invariants(raw, graphs['池']) and not invariants(simple, graphs['池'])
    for left, right in zip(raw_meta['components'], simple_meta['components'], strict=True):
        assert left['selection']['selected'] == right['selection']['selected']
        candidate = left['selection']['selected']['candidate']
        assert candidate['character'] == '沱'
        transform = SharedTransform(**left['selection']['selected']['transform'])
        source_map = {s.standard_stroke_id: s for s in profile.source_trajectories['沱'].strokes}
        for target_id, source_id, kept in zip(left['target_stroke_ids'], candidate['stroke_ids'],
                                             right['retained_source_indices'], strict=True):
            source = source_map[source_id]
            a = next(s for s in raw.strokes if s.standard_stroke_id == target_id)
            b = next(s for s in simple.strokes if s.standard_stroke_id == target_id)
            np.testing.assert_allclose([(p.x, p.y) for p in a.points], transform.apply(source.points), atol=1e-12)
            assert [p.pressure for p in a.points] == source.pressure
            assert [p.pressure for p in b.points] == [source.pressure[i] for i in kept]
            assert protected_indices(source.points).issubset(kept)
            distance = point_distances([(p.x, p.y) for p in a.points], [(p.x, p.y) for p in b.points])
            assert distance.max() <= SIMPLIFICATION_EPSILON + 1e-12
    assert sum(len(s.points) for s in simple.strokes) < sum(len(s.points) for s in raw.strokes)
    assert raw.canvas_fit['source_placements_verified_in_bounds']


def test_no_donor_preserves_every_baseline_field(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    output, report = SourceComponentGenerator(baseline, profile, repo,
        allowed_characters={'池'}).generate(graphs['池'])
    assert asdict(output) == asdict(baseline.generate(graphs['池']))
    assert report['accepted_component_count'] == 0 and report['fallback_reason']


def test_source_run_resume_is_exact_and_changed_mode_or_training_range_is_rejected(tmp_path):
    _, repo, _, _, paths = fixture(tmp_path)
    whitelist = tmp_path / 'train.txt'
    whitelist.write_text('沱')
    args = ('writer', ['池'], repo, paths[0])
    options = {'output_root': tmp_path / 'outputs', 'run_id': 'source', 'png': False,
        'trajectory_mode': 'source-raw', 'source_profile_path': paths[1], 'source_characters_path': whitelist}
    first, run = generate_run(*args, **options)
    trajectory = run / 'trajectories/U+6C60.json'
    original = trajectory.read_bytes()
    second, _ = generate_run(*args, **options)
    assert trajectory.read_bytes() == original
    assert second['source_components']['by_character'] == first['source_components']['by_character']
    manifest = (run / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='identity'):
        generate_run(*args, **{**options, 'trajectory_mode': 'source-simplified'})
    whitelist.write_text('池')
    with pytest.raises(ValueError, match='identity'):
        generate_run(*args, **options)
    assert trajectory.read_bytes() == original and (run / 'manifest.json').read_bytes() == manifest


def test_incompatible_sources_and_implicit_activation_are_rejected(tmp_path):
    _, repo, baseline, source, paths = fixture(tmp_path)
    args = ('writer', ['池'], repo, paths[0])
    with pytest.raises(ValueError, match='explicit source'):
        generate_run(*args, source_profile_path=paths[1])
    with pytest.raises(ValueError, match='requires --source-profile'):
        generate_run(*args, trajectory_mode='source-raw')
    with pytest.raises(ValueError, match='neural'):
        generate_run(*args, trajectory_mode='source-raw', source_profile_path=paths[1], checkpoint=Path('absent'))
    source.writer_id = 'different'
    with pytest.raises(ValueError, match='writer'):
        SourceComponentGenerator(baseline, source, repo)
    source.writer_id = 'writer'
    source.build_identity['structure_sha256'] = 'changed'
    with pytest.raises(ValueError, match='structure database'):
        SourceComponentGenerator(baseline, source, repo)


def test_cli_defaults_to_legacy_and_legacy_payload_has_no_source_metadata(tmp_path):
    _, repo, baseline, _, paths = fixture(tmp_path)
    args = build_parser().parse_args(['generate', '--writer', 'writer', '--text', '池'])
    assert args.trajectory_mode == 'legacy' and args.source_profile is None
    manifest, run = generate_run('writer', ['池'], repo, paths[0], output_root=tmp_path / 'out', png=False)
    assert 'source_components' not in manifest['run_identity']
    payload = json.loads((run / 'trajectories/U+6C60.json').read_text())
    assert 'source_components' not in payload
    # Round-trip JSON to compare tuple/list representations exactly as written.
    assert payload == json.loads(json.dumps(asdict(baseline.generate(repo.get('池')))))


def test_failed_delivery_does_not_count_as_successful_source_output(tmp_path, monkeypatch):
    _, repo, _, _, paths = fixture(tmp_path)

    def fail(*_args):
        raise OSError('fixture output unavailable')

    monkeypatch.setattr('inkstruct.generate._write_glyph', fail)
    manifest, _ = generate_run('writer', ['池'], repo, paths[0], output_root=tmp_path / 'out',
        png=False, trajectory_mode='source-raw', source_profile_path=paths[1])
    assert manifest['failed_count'] == 1 and manifest['completed_count'] == 0
    assert manifest['source_components']['characters_with_source_components'] == 0
    assert manifest['source_components']['by_character'] == {}


def test_cancelled_source_batch_can_resume_without_rewriting_completed_character(tmp_path):
    _, repo, _, _, paths = fixture(tmp_path)
    calls = iter([False, True])
    args = ('writer', ['池', '沱'], repo, paths[0])
    options = {'output_root': tmp_path / 'out', 'run_id': 'cancelled', 'png': False,
               'trajectory_mode': 'source-raw', 'source_profile_path': paths[1]}
    stopped, run = generate_run(*args, **options, cancelled=lambda: next(calls))
    original = (run / 'trajectories/U+6C60.json').read_bytes()
    assert stopped['status'] == 'cancelled' and stopped['completed_count'] == 1
    assert len(stopped['source_components']['by_character']) == 1
    resumed, _ = generate_run(*args, **options)
    assert resumed['status'] == 'completed' and resumed['completed_count'] == 2
    assert len(resumed['source_components']['by_character']) == 2
    assert (run / 'trajectories/U+6C60.json').read_bytes() == original


def test_accepted_source_strokes_report_actual_component_context(tmp_path, monkeypatch):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    original = baseline.generate

    def stale_parent_context(graph):
        glyph = original(graph)
        for stroke in glyph.strokes:
            stroke.component_key = 'legacy_parent_context'
        return glyph

    monkeypatch.setattr(baseline, 'generate', stale_parent_context)
    output, report = SourceComponentGenerator(baseline, profile, repo).generate(graphs['池'])
    assert report['accepted_component_count'] == 2
    expected = {sid: component_context_key(graphs['池'], component)
                for component in graphs['池'].components if not component.children_ids
                for sid in component.stroke_ids}
    assert all(s.component_key == expected[s.standard_stroke_id] for s in output.strokes)
