from dataclasses import asdict

import numpy as np
import pytest

from inkstruct.control_repair import (
    ControlRepairGenerator,
    endpoint_consistent_controls,
    regularize_residual,
)
from inkstruct.generate import DeterministicGenerator
from inkstruct.schemas import StyleProfile
from inkstruct.structures import graph_from_records


def test_total_endpoint_displacement_applied_once_and_bow_preserved():
    source = [(0.0, 0.0), (0.5, 0.02), (1.0, 0.0)]
    warped = [(0.0, 0.2), (0.5, 0.8), (1.0, 0.2)]
    result, method = endpoint_consistent_controls(source, warped, (0.0, 0.2), (0.0, 0.2))
    assert method == "endpoint_similarity"
    np.testing.assert_allclose(result, [(0.0, 0.2), (0.5, 0.22), (1.0, 0.2)])


def test_bent_path_endpoint_correction_is_continuous():
    source = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.0, 0.5), (1.0, 1.0)]
    warped = [(x + 0.2, y) for x, y in source]
    result, method = endpoint_consistent_controls(source, warped, (0.0, 0.2), (0.2, 0.0))
    assert method == "continuous_remaining_endpoint_displacement"
    np.testing.assert_allclose(result[0], (0.0, 0.2))
    np.testing.assert_allclose(result[-1], (1.2, 1.0))
    np.testing.assert_allclose(
        np.asarray(result) - warped,
        [(-0.2, 0.2), (-0.15, 0.15), (-0.1, 0.1), (-0.05, 0.05), (0.0, 0.0)],
    )


def test_reversed_straight_proposal_is_rejected():
    source = [(0.0, 0.0), (1.0, 0.0)]
    result, method = endpoint_consistent_controls(source, source, (2.0, 0.0), (-2.0, 0.0))
    assert result == source
    assert method.startswith("rejected")


def test_sparse_residual_keeps_endpoints_and_learned_affine_field():
    residual = [(0.0, 0.1), (0.5, 1.1), (1.0, 0.1)]
    result = regularize_residual(residual, 1)
    np.testing.assert_allclose(result, [(0.0, 0.1), (0.5, 0.35), (1.0, 0.1)])
    np.testing.assert_allclose(regularize_residual(residual, 4), residual)
    np.testing.assert_allclose(regularize_residual(residual, 50), residual)
    assert residual[1] == (0.5, 1.1)


@pytest.mark.parametrize("delta", [(float("nan"), 0.0), (1.0,)])
def test_nonfinite_or_malformed_endpoints_rejected(delta):
    with pytest.raises(ValueError):
        endpoint_consistent_controls(
            [(0.0, 0.0), (1.0, 0.0)], [(0.0, 0.0), (1.0, 0.0)], delta, (0.0, 0.0)
        )


def fixture_inputs():
    graph = graph_from_records(
        {"character": "二", "medians": [[[200, 700], [800, 700]], [[100, 300], [900, 300]]]},
        {"character": "二", "decomposition": "二", "radical": "二", "matches": [[], []]},
        simplified_characters={"二"},
        source_version="fixture",
    )
    profile = StyleProfile(
        schema_version="style_profile_v4",
        profile_version="fixture",
        writer_id="fixture",
        created_at="fixture",
        source_index_sha256="fixture",
        sample_count=0,
        character_count=0,
        global_style={},
        prototypes={},
        coverage={},
    )
    return graph, profile


def test_no_evidence_no_change_and_disabled_generator_matches_default():
    graph, profile = fixture_inputs()
    before = asdict(profile)
    baseline = asdict(DeterministicGenerator(profile, "fixture").generate(graph))
    for kwargs in ({}, {"geometry": False, "sparse": False}):
        generator = ControlRepairGenerator(profile, "fixture", **kwargs)
        assert asdict(generator.generate(graph)) == baseline
    assert asdict(profile) == before


def test_new_crossing_falls_back_to_exact_original(monkeypatch):
    graph, profile = fixture_inputs()
    generator = ControlRepairGenerator(profile, "fixture")
    calls = iter([{(0, 1)}, set()])
    monkeypatch.setattr("inkstruct.control_repair.crossing_pairs", lambda _: next(calls))
    assert asdict(generator.generate(graph)) == asdict(generator.baseline.generate(graph))
    assert generator.last_diagnostics["二"]["fallback"]
