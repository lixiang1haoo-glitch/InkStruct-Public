"""Opt-in reference-dependence ablation using the existing v6.1 stages.

No pool expansion, source remapping, new archive, shape averaging or default change.
The envelope alternative still uses coarse font bounds; it is not learned author layout.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from itertools import product

import numpy as np

from .geometry import bbox, path_length
from .trajectory_experiment import SharedTransform
from .v61_contacts import BRUSH_WIDTH
from .v61_exp import PARAMETERS, V61ExpGenerator, curves

REFERENCE_PARAMETERS = {
    "reference_rank_weight": 0.25,
    "relative_scale_limits": [0.8, 1.25],
    "offset_limit": BRUSH_WIDTH,
    "offset_step": BRUSH_WIDTH / 2,
    "envelope_center_weight": 1.0,
    "clearance_weight": 1.0,
}


def fit_envelope(source, target):
    """Positive isotropic containment from complete component bounds, no stroke anchors."""
    a = np.array(bbox([p for s in source for p in s]), dtype=float)
    b = np.array(bbox([p for s in target for p in s]), dtype=float)
    if not np.isfinite([a, b]).all() or np.min(a[2:] - a[:2]) < 1e-8:
        raise ValueError("degenerate source envelope")
    scale = float(np.min((b[2:] - b[:2]) / (a[2:] - a[:2])))
    if scale <= 1e-8:
        raise ValueError("degenerate target envelope")
    offset = (b[:2] + b[2:]) / 2 - scale * (a[:2] + a[2:]) / 2
    return SharedTransform(scale, scale, *map(float, offset))


class ReferenceAblationGenerator(V61ExpGenerator):
    def ranking_score(self, placement, peer, crowd):
        # The original base score is anchor residual + .01 * retrieval score.
        # Retrieval confidence is retained; only geometric reference terms shrink.
        confidence_cost = 0.0003 * (1 - placement.candidate["confidence"])
        reference_cost = max(0.0, placement.base_score - confidence_cost)
        return (
            REFERENCE_PARAMETERS["reference_rank_weight"] * reference_cost
            + confidence_cost
            + PARAMETERS["terminal_peer_weight"] * peer
            + PARAMETERS["contact_weight"] * crowd
        )

    def envelope_layout(self, ctx, initial):
        """Fixed donors, coarse envelopes and exact gap guards; retain input if unsafe.

        No per-stroke fit, no rotations and no aspect-ratio deformation. A bounded
        offset search accommodates adjacent strokes without enforcing font gaps.
        Existing reference-supported contact guard is explicitly retained.
        """
        plan, log = dict(initial), []
        w = REFERENCE_PARAMETERS["offset_limit"]
        offsets = [(x, y) for x, y in product((-w, -w / 2, 0, w / 2, w), repeat=2)
                   if np.hypot(x, y) <= w + 1e-12]
        for cid, start in initial.items():
            source = [s.points for s in self.source(start)]
            target = [ctx.graph.strokes[i].median for i in start.indices]
            entry = {"component_id": cid, "candidate": start.candidate,
                     "before": asdict(start.transform), "trials": [], "applied": False}
            try:
                fitted = fit_envelope(source, target)
            except ValueError as exc:
                entry["reason"] = str(exc)
                log.append(entry)
                continue
            entry["envelope_transform"] = asdict(fitted)
            ratio = fitted.sx / start.transform.sx
            entry["relative_scale"] = ratio
            low, high = REFERENCE_PARAMETERS["relative_scale_limits"]
            if not low <= ratio <= high:
                entry["reason"] = "envelope scale outside frozen conservative range; input retained"
                log.append(entry)
                continue
            trials = []
            for dx, dy in offsets:
                transform = replace(fitted, tx=fitted.tx + dx, ty=fitted.ty + dy)
                p = replace(start, transform=transform)
                glyph = self.emit(ctx, {**plan, cid: p})
                score = (REFERENCE_PARAMETERS["envelope_center_weight"] * float(np.hypot(dx, dy))
                         + REFERENCE_PARAMETERS["clearance_weight"]
                         * self.clearance_cost(ctx, curves(glyph)))
                trials.append((score, dx, dy, p, glyph))
            for score, dx, dy, p, glyph in sorted(trials, key=lambda t: t[:3]):
                checks = self.validate(ctx, glyph)
                ratios = [path_length(x) / max(path_length(ctx.graph.strokes[i].median), 1e-9)
                          for i, x in zip(p.indices, self.placed(p), strict=True)]
                checks["reference_length_guard"] = not (min(ratios) >= .4 and max(ratios) <= 2.5)
                entry["trials"].append({"score": score, "offset": [dx, dy],
                                        "transform": asdict(p.transform), "checks": checks,
                                        "length_ratios": ratios})
                if self.safe(checks):
                    plan[cid] = p
                    entry.update(applied=True, after=asdict(p.transform),
                                 reason="safe envelope placement; style benefit unproven")
                    break
            if not entry["applied"]:
                entry["reason"] = "all envelope placements fail existing guards; input retained"
            log.append(entry)
        return plan, log

    def generate(self, character, *, selection=True, layout=True):
        ctx = self.prepare(character)
        plan, sl = self.select(ctx) if selection else (ctx.baseline_plan, [])
        plan, ll = self.envelope_layout(ctx, plan) if layout else (plan, [])
        glyph, meta = self.finish(ctx, plan, selection_log=sl, layout_log=ll)
        meta["reference_ablation"] = dict(REFERENCE_PARAMETERS)
        return glyph, meta
