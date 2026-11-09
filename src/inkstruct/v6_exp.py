"""v6 exp: complete author exemplars, with complete reference polylines as fallback.

Opt-in only. Geometry does not use v4 prototypes, 8-point controls, prototype
averaging or B-Splines. Matching descriptors may sample 16 anchors; those anchors
never replace the points in the delivered trajectory.
"""

from __future__ import annotations

from .component_views import expand_views
from .exemplar_generation import SourceComponentGenerator
from .exemplar_index import ExemplarIndex
from .geometry import path_length
from .schemas import GeneratedGlyph, GeneratedPoint, GeneratedStroke
from .source_trajectory import TRAJECTORY_SCHEMA, arc_parameters
from .trajectory_experiment import invariants

POLICY = "v6_exp_raw_or_reference_v1"
NESTED_COMPONENTS = ("需", "汤")


class FullReferenceGenerator:
    """Identity geometry in the standard frame, including every original vertex."""

    component_mode = "adaptive"
    component_strength = 1.0

    def __init__(self, profile, structure_version):
        self.profile = profile
        self.structure_version = structure_version

    def generate(self, graph):
        strokes, cursor = [], 0
        for stroke in graph.strokes:
            xy = stroke.median
            if len(xy) < 2 or path_length(xy) <= 1e-9:
                raise ValueError(
                    f"degenerate reference stroke: {graph.character}/{stroke.stroke_id}"
                )
            duration = max(80, round(path_length(xy) * 700))
            points = [
                GeneratedPoint(
                    float(x),
                    float(y),
                    cursor + round(t * duration),
                    0.5,
                    "down"
                    if i < len(xy) - 1
                    else ("end" if stroke.order == len(graph.strokes) else "up"),
                )
                for i, ((x, y), t) in enumerate(zip(xy, arc_parameters(xy), strict=True))
            ]
            strokes.append(
                GeneratedStroke(
                    stroke.stroke_id,
                    stroke.order,
                    0.45,
                    points,
                    "v6_complete_reference",
                    stroke.component_path,
                )
            )
            cursor = points[-1].t_ms + 60
        result = GeneratedGlyph(
            "personal_trajectory_v1",
            graph.character,
            graph.codepoint,
            graph.locale,
            self.profile.writer_id,
            self.structure_version,
            self.profile.profile_version,
            POLICY + ":reference",
            0.45,
            strokes,
            {
                "policy": "reference_identity_v1",
                "applied": False,
                "scale": 1.0,
                "translation": [0.0, 0.0],
            },
        )
        errors = invariants(result, graph)
        if errors:
            raise ValueError(f"invalid reference: {errors}")
        return result


class V6ExemplarIndex(ExemplarIndex):
    """Existing shape/role gates, with separately logged validated nested views."""

    def __init__(self, profile, repository, *, expand_nested=True):
        self.expand_nested = expand_nested
        self.view_diagnostics = {}
        super().__init__(profile, repository, nested_views=False)

    def graph(self, character):
        if character not in self.graphs:
            graph = self.repository.get(character)
            if self.expand_nested:
                views = expand_views(graph, self.repository, allowed=NESTED_COMPONENTS)
                graph = views.graph
                self.view_diagnostics[character] = views.diagnostics
            self.graphs[character] = graph
        return self.graphs[character]


class V6ExpGenerator(SourceComponentGenerator):
    """One real instance and one positive isotropic transform per complete part.

    Reuses the frozen donor selector, but its placement frame and every fallback
    come from full reference curves rather than the v4 generator. Candidates must
    match component identity, variant, role, parent layout, count and shape gates.
    Root-only glyphs remain reference-only in this version.
    """

    def __init__(self, source_profile, repository, *, expand_nested=True):
        if source_profile.trajectory_schema != TRAJECTORY_SCHEMA:
            raise ValueError("v6 requires a complete-source archive schema")
        if source_profile.build_identity.get("structure_sha256") != repository.content_sha256():
            raise ValueError("v6 source mappings use a different structure database")
        # An empty but valid archive must still support complete-reference fallback.
        self.baseline = FullReferenceGenerator(
            source_profile, repository.metadata()["source_version"]
        )
        self.mode = "source-raw"
        self.anchor_cache = {}
        self.index = V6ExemplarIndex(source_profile, repository, expand_nested=expand_nested)

    def generate(self, graph, *, occurrence_id=0):
        glyph, report = super().generate(graph, occurrence_id=occurrence_id)
        for component in report["components"]:
            for candidate in component.get("selection", {}).get("candidates", []):
                for old, new in [
                    ("new_crossings_vs_A", "new_crossings_vs_reference"),
                    ("length_ratios_vs_A", "length_ratios_vs_reference"),
                ]:
                    if old in candidate:
                        candidate[new] = candidate.pop(old)
        glyph.generator = POLICY
        accepted = set(report["accepted_stroke_ids"])
        for generated, standard in zip(glyph.strokes, graph.strokes, strict=True):
            if generated.standard_stroke_id not in accepted:
                actual = [(p.x, p.y) for p in generated.points]
                if actual != [tuple(p) for p in standard.median]:
                    raise RuntimeError("v6 fallback lost reference vertices")
            else:
                generated.style_source = "v6_complete_author_source"
        report.update(
            {
                "policy": POLICY,
                "reference_frame": "identity standard glyph frame",
                "view_diagnostics": self.index.view_diagnostics.get(graph.character, []),
                "fallback_policy": "complete reference polyline; never v4",
                "fallback_stroke_ids": [
                    s.stroke_id for s in graph.strokes if s.stroke_id not in accepted
                ],
                "no_donor": not bool(accepted),
                "fallback_reason": None
                if accepted
                else "no accepted component; complete reference retained",
                "new_strict_crossings_vs_reference": report.pop("new_strict_crossings_vs_baseline"),
                "confidence_semantics": "alignment and inherited placeholder scores, not style quality",
                "pressure_time": "source pressure and intra-stroke intervals retained; reference pressure .5 and 700 ms/unit; globally resequenced with 60 ms gaps",
            }
        )
        return glyph, report
