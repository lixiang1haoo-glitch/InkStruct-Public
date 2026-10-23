import copy
import json
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest
from test_pipeline import make_structure
from test_source_generation_entry import fixture

from inkstruct.generate import DeterministicGenerator, generate_run
from inkstruct.reviewed_geometry import (
    REVIEWED_POLICY,
    ReviewedGeometryProcessor,
    geometry_identity,
)
from inkstruct.schemas import StyleProfile
from inkstruct.trajectory_experiment import assemble, invariants


def processor_fixture(tmp_path):
    repo = make_structure(tmp_path)
    graph = repo.get('十')
    profile = StyleProfile('style_profile_v4', 'fixed', 'writer', 'fixed', 'none', 0, 0, {}, {}, {})
    baseline = DeterministicGenerator(profile, 'fixture')
    base = assemble(baseline.generate(graph), {
        0: {'points': [(.2, .3), (.5, .5)], 'pressure': [.4, .5], 'time': [0, 100]},
        1: {'points': [(.2, .49), (.8, .49)], 'pressure': [.3, .6], 'time': [0, 100]}}, 'fixture')
    config = {'policy': REVIEWED_POLICY, 'outlines': [],
              'translation_parameters': {'max_shift': .06, 'step': .002, 'clearance': .002},
              'crossings': [{'character': '十', 'writer_id': 'writer', 'source_version': 'fixture',
                            'pairs': [['s1', 's2']], 'geometry_sha256': geometry_identity(base)}]}
    path = tmp_path/'repairs.json'
    path.write_text(json.dumps(config))
    processor = ReviewedGeometryProcessor(baseline, repo, path, tmp_path/'graphics.txt', tmp_path/'dictionary.txt')
    return processor, graph, base


def test_only_hash_matched_reviewed_geometry_is_moved_and_second_pass_is_noop(tmp_path):
    processor, graph, base = processor_fixture(tmp_path)
    before = asdict(base)
    result, report = processor.apply(base, graph)
    assert report['applied'] and not invariants(result, graph)
    assert asdict(base) == before
    for old, new in zip(base.strokes, result.strokes, strict=True):
        np.testing.assert_allclose(np.diff([(p.x, p.y) for p in old.points], axis=0),
                                   np.diff([(p.x, p.y) for p in new.points], axis=0), atol=1e-14)
        assert [(p.t_ms, p.pressure) for p in old.points] == [(p.t_ms, p.pressure) for p in new.points]
    unchanged, second = processor.apply(result, graph)
    assert unchanged is result and not second['applied']
    changed = copy.deepcopy(base)
    changed.strokes[0].points[0].x += .000001
    unchanged, rejected = processor.apply(changed, graph)
    assert unchanged is changed and 'differs' in rejected['events'][0]['reason']


def test_outline_repairs_are_local_and_leave_captured_strokes_untouched(tmp_path):
    processor, graph, base = processor_fixture(tmp_path)
    processor.config['crossings'] = []
    tiny = assemble(base, {0: {'points': [(.15, .1), (.151, .1)], 'pressure': [.4, .5], 'time': [0, 100]}}, 'tiny')
    proposed = assemble(base, {0: {'points': [(.15, .1), (.45, .1)], 'pressure': [.4, .5], 'time': [0, 200]}}, 'estimate')
    processor.overrides = {'十': (graph, {'test': 'source'}, {'stroke_id': 's1'})}
    processor.baseline = SimpleNamespace(generate=lambda _: proposed)
    result, report = processor.apply(tiny, graph)
    assert report['changed_geometry_ids'] == ['s1']
    assert [(p.x, p.y, p.pressure) for p in result.strokes[1].points] == [(p.x, p.y, p.pressure) for p in tiny.strokes[1].points]
    assert not invariants(result, graph)
    tiny.strokes[0].style_source = 'observed-raw'
    unchanged, protected = processor.apply(tiny, graph)
    assert unchanged is tiny and protected['events'][0]['reason'] == 'captured source stroke protected'
    unchanged, normal = processor.apply(proposed, graph)
    assert unchanged is proposed and 'not severely collapsed' in normal['events'][0]['reason']


def test_unresolvable_outline_conflict_rolls_back_entire_proposal(tmp_path):
    processor, graph, base = processor_fixture(tmp_path)
    processor.config['crossings'] = []
    tiny = assemble(base, {0: {'points': [(.5, .3), (.501, .3)], 'pressure': [.5, .5], 'time': [0, 100]}}, 'tiny')
    crossing = assemble(base, {0: {'points': [(.5, .1), (.5, .9)], 'pressure': [.5, .5], 'time': [0, 200]}}, 'cross')
    processor.overrides = {'十': (graph, {}, {'stroke_id': 's1'})}
    processor.baseline = SimpleNamespace(generate=lambda _: crossing)
    result, report = processor.apply(tiny, graph)
    assert result is tiny and not report['applied']
    assert 'unresolved' in report['events'][0]['reason']


def test_repair_run_resume_identity_and_failed_write_accounting(tmp_path, monkeypatch):
    _, repo, _, _, paths = fixture(tmp_path)
    class DummyProcessor:
        def __init__(self, *args):
            self.identity = {'policy': 'fixture'}
        def apply(self, base, graph):
            return base, {'applied': False, 'events': [], 'geometry_audit': {}}
    monkeypatch.setattr('inkstruct.reviewed_geometry.ReviewedGeometryProcessor', DummyProcessor)
    options = {'output_root': tmp_path/'runs', 'run_id': 'test', 'png': False, 'reviewed_geometry': True}
    manifest, run = generate_run('writer', ['池'], repo, paths[0], **options)
    file = run/'trajectories/U+6C60.json'
    before = file.read_bytes()
    assert manifest['geometry_repairs']['changed_characters'] == []
    generate_run('writer', ['池'], repo, paths[0], **options)
    assert file.read_bytes() == before
    manifest_bytes = (run/'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='identity'):
        generate_run('writer', ['池'], repo, paths[0], **{**options, 'reviewed_geometry': False})
    assert (run/'manifest.json').read_bytes() == manifest_bytes
    with pytest.raises(ValueError, match='adaptive'):
        generate_run('writer', ['池'], repo, paths[0], **{**options, 'component_strength': .8})
    def fail(*args):
        raise OSError('fixture write failure')
    monkeypatch.setattr('inkstruct.generate._write_glyph', fail)
    failed, _ = generate_run('writer', ['池'], repo, paths[0], **{**options, 'run_id': 'failed'})
    assert failed['completed_count'] == 0 and failed['geometry_repairs']['by_character'] == {}


def test_reviewed_crossing_never_moves_a_capture_even_when_geometry_hash_matches(tmp_path):
    processor, graph, base = processor_fixture(tmp_path)
    base.strokes[0].style_source = 'source-raw'
    result, report = processor.apply(base, graph)
    assert result is base and not report['applied']
    assert report['events'][0]['reason'] == 'captured source stroke protected'


def test_database_source_mismatch_is_rejected_before_a_repair_can_run(tmp_path):
    import hashlib
    processor, graph, _ = processor_fixture(tmp_path)
    graphics = json.loads((tmp_path/'graphics.txt').read_text())
    config = copy.deepcopy(processor.config)
    config['outlines'] = [{'character': '十', 'stroke_id': 's1', 'source_version': 'fixture',
        'algorithm': 'single_strip_outline_median_v1', 'cross_sections': 40,
        'outline_sha256': hashlib.sha256(graphics['strokes'][0].encode()).hexdigest(),
        'median_sha256': hashlib.sha256(json.dumps(graphics['medians'][0], separators=(',', ':')).encode()).hexdigest()}]
    config_path = tmp_path/'mismatched.json'
    config_path.write_text(json.dumps(config))
    graph.strokes[0].median[0] = (.01, .01)
    repository = SimpleNamespace(get=lambda _: graph)
    with pytest.raises(ValueError, match='centerlines differ'):
        ReviewedGeometryProcessor(processor.baseline, repository, config_path,
                                  tmp_path/'graphics.txt', tmp_path/'dictionary.txt')
