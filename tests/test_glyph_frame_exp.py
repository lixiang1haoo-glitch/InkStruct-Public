from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
from test_source_generation_entry import fixture

from inkstruct.glyph_frame_exp import GlyphFrameEvidence, apply_glyph_frame, reference_frame
from inkstruct.trajectory_experiment import crossing_pairs, invariants
from inkstruct.v6_exp import FullReferenceGenerator


def test_frame_preserves_all_points_dynamics_angles_and_crossings(tmp_path):
    graphs, _, _, profile, _ = fixture(tmp_path)
    g = graphs['池']
    original = FullReferenceGenerator(profile, 'test').generate(g)
    before = asdict(original)
    result, meta = apply_glyph_frame(original, g)
    assert meta['applied'] and not invariants(result, g)
    assert asdict(original) == before
    old, new = [], []
    for a, b in zip(original.strokes, result.strokes, strict=True):
        old.append([(p.x, p.y) for p in a.points])
        new.append([(p.x, p.y) for p in b.points])
        assert [(p.t_ms, p.pressure, p.pen_state) for p in a.points] == [
            (p.t_ms, p.pressure, p.pen_state) for p in b.points]
        np.testing.assert_allclose(np.diff(new[-1], axis=0),
                                   np.diff(old[-1], axis=0)*meta['transform']['sx'])
    assert crossing_pairs(old) == crossing_pairs(new)


def test_training_repeats_have_one_vote_and_target_is_excluded(tmp_path):
    graphs, _, _, _, _ = fixture(tmp_path)
    graph = graphs['池']
    frame = reference_frame(graph)
    def source(c, dx):
        return SimpleNamespace(character=c, sample_id=c,
            strokes=[SimpleNamespace(standard_stroke_id=s.stroke_id,
                points=[(x+dx, y) for x,y in frame.apply(s.median)]) for s in graph.strokes])
    sources = {str(i):source(str(i), .01) for i in range(8)}
    # Many repeats of one different character must still count only once.
    sources.update({f'repeat{i}':source('outlier', .10) for i in range(100)})
    sources['target'] = source('target', 10)
    repo = SimpleNamespace(get=lambda c:graph)
    evidence = GlyphFrameEvidence(sources, repo)
    prediction = evidence.predict('target')
    assert prediction['available'] and prediction['character_count'] == 9
    assert 'target' not in prediction['training_characters']
    assert abs(prediction['transform']['tx']-.01) < 1e-10
    del sources['target']
    assert prediction == GlyphFrameEvidence(sources, repo).predict('target')


def test_bounds_rejection_returns_exact_original_and_sparse_evidence_uses_public_frame(tmp_path):
    graphs, repo, _, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    original = FullReferenceGenerator(profile, 'test').generate(graph)
    evidence = GlyphFrameEvidence({}, repo)
    result, meta = apply_glyph_frame(original, graph, evidence=evidence)
    assert not meta['prediction']['available'] and meta['applied']
    assert asdict(result) == asdict(apply_glyph_frame(original, graph)[0]) | {'canvas_fit':meta}
    unsafe_prediction = SimpleNamespace(predict=lambda c: {
        'available': True, 'transform': {'sx': 1., 'sy': 1., 'tx': 50., 'ty': 0.}})
    result, meta = apply_glyph_frame(original, graph, evidence=unsafe_prediction)
    assert not meta['applied'] and meta['errors']
    assert asdict(result) == asdict(original)
