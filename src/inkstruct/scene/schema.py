from __future__ import annotations

from dataclasses import dataclass

from ..document.limits import allocating_page, expanded_points
from ..document.schema import Diagnostic, PageProfile, SourceSpan
from ..document.template import TemplateBackground


@dataclass(frozen=True)
class PaintOp:
    occurrence_id: str
    points: tuple[tuple[float, float], ...]
    width_mm: float
    color: str = "#111827"
    execution_domain: str = "page"

    def __post_init__(self):
        expanded_points(len(self.points))


@dataclass(frozen=True)
class Fragment:
    fragment_id: str
    occurrence_id: str
    node_id: str
    span: SourceSpan
    text: str
    page_index: int
    line_index: int
    x_mm: float
    baseline_mm: float
    advance_mm: float
    logical_bounds: tuple[float, float, float, float]
    ink_bounds: tuple[float, float, float, float] | None
    asset_id: str | None
    status: str
    repeated: bool = False
    container_id: str | None = None
    source_resource_id: str | None = None
    glyph_origin_offset_mm: float = 0
    glyph_em_mm: float = 0

    @property
    def selection_bounds(self):
        if self.ink_bounds is None:
            return self.logical_bounds
        a, b = self.logical_bounds, self.ink_bounds
        return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


@dataclass(frozen=True)
class RasterOp:
    occurrence_id: str
    node_id: str
    span: SourceSpan
    source: str
    original_sha256: str | None
    png_base64: str | None
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class Page:
    index: int
    fragments: tuple[Fragment, ...]
    paint_ops: tuple[PaintOp, ...]
    preview_ops: tuple[PaintOp, ...] = ()
    background: TemplateBackground | None = None
    images: tuple[RasterOp, ...] = ()
    source_layout: str = ""

    def __post_init__(self):
        allocating_page(self.index + 1)


@dataclass(frozen=True)
class LayoutSnapshot:
    snapshot_id: str
    job_key: str
    document_id: str
    revision: int
    page_profile: PageProfile
    pages: tuple[Page, ...]
    diagnostics: tuple[Diagnostic, ...]
    resource_key: str
    layout_version: str

    @property
    def exportable(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)

    @property
    def fragments(self) -> tuple[Fragment, ...]:
        return tuple(f for p in self.pages for f in p.fragments)

    @property
    def plotter_exportable(self) -> bool:
        return self.exportable and not any(p.images for p in self.pages)
