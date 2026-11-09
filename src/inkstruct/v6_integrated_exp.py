"""Opt-in v6: versioned reference correction, one frame, complete trajectories.

The source index retains its original mapping database. Only target references
use the correction overlay. No source remapping, profile mutation or production
entry-point change is implied by this explicitly checked bridge.
"""

from __future__ import annotations

import copy
from dataclasses import asdict

import numpy as np

from .component_views import expand_views
from .exemplar_generation import SourceComponentGenerator
from .geometry import bbox, path_length
from .glyph_frame_exp import reference_frame
from .structure_corrections import CorrectedStructureRepository
from .structures import _component_bbox
from .topology_repair import glyph_curves
from .trajectory_experiment import SharedTransform, assemble, crossing_pairs, invariants
from .v6_exp import NESTED_COMPONENTS, FullReferenceGenerator, V6ExpGenerator

POLICY = "v6_corrected_full_frame_exp_v1"


def identity(graph):
    """Geometry may change; standard identity and component ownership may not."""
    return {
        "character": graph.character,
        "codepoint": graph.codepoint,
        "locale": graph.locale,
        "decomposition": graph.decomposition,
        "strokes": [(s.stroke_id, s.order, s.component_path, s.stroke_type) for s in graph.strokes],
        "components": [
            (
                n.component_id,
                n.path,
                n.canonical,
                n.glyph_variant,
                n.role,
                n.parent_id,
                n.children_ids,
                n.stroke_ids,
                n.layout,
            )
            for n in graph.components
        ],
    }


def framed_graph(graph, transform):
    """Keep every reference vertex, including corners and recovered overshoots."""
    values = np.asarray(list(asdict(transform).values()), dtype=float)
    if not np.isfinite(values).all() or transform.sx <= 0 or transform.sx != transform.sy:
        raise ValueError("v6 frame requires finite positive isotropic scaling")
    result = copy.deepcopy(graph)
    for stroke in result.strokes:
        if len(stroke.median) < 2 or not np.isfinite(stroke.median).all():
            raise ValueError("invalid reference coordinates")
        stroke.median = transform.apply(stroke.median)
        stroke.bbox = bbox(stroke.median)
    for node in result.components:
        node.bbox = _component_bbox(node.stroke_ids, result.strokes)
    return result


class _TargetIndex:
    def __init__(self, source_index, view, schedule):
        self.source_index, self.view, self.schedule = source_index, view, schedule
        self.sources = source_index.sources

    def graph(self, character):
        if character != self.view.character:
            raise ValueError("target view belongs to another character")
        return self.view

    def candidates(self, graph, component):
        if self.schedule is not None:
            record = self.schedule.get(component.component_id)
            if record and set(record["target_stroke_ids"]) != set(component.stroke_ids):
                raise ValueError("locked schedule changes component ownership")
            selected = (record or {}).get("selection", {}).get("selected")
            return [selected["candidate"]] if selected else []
        return self.source_index.candidates(graph, component)


class IntegratedV6Generator(V6ExpGenerator):
    """Explicit experimental API; construct once, call generate(character).

    A frame override and a frozen donor schedule are for controlled comparisons,
    not learned layout. Unsafe frozen placements fall back to corrected reference.
    """

    def __init__(self, source_profile, mapping_repository, target_repository):
        super().__init__(source_profile, mapping_repository)
        base_hash = mapping_repository.content_sha256()
        if target_repository.content_sha256() != base_hash:
            if not isinstance(target_repository, CorrectedStructureRepository):
                raise ValueError("target repository must be a verified correction overlay")
            if target_repository.base.content_sha256() != base_hash:
                raise ValueError("correction overlay has a different mapping ancestor")
        self.mapping_repository = mapping_repository
        self.target_repository = target_repository
        self.baseline = FullReferenceGenerator(
            source_profile, target_repository.metadata()["source_version"]
        )
        self.bridge = {
            "policy": "retain_original_source_mapping_target_only_correction_v1",
            "mapping_structure_sha256": base_hash,
            "target_structure_sha256": target_repository.content_sha256(),
            "correction_identity": getattr(target_repository, "identity", None),
            "source_profile_version": source_profile.profile_version,
            "source_realign": False,
        }

    def _select_component(self, current, graph, ids, candidates, component, occurrence_id):
        if self.index.schedule is None:
            return super()._select_component(
                current, graph, ids, candidates, component, occurrence_id
            )
        record = self.index.schedule[component.component_id]
        selected = copy.deepcopy(record["selection"]["selected"])
        candidate = selected["candidate"]
        sample = self.index.sources[candidate["sample_id"]]
        if (
            sample.character == graph.character
            or sample.character != candidate["character"]
            or sample.source_sha256 != candidate["source_sha256"]
        ):
            raise ValueError("invalid frozen donor identity")
        source = {s.standard_stroke_id: s for s in sample.strokes}
        transform = SharedTransform(**selected["transform"])
        if transform.sx <= 0 or transform.sx != transform.sy:
            raise ValueError("frozen component transform must be positive isotropic")
        output = {s.standard_stroke_id: i for i, s in enumerate(current.strokes)}
        replacements, ratios = {}, []
        for target_id, source_id in zip(ids, candidate["stroke_ids"], strict=True):
            stroke = source[source_id]
            xy = transform.apply(stroke.points)
            index = output[target_id]
            replacements[index] = {"points": xy, "pressure": stroke.pressure, "time": stroke.t_ms}
            ratios.append(path_length(xy) / max(path_length(glyph_curves(current)[index]), 1e-9))
        proposed = assemble(current, replacements, POLICY)
        errors = invariants(proposed, graph)
        extra = crossing_pairs(glyph_curves(proposed)) - crossing_pairs(glyph_curves(current))
        ok = not errors and not extra and min(ratios) >= 0.4 and max(ratios) <= 2.5
        selected.update(
            accepted=ok,
            decision="accepted" if ok else "rejected",
            errors=errors,
            new_crossings_vs_A=sorted(extra),
            length_ratios_vs_A=ratios,
        )
        reason = None if ok else "frozen donor unsafe in corrected reference; retain reference"
        return (proposed if ok else current), {
            "selected": selected if ok else None,
            "candidates": [selected],
            "fallback_reason": reason,
            "fully_validated_candidates": 1,
        }

    def generate(self, character, *, frame=None, locked_schedule=None, occurrence_id=0):
        if locked_schedule is not None and (
            locked_schedule.get("character") != character
            or locked_schedule.get("bridge", {}).get("mapping_structure_sha256")
            != self.bridge["mapping_structure_sha256"]
        ):
            raise ValueError("frozen schedule belongs to a different target or mapping database")
        original = self.mapping_repository.get(character)
        target = self.target_repository.get(character)
        if identity(original) != identity(target):
            raise ValueError("target correction changes stroke identity/order or component mapping")
        transform = reference_frame(target) if frame is None else frame
        graph = framed_graph(target, transform)
        expanded = expand_views(target, self.target_repository, allowed=NESTED_COMPONENTS)
        view = framed_graph(expanded.graph, transform)
        schedule = (
            None
            if locked_schedule is None
            else {r["component_id"]: r for r in locked_schedule["components"]}
        )
        worker = copy.copy(self)
        worker.index = _TargetIndex(self.index, view, schedule)
        glyph, diagnostics = SourceComponentGenerator.generate(
            worker, graph, occurrence_id=occurrence_id
        )
        accepted = set(diagnostics["accepted_stroke_ids"])
        for output, reference in zip(glyph.strokes, graph.strokes, strict=True):
            if output.standard_stroke_id not in accepted:
                if [(p.x, p.y) for p in output.points] != reference.median:
                    raise RuntimeError("reference fallback lost vertices")
            else:
                output.style_source = "v6_complete_author_source"
        glyph.generator = POLICY
        glyph.canvas_fit = {
            "policy": POLICY,
            "reference_transform": asdict(transform),
            "before_candidate_placement": True,
            "bridge": self.bridge,
        }
        diagnostics.update(
            character=character,
            policy=POLICY,
            bridge=self.bridge,
            reference_transform=asdict(transform),
            source_mapping_identity_verified=True,
            target_capture_used=False,
            locked_schedule=locked_schedule is not None,
            correction_event=getattr(self.target_repository, "events", {}).get(character),
            nested_views=expanded.diagnostics,
        )
        return glyph, diagnostics
