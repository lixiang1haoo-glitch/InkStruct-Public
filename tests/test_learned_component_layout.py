from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.alignment import _normalise_glyph_extent
from inkstruct.contextual_trajectory import choose_component
from inkstruct.exemplar_index import ExemplarIndex, component_key, ordered_ids
from inkstruct.learned_component_layout import (
    ComponentLayoutEvidence,
    layout_summary,
    place_with_learned_layout,
    public_layout,
)
from inkstruct.topology_repair import glyph_curves
from inkstruct.trajectory_experiment import invariants


def test_known_layout_residual_and_target_repeat_isolation(tmp_path):
    graphs, _, _, profile, _ = fixture(tmp_path)
    graph = graphs['沱']
    component = next(c for c in graph.components if c.path == 'root.0')
    ids = ordered_ids(graph, component)
    center, span, _ = public_layout(graph, component)
    standard = _normalise_glyph_extent([s.median for s in graph.strokes])
    chars = '沱江河海湖池'
    copies = {c: replace(graph, character=c) for c in chars}
    sources = {}
    for c in chars:
        source = replace(deepcopy(profile.source_trajectories['沱']), sample_id=c, character=c)
        for stroke, public in zip(source.strokes, standard, strict=True):
            if stroke.standard_stroke_id in ids:
                stroke.points = [(tuple(p)) for p in ((np.asarray(public)-center)*1.1+center+[.02, -.01])]
        sources[c] = source
    entries = [{'character': c, 'sample_id': c, 'source_sha256': sources[c].source_sha256,
                'component_id': component.component_id, 'stroke_ids': ids} for c in chars]
    index = SimpleNamespace(by_key={component_key(graph, component): entries}, sources=sources, graph=lambda c: copies[c])
    evidence = ComponentLayoutEvidence(index)
    prediction = evidence.predict(graph, component)
    assert prediction['available'] and '沱' not in prediction['reference_characters']
    np.testing.assert_allclose(prediction['center'], center+[.02, -.01], atol=1e-12)
    assert prediction['span'] == pytest.approx(span*1.1)
    # Hundreds of copies of a target character never enter counts or estimates.
    entry = evidence.exact[component_key(graph, component)][0]
    poisoned = {**entry, 'residual': np.array([100., 100., 100.])}
    evidence.exact[component_key(graph, component)].extend([poisoned]*100)
    assert evidence.predict(graph, component) == prediction
    # Repeating one reference with an identical observation does not add votes.
    evidence.exact[component_key(graph, component)].extend([evidence.exact[component_key(graph, component)][1]]*100)
    repeated = evidence.predict(graph, component)
    assert repeated['center'] == prediction['center'] and repeated['reference_characters'] == prediction['reference_characters']


def test_layout_placement_is_shared_and_zero_is_exact_original(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    ids = ordered_ids(graph, component)
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    base = baseline.generate(graph)
    original, metadata = choose_component(base, graph, ids, index.candidates(graph, component), index.sources)
    center, span, _ = layout_summary(glyph_curves(original)[:3])
    prediction = {'available': True, 'center': (center+[.001, 0]).tolist(), 'span': span*.99}
    snapshot = asdict(original)
    off, off_meta = place_with_learned_layout(base, original, metadata, graph, component, index.sources, prediction, 0.)
    assert off is original and off_meta is metadata
    changed, report = place_with_learned_layout(base, original, metadata, graph, component, index.sources, prediction, 1.)
    assert report['learned_layout']['applied'] and not invariants(changed, graph)
    assert report['selected']['candidate'] == metadata['selected']['candidate']
    for before, after in zip(original.strokes[:3], changed.strokes[:3], strict=True):
        a = np.array([(p.x, p.y) for p in before.points])
        b = np.array([(p.x, p.y) for p in after.points])
        np.testing.assert_allclose(b, (a-center)*.99+center+[.001, 0], atol=1e-12)
        assert [p.pressure for p in before.points] == [p.pressure for p in after.points]
        np.testing.assert_array_equal(np.diff([p.t_ms for p in before.points]), np.diff([p.t_ms for p in after.points]))
    assert asdict(original) == snapshot
    failed, reason = place_with_learned_layout(base, original, metadata, graph, component, index.sources,
        {'available': True, 'center': [5., 5.], 'span': span}, 1.)
    assert failed is original and reason['learned_layout']['fallback_reason']
    for bad in (-1., 1.1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            place_with_learned_layout(base, original, metadata, graph, component, index.sources, prediction, bad)


def test_sparse_evidence_abstains_without_target_or_global_leakage(tmp_path):
    graphs, repo, _, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    prediction = ComponentLayoutEvidence(index).predict(graph, component)
    assert not prediction['available']
    assert all(a['reference_character_count'] <= 1 for a in prediction['attempts'])
