import copy
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest
from test_pipeline import make_structure

from inkstruct.component_views import expand_views
from inkstruct.generate import DeterministicGenerator
from inkstruct.outline_median import flatten_outline, propose_strip_median
from inkstruct.schemas import ComponentNode, StyleProfile
from inkstruct.topology_repair import repair_reviewed_crossings
from inkstruct.trajectory_experiment import assemble, crossing_pairs


def test_nested_view_requires_ordered_correspondence_and_never_mutates_source(tmp_path):
    graph = make_structure(tmp_path).get('十')
    independent = copy.deepcopy(graph)
    independent.components[0].children_ids = ['a', 'b']
    independent.components[0].layout = '⿱'
    for i, identifier in enumerate(('a', 'b')):
        s = independent.strokes[i]
        independent.components.append(ComponentNode(identifier, f'root.{i}', identifier, identifier,
            'top' if i == 0 else 'bottom', independent.components[0].component_id, [],
            [s.stroke_id], s.bbox, None, 1.))
    graph.character = '甲'
    root = graph.components[0]
    root.children_ids = ['host']
    graph.components.append(ComponentNode('host', 'root.0', '十', '十', 'right', root.component_id, [],
                                          [s.stroke_id for s in graph.strokes], root.bbox, None, 1.))
    before = asdict(graph)
    repository = SimpleNamespace(get=lambda _: independent)
    result = expand_views(graph, repository, allowed=('十',))
    assert result.diagnostics[0]['expanded']
    assert asdict(graph) == before
    assert [asdict(s) for s in result.graph.strokes] == [asdict(s) for s in graph.strokes]
    assert result.graph.components[1].children_ids == ['host::view::a', 'host::view::b']
    independent.strokes = independent.strokes[:1]
    rejected = expand_views(graph, repository, allowed=('十',))
    assert not rejected.diagnostics[0]['expanded']
    assert asdict(rejected.graph) == before


def test_reviewed_translation_removes_crossing_without_changing_pen_shape(tmp_path):
    graph = make_structure(tmp_path).get('十')
    profile = StyleProfile('style_profile_v4', 'fixed', 'writer', 'fixed', 'none', 0, 0, {}, {}, {})
    base = DeterministicGenerator(profile, 'fixture').generate(graph)
    replacements = {0: {'points': [(.2, .3), (.5, .5)], 'pressure': [.4, .5], 'time': [0, 100]},
                    1: {'points': [(.2, .49), (.8, .49)], 'pressure': [.3, .6], 'time': [0, 100]}}
    base = assemble(base, replacements, 'fixture')
    untouched = asdict(base)
    repaired, report = repair_reviewed_crossings(base, graph, [('s1', 's2')])
    assert report['applied'] and not report['after_reviewed_crossings']
    assert not crossing_pairs([[(p.x, p.y) for p in s.points] for s in repaired.strokes])
    assert asdict(base) == untouched
    for old, new in zip(base.strokes, repaired.strokes, strict=True):
        assert np.allclose(np.diff([(p.x, p.y) for p in old.points], axis=0),
                           np.diff([(p.x, p.y) for p in new.points], axis=0))
        assert [(p.t_ms, p.pressure) for p in old.points] == [(p.t_ms, p.pressure) for p in new.points]
    again, second = repair_reviewed_crossings(repaired, graph, [('s1', 's2')])
    assert again is repaired and not second['applied']


def test_normal_short_strokes_and_complex_outlines_are_not_automatically_extended():
    path = 'M 0 0 L 100 0 L 100 10 L 0 10 Z'
    recovered, report = propose_strip_median(path, [(1, 5), (0, 5)])
    assert report['proposed_length'] > 90
    assert recovered[0][0] > recovered[-1][0]
    assert all(0 <= x <= 100 and 0 <= y <= 10 for x, y in recovered)
    with pytest.raises(ValueError, match='near-empty'):
        propose_strip_median(path, [(90, 5), (10, 5)])
    with pytest.raises(ValueError, match='multiple contours'):
        flatten_outline(path + ' M 20 20 L 30 20 L 30 30 Z')
    with pytest.raises(ValueError, match='elongated'):
        propose_strip_median('M 0 0 L 10 0 L 10 10 L 0 10 Z', [(1, 5), (0, 5)])


def test_fast_candidate_selection_matches_exhaustive_choice_and_reports_skipped_candidates(tmp_path):
    from inkstruct.contextual_trajectory import choose_component
    from inkstruct.fast_placement import choose_component_fast
    from inkstruct.schemas import SourceTrajectorySample, SourceTrajectoryStroke
    from inkstruct.source_trajectory import arc_parameters

    graph = make_structure(tmp_path).get('十')
    profile = StyleProfile('style_profile_v4', 'fixed', 'writer', 'fixed', 'none', 0, 0, {}, {}, {})
    base = DeterministicGenerator(profile, 'fixture').generate(graph)
    sources, candidates = {}, []
    for character, offset in [('甲', 0.), ('乙', .01)]:
        source = []
        for s in base.strokes:
            p = [(v.x + offset * (s.order - 1), v.y) for v in s.points]
            source.append(SourceTrajectoryStroke(s.standard_stroke_id, s.order, p, [.5] * len(p),
                          list(range(len(p))), arc_parameters(p), .9))
        sources[character] = SourceTrajectorySample(character, character, character, 'declared', source)
        candidates.append({'character': character, 'sample_id': character, 'source_sha256': character,
                           'stroke_ids': [s.stroke_id for s in graph.strokes], 'score': offset})
    ids = [s.stroke_id for s in graph.strokes]
    slow, meta = choose_component(base, graph, ids, candidates, sources)
    fast, info = choose_component_fast(base, graph, ids, candidates, sources)
    assert asdict(fast) == asdict(slow)
    assert info['selected']['candidate'] == meta['selected']['candidate']
    assert info['fully_validated_candidates'] == 1
    assert info['candidates'][1]['accepted'] is None


def test_stale_source_override_is_rejected(tmp_path):
    from inkstruct.outline_median import apply_reviewed_override
    graph = make_structure(tmp_path).get('十')
    config = {'algorithm': 'single_strip_outline_median_v1', 'character': '十',
              'source_version': graph.source_version, 'stroke_id': 's1',
              'outline_sha256': 'wrong', 'median_sha256': 'wrong'}
    with pytest.raises(ValueError, match='source hashes changed'):
        apply_reviewed_override(graph, {'character': '十', 'strokes': ['M 0 0 L 10 0 L 10 1 Z'],
                                       'medians': [[[1, 0], [0, 0]]]}, {}, config)


def test_exemplar_index_limits_training_characters_and_excludes_all_target_repeats(tmp_path):
    from inkstruct.exemplar_index import ExemplarIndex
    from inkstruct.schemas import SourceTrajectorySample, SourceTrajectoryStroke
    from inkstruct.source_trajectory import arc_parameters

    fixture = make_structure(tmp_path).get('十')
    graphs, sources = {}, {}
    for character in ('甲', '乙', '丙'):
        graph = copy.deepcopy(fixture)
        graph.character = character
        root = graph.components[0]
        root.children_ids = ['right']
        root.layout = '⿰'
        graph.components.append(ComponentNode('right', 'root.1', '十', '十', 'right',
            root.component_id, [], [s.stroke_id for s in graph.strokes], root.bbox, None, 1.))
        graphs[character] = graph
        for repeat in range(2):
            identifier = f'{character}-{repeat}'
            strokes = [SourceTrajectoryStroke(s.stroke_id, s.order, s.median, [.5] * len(s.median),
                list(range(len(s.median))), arc_parameters(s.median), .9) for s in graph.strokes]
            sources[identifier] = SourceTrajectorySample(identifier, character, identifier, 'declared', strokes)
    profile = SimpleNamespace(writer_id='fixture', source_trajectories=sources)
    repository = SimpleNamespace(get=lambda c: graphs[c])
    index = ExemplarIndex(profile, repository, allowed_characters={'甲', '乙'})
    candidates = index.candidates(graphs['甲'], graphs['甲'].components[-1])
    assert {c['character'] for c in candidates} == {'乙'}
    assert {c['sample_id'] for c in candidates} == {'乙-0', '乙-1'}
