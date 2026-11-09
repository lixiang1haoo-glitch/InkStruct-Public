from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]
PathPoints = tuple[Point, ...]


@dataclass(frozen=True)
class PlotStroke:
    """Immutable placed geometry; execution direction never edits source assets.

    stroke_id identifies this placed instance, source_stroke_id its asset stroke.
    Contiguous execution domains retain their relative order when routing.
    """

    stroke_id: str
    points: PathPoints
    width_mm: float = 0.3
    occurrence_id: str | None = None
    source_stroke_id: str | None = None
    execution_domain: str = "page"

    def __post_init__(self):
        if not self.stroke_id or not self.execution_domain:
            raise ValueError("Plot strokes require instance and execution domain IDs")
        if not math.isfinite(self.width_mm) or round(self.width_mm, 6) <= 0:
            raise ValueError("Plot stroke width must be finite and positive")
        points = tuple(tuple(p) for p in self.points)
        if len(points) < 2:
            raise ValueError(f"{self.stroke_id}: single-point strokes require explicit adaptation")
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
            raise ValueError(f"{self.stroke_id}: invalid plot coordinates")
        # Precision is part of the SVG contract: reject paths that collapse on export.
        if len({(round(x, 6), round(y, 6)) for x, y in points}) < 2:
            raise ValueError(f"{self.stroke_id}: zero-length stroke at SVG precision")
        if self.execution_domain == 'registration' and (
            not self.stroke_id.startswith('registration:') or len(points) != 2
            or self.width_mm != 0.01 or points[0][1] != points[1][1]
            or math.dist(*points) > 1.000001 or self.source_stroke_id is not None
        ):
            raise ValueError('Invalid explicit registration mark')
        object.__setattr__(self, "points", points)


@dataclass(frozen=True)
class PlotPage:
    index: int
    width_mm: float
    height_mm: float
    strokes: tuple[PlotStroke, ...]

    def __post_init__(self):
        if self.index < 0 or int(self.index) != self.index:
            raise ValueError("Invalid plot page index")
        if any(
            not math.isfinite(v) or not 0 < v <= 2000
            for v in (
                self.width_mm,
                self.height_mm,
            )
        ):
            raise ValueError("Plot page dimensions must be within (0, 2000] mm")
        object.__setattr__(self, "strokes", tuple(self.strokes))
        if len({s.stroke_id for s in self.strokes}) != len(self.strokes):
            raise ValueError("Duplicate plot stroke instance ID")
        for stroke in self.strokes:
            radius = 0 if stroke.execution_domain == 'registration' else stroke.width_mm / 2
            if any(
                x - radius < -1e-6
                or y - radius < -1e-6
                or x + radius > self.width_mm + 1e-6
                or y + radius > self.height_mm + 1e-6
                for x, y in stroke.points
            ):
                raise ValueError(f"{stroke.stroke_id}: ink exceeds plot page bounds")


@dataclass(frozen=True)
class PlotPlan:
    document_id: str
    snapshot_id: str
    pages: tuple[PlotPage, ...]
    schema_version: str = "inkstruct_plot_plan_v1"

    def __post_init__(self):
        object.__setattr__(self, "pages", tuple(self.pages))
        if tuple(p.index for p in self.pages) != tuple(range(len(self.pages))):
            raise ValueError("Plot pages must be contiguous and in document order")
