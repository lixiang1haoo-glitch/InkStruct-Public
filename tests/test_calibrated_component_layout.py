from dataclasses import asdict

import numpy as np
import pytest
from test_source_generation_entry import fixture

from inkstruct.calibrated_component_layout import (
    CalibratedComponentLayoutEvidence,
    place_with_calibrated_layout,
)
from inkstruct.contextual_trajectory import choose_component
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.learned_component_layout import layout_summary
from inkstruct.topology_repair import glyph_curves


def test_training_band_abstains_when_character_calibration_is_sparse(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    evidence = CalibratedComponentLayoutEvidence(ExemplarIndex(profile, repo, allowed_characters={'沱'}))
    calibration = evidence.calibrate()
    assert not calibration['available'] and calibration['radius'] is None
    assert calibration['reference_character_count'] == 0


def test_band_shrinks_strength_and_preserves_exact_inside_and_disabled_paths(tmp_path):
    graphs, repo, baseline, profile, _ = fixture(tmp_path)
    graph = graphs['池']
    component = next(c for c in graph.components if c.path == 'root.0')
    ids = ordered_ids(graph, component)
    index = ExemplarIndex(profile, repo, allowed_characters={'沱'})
    base = baseline.generate(graph)
    original, metadata = choose_component(base, graph, ids, index.candidates(graph, component), index.sources)
    center, span, _ = layout_summary(glyph_curves(original)[:3])
    prediction = {'available': True, 'center': (center+[.004, 0]).tolist(), 'span': span,
                  'response_dispersion': [.001, .001, .05]}
    calibration = {'available': True, 'radius': 3., 'reference_character_count': 20, 'interpretation': 'test reference band'}
    snapshot = asdict(original)
    output, report = place_with_calibrated_layout(base, original, metadata, graph, component, index.sources, prediction, calibration, 1.)
    assert report['layout_band']['effective_strength'] == pytest.approx(.25)
    assert report['layout_band']['applied']
    for a, b in zip(glyph_curves(original)[:3], glyph_curves(output)[:3], strict=True):
        np.testing.assert_allclose(np.asarray(b)-np.asarray(a), np.broadcast_to([.001, 0], np.asarray(a).shape), atol=1e-12)
    assert asdict(original) == snapshot
    inside = {**calibration, 'radius': 5.}
    assert place_with_calibrated_layout(base, original, metadata, graph, component, index.sources, prediction, inside, 1.)[0] is original
    off, off_meta = place_with_calibrated_layout(base, original, metadata, graph, component, index.sources, prediction, calibration, 0.)
    assert off is original and off_meta is metadata
    for bad in (-1, 1.1, float('nan')):
        with pytest.raises(ValueError):
            place_with_calibrated_layout(base, original, metadata, graph, component, index.sources, prediction, calibration, bad)
