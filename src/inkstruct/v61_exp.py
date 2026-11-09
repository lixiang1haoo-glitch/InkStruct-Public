"""v6.1 exp: frozen instance proposals, separate selection and layout decisions.

Reuses the v6 structure/archive bridge, retrieval pool, similarity fit and output
assembler. No production import. Reference contact is a review prior, never an
author-style truth or an instruction to close every gap.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, replace
from itertools import product

import numpy as np

from .geometry import path_length
from .glyph_frame_exp import reference_frame
from .trajectory_experiment import (
    SharedTransform,
    assemble,
    at_distance,
    crossing_pairs,
    invariants,
)
from .v6_exp import FullReferenceGenerator
from .v6_integrated_exp import IntegratedV6Generator, framed_graph
from .v61_contacts import BRUSH_WIDTH, contact_pairs, segment_clearance

POLICY = "v6.1_exp_selection_layout_v1"
PARAMETERS = {
    "brush_width": BRUSH_WIDTH,
    "terminal_peer_weight": 0.01,
    "contact_weight": 1.0,
    "layout_step": BRUSH_WIDTH / 2,
    "layout_limit": BRUSH_WIDTH,
    "clearance_margin": BRUSH_WIDTH / 4,
    "movement_weight": 0.02,
    "max_candidates": 16,
}


def curves(glyph):
    return [[(p.x, p.y) for p in s.points] for s in glyph.strokes]


@dataclass(frozen=True)
class Placement:
    component_id: str
    ids: tuple[str, ...]
    indices: tuple[int, ...]
    candidate: dict
    transform: SharedTransform
    base_score: float


@dataclass
class Context:
    character: str
    graph: object
    reference: object
    baseline: object
    baseline_meta: dict
    pools: dict
    baseline_plan: dict
    reference_contacts: set
    baseline_contacts: set
    baseline_crossings: set
    separated_pairs: list


def terminal_vectors(strokes):
    """Relative arc window: identical for a source and its positive similarity."""
    output = []
    for stroke in strokes:
        length = path_length(stroke)
        vector = np.asarray(stroke[-1]) - at_distance(stroke, 0.9 * length)
        output.append(vector / max(float(np.linalg.norm(vector)), 1e-12))
    return np.asarray(output)


class V61ExpGenerator:
    def __init__(self, profile, mapping_repository, target_repository):
        self.v6 = IntegratedV6Generator(profile, mapping_repository, target_repository)
        self.profile = profile

    def prepare(self, character):
        """Freeze reference, B output, eligible proposals and original transforms."""
        baseline, meta = self.v6.generate(character)
        target = self.v6.target_repository.get(character)
        graph = framed_graph(target, reference_frame(target))
        reference = FullReferenceGenerator(self.profile, target.source_version).generate(graph)
        positions = {s.stroke_id: i for i, s in enumerate(graph.strokes)}
        pools, plan = {}, {}
        for part in meta["components"]:
            cid = part["component_id"]
            ids = tuple(part["target_stroke_ids"])
            entries = []
            for trial in part.get("selection", {}).get("candidates", [])[
                : PARAMETERS["max_candidates"]
            ]:
                if "transform" not in trial:
                    continue
                entries.append(
                    Placement(
                        cid,
                        ids,
                        tuple(positions[k] for k in ids),
                        copy.deepcopy(trial["candidate"]),
                        SharedTransform(**trial["transform"]),
                        trial["score"],
                    )
                )
            pools[cid] = entries
            selected = part.get("selection", {}).get("selected")
            if selected:
                plan[cid] = next(p for p in entries if p.candidate == selected["candidate"])
        ref = curves(reference)
        base = curves(baseline)
        separated = []
        # Only cross-component distances can be changed by rigid component placement.
        owners = {
            i: cid for cid, placements in pools.items() for p in placements[:1] for i in p.indices
        }
        for i in range(len(ref)):
            for j in range(i + 1, len(ref)):
                if owners.get(i, ("reference", i)) == owners.get(j, ("reference", j)):
                    continue
                gap = segment_clearance(ref[i], ref[j])
                if gap > BRUSH_WIDTH + PARAMETERS["clearance_margin"]:
                    separated.append((i, j))
        ctx = Context(
            character,
            graph,
            reference,
            baseline,
            meta,
            pools,
            plan,
            contact_pairs(ref),
            contact_pairs(base),
            crossing_pairs(base),
            separated,
        )
        # The refactor itself must not alter the frozen baseline geometry/dynamics.
        rebuilt = self.emit(ctx, plan)
        if [[asdict(p) for p in s.points] for s in rebuilt.strokes] != [
            [asdict(p) for p in s.points] for s in baseline.strokes
        ]:
            raise RuntimeError("placement-plan assembly differs from frozen v6")
        return ctx

    def source(self, placement):
        candidate = placement.candidate
        sample = self.profile.source_trajectories[candidate["sample_id"]]
        if (
            sample.source_sha256 != candidate["source_sha256"]
            or sample.character != candidate["character"]
        ):
            raise ValueError("source identity mismatch")
        mapping = {s.standard_stroke_id: s for s in sample.strokes}
        return [mapping[k] for k in candidate["stroke_ids"]]

    def placed(self, placement):
        return [placement.transform.apply(s.points) for s in self.source(placement)]

    def validate_transform(self, placement):
        if placement.transform.sx <= 0 or placement.transform.sx != placement.transform.sy:
            raise ValueError("positive isotropic component transform required")

    def emit(self, ctx, plan):
        """One final transform per source component; assembler owns output time."""
        replacements = {}
        owned = set()
        for p in plan.values():
            if p.candidate["character"] == ctx.character or owned.intersection(p.indices):
                raise ValueError("target donor or overlapping component ownership")
            self.validate_transform(p)
            owned.update(p.indices)
            for i, src, xy in zip(p.indices, self.source(p), self.placed(p), strict=True):
                replacements[i] = {"points": xy, "pressure": src.pressure, "time": src.t_ms}
        glyph = assemble(ctx.reference, replacements, POLICY)
        for i, s in enumerate(glyph.strokes):
            s.style_source = (
                "v61_complete_author_source"
                if i in owned
                else "v61_reference_fallback_style_insufficient"
            )
        glyph.generator = POLICY
        return glyph

    def clearance_cost(self, ctx, xy):
        boxes = [np.array([np.min(c, axis=0), np.max(c, axis=0)]) for c in xy]
        return sum(
            max(0.0, BRUSH_WIDTH - segment_clearance(xy[i], xy[j]))
            for i, j in ctx.separated_pairs
            if np.linalg.norm(
                np.maximum(0, np.maximum(boxes[i][0] - boxes[j][1], boxes[j][0] - boxes[i][1]))
            )
            < BRUSH_WIDTH
        )

    def validate(self, ctx, glyph):
        """Protocol, strict geometry and brush-model guard are distinct evidence."""
        xy = curves(glyph)
        contacts = contact_pairs(xy)
        return {
            "protocol": invariants(glyph, ctx.graph),
            "new_crossings": sorted(crossing_pairs(xy) - ctx.baseline_crossings),
            "new_brush_contacts": sorted(contacts - ctx.baseline_contacts),
            "lost_reference_supported_contacts": sorted(
                (ctx.baseline_contacts & ctx.reference_contacts) - contacts
            ),
            "degenerate": [i + 1 for i, c in enumerate(xy) if path_length(c) < 0.003],
        }

    @staticmethod
    def safe(checks):
        return not any(checks.values())

    def ranking_score(self, placement, peer, crowd):
        """Separate scoring policy from frozen proposals and unchanged safety gates."""
        return (
            placement.base_score
            + PARAMETERS["terminal_peer_weight"] * peer
            + PARAMETERS["contact_weight"] * crowd
        )

    def select(self, ctx):
        """Rerank fixed proposals; no new source pool, fitting, target capture or warp."""
        plan = dict(ctx.baseline_plan)
        log = []
        for cid, pool in ctx.pools.items():
            if not pool:
                log.append(
                    {
                        "component_id": cid,
                        "reason": "no eligible donor; reference/style insufficient",
                    }
                )
                continue
            vectors = [terminal_vectors(self.placed(p)) for p in pool]
            characters = sorted({p.candidate["character"] for p in pool})
            trials = []
            for p, v in zip(pool, vectors, strict=True):
                # One vote per source character; repeat samples cannot dominate.
                peer = float(
                    np.mean(
                        [
                            np.mean(
                                [
                                    np.linalg.norm(v - z, axis=1).mean() / 2
                                    for q, z in zip(pool, vectors, strict=True)
                                    if q.candidate["character"] == c
                                ]
                            )
                            for c in characters
                        ]
                    )
                )
                trial = {**plan, cid: p}
                glyph = self.emit(ctx, trial)
                crowd = self.clearance_cost(ctx, curves(glyph))
                score = self.ranking_score(p, peer, crowd)
                trials.append(
                    (
                        score,
                        p,
                        glyph,
                        {
                            "candidate": p.candidate,
                            "transform": asdict(p.transform),
                            "base_score": p.base_score,
                            "terminal_peer_cost": peer,
                            "clearance_cost": crowd,
                            "score": score,
                        },
                    )
                )
            old = plan.get(cid)
            old_score = next((score for score, p, _, _ in trials if p is old), float("inf"))
            entry = {
                "component_id": cid,
                "candidates": [],
                "changed": False,
                "baseline_score": old_score if np.isfinite(old_score) else None,
                "ranked_proposals": [
                    {**detail, "safety": "not_checked_unless_lower_score"}
                    for _, _, _, detail in sorted(
                        trials, key=lambda t: (t[0], t[1].candidate["sample_id"])
                    )
                ],
            }
            for score, p, glyph, detail in sorted(
                trials, key=lambda t: (t[0], t[1].candidate["sample_id"])
            ):
                if score >= old_score - 1e-9:
                    break
                checks = self.validate(ctx, glyph)
                ratios = [
                    path_length(x) / max(path_length(ctx.graph.strokes[i].median), 1e-9)
                    for i, x in zip(p.indices, self.placed(p), strict=True)
                ]
                detail["checks"] = checks
                detail["length_ratios"] = ratios
                good = self.safe(checks) and min(ratios) >= 0.4 and max(ratios) <= 2.5
                detail["accepted"] = good
                entry["candidates"].append(detail)
                if good:
                    plan[cid] = p
                    entry["changed"] = True
                    break
            entry["reason"] = (
                "accepted better score"
                if entry["changed"]
                else "baseline retained: no safer lower-score candidate"
            )
            log.append(entry)
        return plan, log

    def layout(self, ctx, initial):
        """One centralized bounded translation solve; no endpoint edits or closure."""
        plan = dict(initial)
        log = []
        offsets = [
            (dx, dy)
            for dx, dy in product(
                (-BRUSH_WIDTH, -BRUSH_WIDTH / 2, 0.0, BRUSH_WIDTH / 2, BRUSH_WIDTH), repeat=2
            )
            if np.hypot(dx, dy) <= PARAMETERS["layout_limit"] + 1e-12
        ]
        for cid, start in initial.items():
            current_cost = self.clearance_cost(ctx, curves(self.emit(ctx, plan)))
            if current_cost <= 1e-12:
                continue
            trials = []
            for dx, dy in offsets:
                if dx == dy == 0:
                    continue
                t = replace(start.transform, tx=start.transform.tx + dx, ty=start.transform.ty + dy)
                p = replace(start, transform=t)
                glyph = self.emit(ctx, {**plan, cid: p})
                cost = self.clearance_cost(ctx, curves(glyph))
                score = cost + PARAMETERS["movement_weight"] * float(np.hypot(dx, dy))
                trials.append((score, cost, dx, dy, p, glyph))
            entry = {
                "component_id": cid,
                "initial_cost": current_cost,
                "proposals": [],
                "applied": False,
            }
            for score, cost, dx, dy, p, glyph in sorted(trials, key=lambda t: t[:4]):
                if score >= current_cost - 1e-9:
                    break
                checks = self.validate(ctx, glyph)
                entry["proposals"].append(
                    {
                        "translation": [dx, dy],
                        "score": score,
                        "clearance_cost": cost,
                        "checks": checks,
                    }
                )
                if self.safe(checks):
                    plan[cid] = p
                    entry.update(applied=True, translation=[dx, dy], final_cost=cost)
                    break
            entry["reason"] = (
                "whole-component translation accepted"
                if entry["applied"]
                else "no bounded safe clearance improvement"
            )
            log.append(entry)
        return plan, log

    def finish(self, ctx, plan, *, selection_log=(), layout_log=()):
        glyph = self.emit(ctx, plan)
        checks = self.validate(ctx, glyph)
        if not self.safe(checks):
            raise RuntimeError(f"v6.1 final safety failure: {checks}")
        glyph.canvas_fit = {
            "policy": POLICY,
            "reference_transform": ctx.baseline_meta["reference_transform"],
            "component_transforms": {cid: asdict(p.transform) for cid, p in plan.items()},
            "transforms_applied_once_from_original_source": True,
        }
        sources = sum(len(p.indices) for p in plan.values())
        return glyph, {
            "policy": POLICY,
            "character": ctx.character,
            "parameters": PARAMETERS,
            "bridge": ctx.baseline_meta["bridge"],
            "reference_transform": ctx.baseline_meta["reference_transform"],
            "plan": [asdict(p) for p in plan.values()],
            "selection": selection_log,
            "layout": layout_log,
            "checks": checks,
            "source_strokes": sources,
            "reference_strokes": len(ctx.graph.strokes) - sources,
            "style_status": "partial author instances; reference fallback has insufficient personalization",
            "clearance_cost": self.clearance_cost(ctx, curves(glyph)),
        }

    def generate(self, character, *, selection=True, layout=True):
        ctx = self.prepare(character)
        plan, slog = self.select(ctx) if selection else (ctx.baseline_plan, [])
        plan, llog = self.layout(ctx, plan) if layout else (plan, [])
        return self.finish(ctx, plan, selection_log=slog, layout_log=llog)
