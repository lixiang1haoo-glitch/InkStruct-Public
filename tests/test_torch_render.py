from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from inkstruct.model import HierarchicalResidualModel, ModelConfig
from inkstruct.torch_render import auxiliary_curve_loss, multiscale_sdf_loss


def test_soft_renderer_produces_control_point_gradients() -> None:
    predicted = torch.tensor(
        [[[[0.1, 0.2], [0.3, 0.25], [0.6, 0.3], [0.9, 0.4]]]],
        dtype=torch.float32,
        requires_grad=True,
    )
    target = predicted.detach().clone()
    target[..., 1] += 0.05
    mask = torch.zeros((1, 1), dtype=torch.bool)
    curve = auxiliary_curve_loss(predicted, target, mask)["curve"]
    sdf = multiscale_sdf_loss(predicted, target, mask, sizes=(16,))
    (curve + sdf).backward()
    assert predicted.grad is not None
    assert torch.isfinite(predicted.grad).all()
    assert predicted.grad.abs().sum() > 0


def test_context_refinement_is_bounded() -> None:
    config = ModelConfig(
        d_model=32,
        nhead=4,
        style_layers=1,
        structure_layers=1,
        decoder_layers=1,
        use_refiner=True,
        refinement_bound=0.03,
    )
    model = HierarchicalResidualModel(config)
    prediction = model(torch.randn(2, 5, 40), torch.randn(2, 4, 40))
    assert prediction["refinement"].abs().max() <= 0.030001
    assert prediction["residual"].shape == (2, 4, 8, 2)
