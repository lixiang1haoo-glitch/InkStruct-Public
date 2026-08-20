import json
from dataclasses import asdict
from datetime import UTC, datetime

import torch

from inkstruct.factorized import observed_structure_keys, stroke_context_tokens
from inkstruct.model import HierarchicalResidualModel, ModelConfig
from inkstruct.profile import load_profile
from inkstruct.schemas import FactorizedStyleProfile, StyleProfile
from inkstruct.structures import graph_from_records


def _graph():
    return graph_from_records(
        {
            "character": "池",
            "medians": [
                [[120, 780], [180, 700]],
                [[140, 600], [200, 530]],
                [[420, 760], [800, 760]],
                [[600, 820], [600, 240]],
            ],
        },
        {
            "character": "池",
            "decomposition": "⿰氵也",
            "radical": "氵",
            "matches": [[0], [0], [1], [1]],
        },
        simplified_characters={"池"},
        source_version="fixture",
    )


def test_factorized_context_keys_are_deterministic():
    graph = _graph()
    first = stroke_context_tokens(graph)
    second = stroke_context_tokens(graph)
    assert first.shape == (len(graph.strokes), 16)
    assert torch.equal(torch.from_numpy(first), torch.from_numpy(second))
    keys = observed_structure_keys(graph)
    assert any(key.startswith("component:") for key in keys)
    assert any(key.startswith("role-layout:") for key in keys)
    assert any(key.startswith("stroke-signature:") for key in keys)


def test_factorized_model_emits_writer_uncertainty():
    config = ModelConfig(
        d_model=32,
        nhead=4,
        style_layers=1,
        structure_layers=1,
        decoder_layers=1,
        use_factorized_style=True,
    )
    model = HierarchicalResidualModel(config).eval()
    result = model(
        torch.randn(2, 5, 40),
        torch.randn(2, 3, 40),
        context_tokens=torch.randn(2, 3, 16),
    )
    assert result["writer_mean"].shape == (2, 64)
    assert result["writer_log_variance"].shape == (2, 64)
    assert result["residual_log_variance"].shape == (2, 3)


def test_v4_and_v5_profile_round_trip(tmp_path):
    factorized = FactorizedStyleProfile(
        model_version="fixture",
        checkpoint_sha256="a" * 64,
        writer_latent=[0.0] * 64,
        writer_log_variance=[-1.0] * 64,
        observed_structure_keys=["component:水"],
        uncertainty_summary={"latent_std_mean": 0.6},
    )
    for schema, value in (("style_profile_v4", None), ("style_profile_v5", factorized)):
        profile = StyleProfile(
            schema_version=schema,
            profile_version=schema,
            writer_id="writer-1",
            created_at=datetime.now(UTC).isoformat(),
            source_index_sha256="fixture",
            sample_count=1,
            character_count=1,
            global_style={},
            prototypes={},
            coverage={},
            factorized_style=value,
        )
        path = tmp_path / f"{schema}.json"
        path.write_text(json.dumps(asdict(profile)), encoding="utf-8")
        loaded = load_profile(path)
        assert loaded.schema_version == schema
        assert (loaded.factorized_style is not None) == (value is not None)
        if loaded.factorized_style is not None:
            assert len(loaded.factorized_style.writer_latent) == 64
