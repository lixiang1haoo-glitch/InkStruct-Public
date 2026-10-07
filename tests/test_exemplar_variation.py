import copy
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.component_variation_evidence import (
    ComponentVariationEvidence,
    shape_descriptor,
    shape_identity,
)
from inkstruct.contextual_trajectory import choose_component
from inkstruct.exemplar_generation import SourceComponentGenerator
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.exemplar_variation import (
    VariationPool,
    VariedSourceComponentGenerator,
    prepare_variation_pool,
)


def evidence_fixture():
    candidates, sources, shapes = [], {}, {}
    for i in range(10):
        char = chr(0x4E00+i)
        curves = [[(0., 0.), (.1+i*.004, .4), (.05+i*.002, .5)],
                  [(.3, .2), (.4+i*.003, .3), (.6, .5)]]
        candidates.append({'sample_id': char, 'character': char, 'stroke_ids': ['s1', 's2']})
        sources[char] = SimpleNamespace(strokes=[SimpleNamespace(standard_stroke_id=f's{j+1}', points=p)
                                                for j, p in enumerate(curves)])
        shapes[char] = curves
    return SimpleNamespace(by_key={'context': candidates}, sources=sources), shapes


def test_shape_evidence_ignores_only_common_translation_scale():
    _, shapes = evidence_fixture()
    curves = next(iter(shapes.values()))
    shifted = [(np.asarray(p)*3.7+[2., -1.]).tolist() for p in curves]
    np.testing.assert_allclose(shape_descriptor(curves), shape_descriptor(shifted), atol=1e-12)
    assert shape_identity(curves) == shape_identity(shifted)
    altered = copy.deepcopy(curves)
    altered[1][-1] = (.6, .8)
    assert np.linalg.norm(shape_descriptor(altered)-shape_descriptor(curves)) > .01


def test_target_character_removed_before_calibration_and_donor_copies_excluded():
    index, shapes = evidence_fixture()
    target = next(iter(shapes))
    model = ComponentVariationEvidence(index)
    original = model.cohort('context', target)[1]
    for stroke in index.sources[target].strokes:
        stroke.points = [(0., 0.), (100., 100.)]
    changed = ComponentVariationEvidence(index).cohort('context', target)[1]
    assert original == changed
    donor = list(shapes)[1]
    score = model.assess('context', target, shapes[donor], donor_character=donor)
    assert score['nearest_other_character_distance'] > 0
    assert score['available'] and score['donor_character_excluded_from_scoring'] == donor
    # A copied source under another character cannot inflate independent counts or score zero.
    index.sources['copy'] = copy.deepcopy(index.sources[donor])
    index.by_key['context'].append({'sample_id': 'copy', 'character': 'copy', 'stroke_ids': ['s1', 's2']})
    copied = ComponentVariationEvidence(index)
    assert copied.cohort('context', target)[1]['distinct_shapes'] == original['distinct_shapes']
    assert copied.assess('context', target, shapes[donor], donor_character=donor)['nearest_other_character_distance'] > 0


def test_evidence_gate_does_not_randomize_without_two_supported_shapes():
    records = [{'score': .01+i*.001, 'candidate': {'confidence': .9},
                'component_evidence': {'within_empirical_range': True}} for i in range(3)]
    pool = VariationPool([], records, {'available': True})
    selected, probabilities = pool.eligible(.005)
    assert len(selected) == 3 and sum(probabilities) == pytest.approx(1.)
    assert probabilities[0] > probabilities[1] > probabilities[2]
    records[0]['component_evidence']['within_empirical_range'] = False
    records[1]['component_evidence']['within_empirical_range'] = False
    assert pool.eligible(.005) == (records[:1], [1.])
    assert pool.eligible(0.) == (records[:1], [1.])
    for margin in (-1., float('nan'), float('inf'), .051):
        with pytest.raises(ValueError):
            pool.eligible(margin)


def test_off_and_insufficient_evidence_preserve_whole_source_outputs(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    ordinary = SourceComponentGenerator(baseline, profile, repo).generate(graphs['池'])
    disabled = VariedSourceComponentGenerator(baseline, profile, repo).generate(graphs['池'])
    assert asdict(ordinary[0]) == asdict(disabled[0]) and ordinary[1] == disabled[1]
    varied = VariedSourceComponentGenerator(baseline, profile, repo, seed=42, margin=.005)
    result, metadata = varied.generate(graphs['池'], occurrence_id=12)
    assert asdict(result) == asdict(ordinary[0])
    assert asdict(varied.generate(graphs['池'], occurrence_id=12)[0]) == asdict(result)
    for component in metadata['components']:
        v = component['selection']['variation']
        assert v['eligible_distinct_candidates'] == 1
        assert not v['component_evidence']['available']
    with pytest.raises(TypeError):
        VariedSourceComponentGenerator(baseline, profile, repo, seed=True)


def test_seeded_draws_are_reproducible_and_never_mix_strokes(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    ids = ordered_ids(graph, component)
    candidates = index.candidates(graph, component)
    base = baseline.generate(graph)
    pool = prepare_variation_pool(base, graph, ids, candidates, index.sources)
    expected, _ = choose_component(base, graph, ids, candidates, index.sources)
    got, _ = pool.select(base, ids, index.sources, seed=3, occurrence_id=0, component_id='c', margin=0.)
    assert asdict(expected) == asdict(got)
    other = copy.deepcopy(pool.distinct[0])
    other['transform']['tx'] += .001
    other['geometry_id'] = 'second'
    other['score'] += .001
    pool.distinct.append(other)
    selected = set()
    for occurrence in range(30):
        args = {'seed': 7, 'occurrence_id': occurrence, 'component_id': 'c', 'margin': .005}
        result, meta = pool.select(base, ids, index.sources, **args)
        again, repeat = pool.select(base, ids, index.sources, **args)
        assert asdict(result) == asdict(again) and meta == repeat
        selected.add(meta['variation']['selected_geometry_id'])
        transform = meta['selected']['transform']
        for sid in ids:
            source = next(s for s in index.sources['沱'].strokes if s.standard_stroke_id == sid)
            stroke = next(s for s in result.strokes if s.standard_stroke_id == sid)
            np.testing.assert_allclose([(p.x, p.y) for p in stroke.points],
                np.asarray(source.points)*[transform['sx'], transform['sy']]+[transform['tx'], transform['ty']])
            assert [p.pressure for p in stroke.points] == source.pressure
    assert len(selected) == 2
