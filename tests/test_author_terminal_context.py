from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.author_terminal_context import (
    AuthorTerminalEvidence,
    circular_cue,
    prepare_author_terminal,
)
from inkstruct.contextual_trajectory import choose_component
from inkstruct.exemplar_index import ExemplarIndex, component_key, ordered_ids
from inkstruct.trajectory_experiment import invariants


def test_circular_character_balance_uncertainty_and_wrapping():
    a = circular_cue({'甲': [1+0j]*100, '乙': [1j], '丙': [1j], '丁': [1j]})
    b = circular_cue({'甲': [1+0j], '乙': [1j], '丙': [1j], '丁': [1j]})
    assert a == b and a['reference_characters'] == 4
    assert circular_cue({'甲': [1+0j], '乙': [-1+0j], '丙': [1j], '丁': [-1j]}) is None
    assert circular_cue({'甲': [1+0j]*100}) is None
    v = circular_cue({c: [np.exp(1j*angle)] for c, angle in zip('甲乙丙丁', [3.13, -3.13, 3.13, -3.13], strict=True)})
    np.testing.assert_allclose(v['vector'], [-1., 0.], atol=1e-12)


def test_target_and_donor_are_excluded_before_reference_prediction(tmp_path):
    graphs, _, baseline, profile, _ = fixture(tmp_path)
    target = graphs['池']
    component = next(c for c in target.components if c.path == 'root.0')
    donor_graph = graphs['沱']
    donor_component = next(c for c in donor_graph.components if c.path == 'root.0')
    chars = '池沱江河海湖洋流清'
    copies = {c: replace(donor_graph, character=c) for c in chars}
    sources = {c: replace(deepcopy(profile.source_trajectories['沱']), sample_id=c, character=c) for c in chars}
    entries = [{'character': c, 'sample_id': c, 'stroke_ids': ordered_ids(donor_graph, donor_component),
                'component_id': donor_component.component_id, 'source_sha256': sources[c].source_sha256} for c in chars]
    index = SimpleNamespace(by_key={component_key(target, component): entries}, sources=sources, graph=lambda c: copies[c])
    evidence = AuthorTerminalEvidence(index)
    base = baseline.generate(target)
    curves = [[(p.x, p.y) for p in s.points] for s in base.strokes[:3]]
    cue, detail = evidence.predict(target, component, curves, '沱')
    assert set(detail['ranked_reference_characters']).isdisjoint({'池', '沱'})
    assert all(e['character'] not in {'池', '沱'} for e in detail['used_sources'])
    for entry in evidence.entries[component_key(target, component)]:
        if entry['candidate']['character'] in {'池', '沱'}:
            entry['raw'] = [[(float('nan'), float('nan'))]]*3
    changed, _ = evidence.predict(target, component, curves, '沱')
    assert changed == cue
    assert all(c is not None for c in cue['author'])


def test_unsupported_and_disabled_paths_match_D_exactly(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    candidates = index.candidates(graph, component)
    base = baseline.generate(graph)
    expected, _ = choose_component(base, graph, ordered_ids(graph, component), candidates, index.sources)
    prepared = prepare_author_terminal(base, graph, component, candidates, AuthorTerminalEvidence(index))
    for weight in (0., .08):
        for mode in ('author', 'public_residual'):
            output, report = prepared.select(weight, mode)
            assert asdict(output) == asdict(expected)
            assert not invariants(output, graph)
            assert report['context_fallback_reason']
    for invalid in (-1., float('nan'), float('inf')):
        with pytest.raises(ValueError):
            prepared.select(invalid)
    with pytest.raises(ValueError):
        prepared.select(.01, 'target_original')


def test_supported_reranking_changes_only_complete_candidate_choice(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    base = baseline.generate(graph)
    prepared = prepare_author_terminal(base, graph, component, index.candidates(graph, component), AuthorTerminalEvidence(index))
    glyph, record = prepared.alternatives[0]
    alternate = replace(glyph, character='test-only-choice')
    first = {**record, 'score': .02, 'author_terminal_penalties': {'author': 1., 'public_residual': 1.}}
    second = {**record, 'score': .025, 'author_terminal_penalties': {'author': 0., 'public_residual': 0.}}
    prepared.alternatives = [(glyph, first), (alternate, second)]
    prepared.common_supported_strokes = {'author': [0], 'public_residual': [0]}
    assert prepared.select(.01)[0] is alternate
    assert prepared.select(0.)[0] is prepared.original
