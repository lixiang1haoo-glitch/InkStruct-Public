"""Prepare, inspect and assemble the initial complete-component plan."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass


from ..trajectory_experiment import (
    SharedTransform,
    assemble,
    crossing_pairs,
)
from .reference import FullReferenceGenerator
from .framing import FramedComponentGenerator, framed_graph, reference_frame
from .contacts import BRUSH_WIDTH, contact_pairs, segment_clearance

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


class ComponentPlan:
    def __init__(self, profile, mapping_repository, target_repository):
        self.v6 = FramedComponentGenerator(profile, mapping_repository, target_repository)
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
