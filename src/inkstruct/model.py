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
    use_factorized_style: bool = False
    writer_latent_dim: int = 64
    context_features: int = 16


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
        self.context_projection = (
            nn.Linear(cfg.context_features, cfg.d_model) if cfg.use_factorized_style else None
        )
        self.writer_mean_head = (
            nn.Linear(cfg.d_model, cfg.writer_latent_dim) if cfg.use_factorized_style else None
        )
        self.writer_log_variance_head = (
            nn.Linear(cfg.d_model, cfg.writer_latent_dim) if cfg.use_factorized_style else None
        )
        self.writer_to_model = (
            nn.Linear(cfg.writer_latent_dim, cfg.d_model) if cfg.use_factorized_style else None
        )
        self.residual_log_variance_head = (
            nn.Linear(cfg.d_model, 1) if cfg.use_factorized_style else None
        )
        self.refinement_head = (
            nn.Sequential(
                nn.Linear(cfg.d_model * 2, cfg.d_model),
                nn.GELU(),
                nn.Linear(cfg.d_model, cfg.control_points * 2),
            )
            if cfg.use_refiner
            else None
        )

    def encode_writer(
        self, style_tokens: Tensor, style_padding_mask: Tensor | None = None
    ) -> tuple[Tensor, Tensor, Tensor]:
        style = self.style_encoder(
            self.style_projection(style_tokens), src_key_padding_mask=style_padding_mask
        )
        valid = (
            (~style_padding_mask).to(style.dtype).unsqueeze(-1)
            if style_padding_mask is not None
            else torch.ones((*style.shape[:2], 1), device=style.device, dtype=style.dtype)
        )
        pooled = (style * valid).sum(dim=1) / valid.sum(dim=1).clamp_min(1)
        if self.writer_mean_head is None or self.writer_log_variance_head is None:
            raise RuntimeError("checkpoint does not contain the factorized writer encoder")
        mean = self.writer_mean_head(pooled)
        log_variance = self.writer_log_variance_head(pooled).clamp(-8.0, 4.0)
        return style, mean, log_variance

    def forward(
        self,
        style_tokens: Tensor,
        structure_tokens: Tensor,
        *,
        style_padding_mask: Tensor | None = None,
        structure_padding_mask: Tensor | None = None,
        context_tokens: Tensor | None = None,
        writer_latent: Tensor | None = None,
    ) -> dict[str, Tensor]:
        writer_mean = writer_log_variance = None
        if self.config.use_factorized_style:
            style, writer_mean, writer_log_variance = self.encode_writer(
                style_tokens, style_padding_mask
            )
            if writer_latent is None:
                writer_latent = writer_mean
        else:
            style = self.style_encoder(
                self.style_projection(style_tokens), src_key_padding_mask=style_padding_mask
            )
        structure_input = self.structure_projection(structure_tokens)
        if self.context_projection is not None:
            if context_tokens is None:
                context_tokens = torch.zeros(
                    (*structure_tokens.shape[:2], self.config.context_features),
                    device=structure_tokens.device,
                    dtype=structure_tokens.dtype,
                )
            structure_input = structure_input + self.context_projection(context_tokens)
        structure = self.structure_encoder(
            structure_input,
            src_key_padding_mask=structure_padding_mask,
        )
        decoded = self.stroke_decoder(
            structure,
            style,
            tgt_key_padding_mask=structure_padding_mask,
            memory_key_padding_mask=style_padding_mask,
        )
        if self.writer_to_model is not None and writer_latent is not None:
            decoded = decoded + self.writer_to_model(writer_latent).unsqueeze(1)
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
        result = {
            "initial_residual": initial_residual,
            "refinement": refinement,
            "residual": initial_residual + refinement,
            "pressure": torch.sigmoid(self.pressure_head(decoded)),
            "duration": torch.nn.functional.softplus(self.duration_head(decoded)).squeeze(-1),
            "density": torch.nn.functional.softplus(self.density_head(decoded)).squeeze(-1),
            "confidence": torch.sigmoid(self.confidence_head(decoded)).squeeze(-1),
        }
        if self.residual_log_variance_head is not None:
            result["residual_log_variance"] = self.residual_log_variance_head(decoded).squeeze(
                -1
            ).clamp(-8.0, 4.0)
            result["writer_mean"] = writer_mean
            result["writer_log_variance"] = writer_log_variance
        return result

    def checkpoint_payload(self) -> dict:
        return {"model_config": asdict(self.config), "model_state": self.state_dict()}
