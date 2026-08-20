from __future__ import annotations

from dataclasses import asdict, dataclass

try:
    import torch
    from torch import Tensor, nn
except ImportError as error:  # pragma: no cover - exercised by CLI diagnostic
    raise RuntimeError("the learned generator requires the 'train' dependency group") from error


@dataclass(slots=True)
class ModelConfig:
    input_features: int = 40
    d_model: int = 256
    nhead: int = 8
    style_layers: int = 4
    structure_layers: int = 6
    decoder_layers: int = 4
    control_points: int = 8
    dropout: float = 0.1
    use_refiner: bool = False
    refinement_bound: float = 0.03


class HierarchicalResidualModel(nn.Module):
    """Topology-preserving residual model.

    One output token is produced for each input standard stroke. The network
    cannot add, drop or reorder strokes; topology remains the responsibility of
    the CharacterGraph.
    """

    def __init__(self, config: ModelConfig | None = None):
        super().__init__()
        self.config = config or ModelConfig()
        cfg = self.config
        self.style_projection = nn.Linear(cfg.input_features, cfg.d_model)
        self.structure_projection = nn.Linear(cfg.input_features, cfg.d_model)
        style_layer = nn.TransformerEncoderLayer(
            cfg.d_model,
            cfg.nhead,
            dim_feedforward=cfg.d_model * 4,
            dropout=cfg.dropout,
            batch_first=True,
            norm_first=True,
        )
        structure_layer = nn.TransformerEncoderLayer(
            cfg.d_model,
            cfg.nhead,
            dim_feedforward=cfg.d_model * 4,
            dropout=cfg.dropout,
            batch_first=True,
            norm_first=True,
        )
        decoder_layer = nn.TransformerDecoderLayer(
            cfg.d_model,
            cfg.nhead,
            dim_feedforward=cfg.d_model * 4,
            dropout=cfg.dropout,
            batch_first=True,
            norm_first=True,
        )
        self.style_encoder = nn.TransformerEncoder(style_layer, cfg.style_layers)
        self.structure_encoder = nn.TransformerEncoder(structure_layer, cfg.structure_layers)
        self.stroke_decoder = nn.TransformerDecoder(decoder_layer, cfg.decoder_layers)
        self.residual_head = nn.Linear(cfg.d_model, cfg.control_points * 2)
        self.pressure_head = nn.Linear(cfg.d_model, cfg.control_points)
        self.duration_head = nn.Linear(cfg.d_model, 1)
        self.density_head = nn.Linear(cfg.d_model, 1)
        self.confidence_head = nn.Linear(cfg.d_model, 1)
        self.refinement_head = (
            nn.Sequential(
                nn.Linear(cfg.d_model * 2, cfg.d_model),
                nn.GELU(),
                nn.Linear(cfg.d_model, cfg.control_points * 2),
            )
            if cfg.use_refiner
            else None
        )

    def forward(
        self,
        style_tokens: Tensor,
        structure_tokens: Tensor,
        *,
        style_padding_mask: Tensor | None = None,
        structure_padding_mask: Tensor | None = None,
    ) -> dict[str, Tensor]:
        style = self.style_encoder(
            self.style_projection(style_tokens), src_key_padding_mask=style_padding_mask
        )
        structure = self.structure_encoder(
            self.structure_projection(structure_tokens),
            src_key_padding_mask=structure_padding_mask,
        )
        decoded = self.stroke_decoder(
            structure,
            style,
            tgt_key_padding_mask=structure_padding_mask,
            memory_key_padding_mask=style_padding_mask,
        )
        batch, strokes, _ = decoded.shape
        initial_residual = torch.tanh(self.residual_head(decoded)).view(
                batch, strokes, self.config.control_points, 2
            ) * 0.35
        if self.refinement_head is not None:
            valid = (
                (~structure_padding_mask).to(decoded.dtype).unsqueeze(-1)
                if structure_padding_mask is not None
                else torch.ones(batch, strokes, 1, device=decoded.device, dtype=decoded.dtype)
            )
            context = (decoded * valid).sum(dim=1) / valid.sum(dim=1).clamp_min(1)
            context = context.unsqueeze(1).expand(-1, strokes, -1)
            refinement = torch.tanh(self.refinement_head(torch.cat((decoded, context), dim=-1)))
            refinement = refinement.view(batch, strokes, self.config.control_points, 2)
            refinement = refinement * self.config.refinement_bound
        else:
            refinement = torch.zeros_like(initial_residual)
        return {
            "initial_residual": initial_residual,
            "refinement": refinement,
            "residual": initial_residual + refinement,
            "pressure": torch.sigmoid(self.pressure_head(decoded)),
            "duration": torch.nn.functional.softplus(self.duration_head(decoded)).squeeze(-1),
            "density": torch.nn.functional.softplus(self.density_head(decoded)).squeeze(-1),
            "confidence": torch.sigmoid(self.confidence_head(decoded)).squeeze(-1),
        }

    def checkpoint_payload(self) -> dict:
        return {"model_config": asdict(self.config), "model_state": self.state_dict()}
