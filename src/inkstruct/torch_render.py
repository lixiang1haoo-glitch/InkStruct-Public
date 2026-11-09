from __future__ import annotations

import torch
from torch import Tensor


def sample_cubic_bspline(control_points: Tensor, samples: int = 24) -> Tensor:
    """Evaluate open cubic uniform B-splines while preserving autograd."""
    if samples < 2:
        raise ValueError("samples must be at least two")
    if control_points.shape[-2] < 4:
        indexes = torch.linspace(
            0, control_points.shape[-2] - 1, samples, device=control_points.device
        )
        left = indexes.floor().long()
        right = torch.clamp(left + 1, max=control_points.shape[-2] - 1)
        weight = (indexes - left).view(*([1] * (control_points.ndim - 2)), samples, 1)
        return control_points[..., left, :] * (1 - weight) + control_points[..., right, :] * weight
    padded = torch.cat(
        (
            control_points[..., :1, :].expand(*control_points.shape[:-2], 3, 2),
            control_points,
            control_points[..., -1:, :].expand(*control_points.shape[:-2], 3, 2),
        ),
        dim=-2,
    )
    segment_count = padded.shape[-2] - 3
    positions = torch.linspace(
        0, segment_count - 1e-5, samples, device=control_points.device, dtype=control_points.dtype
    )
    indexes = positions.floor().long().clamp(max=segment_count - 1)
    t = positions - indexes
    basis = torch.stack(
        (
            (1 - t) ** 3 / 6,
            (3 * t**3 - 6 * t**2 + 4) / 6,
            (-3 * t**3 + 3 * t**2 + 3 * t + 1) / 6,
            t**3 / 6,
        ),
        dim=-1,
    )
    windows = torch.stack([padded[..., indexes + offset, :] for offset in range(4)], dim=-2)
    view = (*([1] * (windows.ndim - 3)), samples, 4, 1)
    return (windows * basis.view(view)).sum(dim=-2)


def auxiliary_curve_loss(predicted: Tensor, target: Tensor, stroke_mask: Tensor) -> dict[str, Tensor]:
    """Curve, endpoint, tangent and curvature losses on sampled splines."""
    predicted_curve = sample_cubic_bspline(predicted, 24)
    target_curve = sample_cubic_bspline(target, 24)
    valid = (~stroke_mask).to(predicted.dtype)

    def masked(values: Tensor) -> Tensor:
        while values.ndim > valid.ndim:
            values = values.mean(dim=-1)
        return (values * valid).sum() / valid.sum().clamp_min(1)

    curve = masked(torch.linalg.vector_norm(predicted_curve - target_curve, dim=-1))
    endpoints = masked(
        torch.linalg.vector_norm(
            predicted_curve[..., (0, -1), :] - target_curve[..., (0, -1), :], dim=-1
        )
    )
    predicted_tangent = torch.diff(predicted_curve, dim=-2)
    target_tangent = torch.diff(target_curve, dim=-2)
    predicted_tangent = predicted_tangent / torch.linalg.vector_norm(
        predicted_tangent, dim=-1, keepdim=True
    ).clamp_min(1e-6)
    target_tangent = target_tangent / torch.linalg.vector_norm(
        target_tangent, dim=-1, keepdim=True
    ).clamp_min(1e-6)
    tangent = masked(1 - (predicted_tangent * target_tangent).sum(dim=-1).clamp(-1, 1))
    predicted_curvature = torch.diff(predicted_tangent, dim=-2)
    target_curvature = torch.diff(target_tangent, dim=-2)
    curvature = masked(
        torch.linalg.vector_norm(predicted_curvature - target_curvature, dim=-1)
    )
    return {"curve": curve, "endpoint": endpoints, "tangent": tangent, "curvature": curvature}


def soft_stroke_sdf(
    controls: Tensor,
    stroke_mask: Tensor,
    *,
    size: int = 32,
    radius: float = 0.012,
    temperature: float = 0.006,
) -> Tensor:
    """Differentiable soft distance field for a batch of open centerline strokes."""
    if size < 8:
        raise ValueError("render size must be at least eight")
    curves = sample_cubic_bspline(controls, 24)
    batch, strokes, points, _ = curves.shape
    axis = (torch.arange(size, device=controls.device, dtype=controls.dtype) + 0.5) / size
    yy, xx = torch.meshgrid(axis, axis, indexing="ij")
    pixels = torch.stack((xx.reshape(-1), yy.reshape(-1)), dim=-1)
    distances = torch.cdist(pixels.unsqueeze(0).expand(batch, -1, -1), curves.reshape(batch, strokes * points, 2))
    point_mask = stroke_mask.unsqueeze(-1).expand(-1, -1, points).reshape(batch, 1, strokes * points)
    distances = distances.masked_fill(point_mask, 10.0)
    soft_minimum = -temperature * torch.logsumexp(-distances / temperature, dim=-1)
    return (soft_minimum - max(radius, 0.6 / size)).reshape(batch, size, size)


def multiscale_sdf_loss(
    predicted: Tensor,
    target: Tensor,
    stroke_mask: Tensor,
    *,
    sizes: tuple[int, ...] = (32, 64),
) -> Tensor:
    losses = []
    for size in sizes:
        left = soft_stroke_sdf(predicted, stroke_mask, size=size)
        right = soft_stroke_sdf(target, stroke_mask, size=size)
        losses.append(torch.mean(torch.abs(torch.clamp(left, -0.08, 0.08) - torch.clamp(right, -0.08, 0.08))))
    return torch.stack(losses).mean()
