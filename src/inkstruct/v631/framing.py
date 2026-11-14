"""Build the author-independent reference frame and component baseline."""

from __future__ import annotations

import copy
from dataclasses import asdict

import numpy as np

from .component_views import expand_views
from .initial_components import SourceComponentGenerator
from ..geometry import bbox
from ..structure_corrections import CorrectedStructureRepository
from ..structures import _component_bbox
from ..trajectory_experiment import SharedTransform
from .reference import NESTED_COMPONENTS, FullReferenceGenerator, ReferenceComponentGenerator

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


def reference_frame(graph):
    """Match the public frame to the existing capture normalization (extent .85)."""
    xy = np.asarray([p for s in graph.strokes for p in s.median], dtype=float)
    if not len(xy) or not np.isfinite(xy).all():
        raise ValueError("invalid reference frame")
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = float(max(hi - lo))
    if span <= 1e-9:
        raise ValueError("degenerate reference frame")
    scale = .85 / span
    offset = .5 - scale * (hi + lo) / 2
    return SharedTransform(scale, scale, float(offset[0]), float(offset[1]))


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
    def __init__(self, source_index, view):
        self.source_index, self.view = source_index, view
        self.sources = source_index.sources

    def graph(self, character):
        if character != self.view.character:
            raise ValueError("target view belongs to another character")
        return self.view

    def candidates(self, graph, component):
        return self.source_index.candidates(graph, component)


class FramedComponentGenerator(ReferenceComponentGenerator):
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

    def generate(self, character):
        original = self.mapping_repository.get(character)
        target = self.target_repository.get(character)
        if identity(original) != identity(target):
            raise ValueError("target correction changes stroke identity/order or component mapping")
        transform = reference_frame(target)
        graph = framed_graph(target, transform)
        expanded = expand_views(target, self.target_repository, allowed=NESTED_COMPONENTS)
        view = framed_graph(expanded.graph, transform)
        worker = copy.copy(self)
        worker.index = _TargetIndex(self.index, view)
        glyph, diagnostics = SourceComponentGenerator.generate(worker, graph)
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
            locked_schedule=False,
            correction_event=getattr(self.target_repository, "events", {}).get(character),
            nested_views=expanded.diagnostics,
        )
        return glyph, diagnostics
