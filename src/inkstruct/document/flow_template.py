"""Template v3: one body stream, named fields and explicitly ordered page groups."""

import re
from dataclasses import asdict, dataclass, replace
from typing import ClassVar

from .schema import PageProfile, digest
from .template import Region, TemplateBackground, TemplateRule, _numbers
from .template_revision import TemplateRevision

SCHEMA = "inkstruct_page_template_v3"
FIELD_PROTOCOL = "inkstruct_named_fields_v1"
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class NamedField:
    field_id: str
    label: str
    required: bool = False
    value_type: str = "markdown"

    def __post_init__(self):
        if (
            not isinstance(self.field_id, str)
            or not IDENTIFIER.fullmatch(self.field_id)
            or not isinstance(self.label, str)
            or not self.label
            or len(self.label) > 256
            or type(self.required) is not bool
            or self.value_type not in {"markdown", "text", "number", "date"}
        ):
            raise ValueError("Invalid named template field")


@dataclass(frozen=True)
class PaperGrid:
    first_mm: float
    last_mm: float
    rows: int

    def __post_init__(self):
        if (not _numbers((self.first_mm, self.last_mm)) or self.first_mm < 0
                or type(self.rows) is not int or not 1 <= self.rows <= 1000
                or (self.rows == 1 and self.first_mm != self.last_mm)
                or (self.rows > 1 and self.pitch < 0.1)):
            raise ValueError("行格须填写有效的首末基线和 1–1000 行；单行的首末基线相同")

    @property
    def pitch(self):
        return (self.last_mm - self.first_mm) / (self.rows - 1) if self.rows > 1 else 0

    def baselines(self):
        return (self.first_mm + index * self.pitch for index in range(self.rows))


@dataclass(frozen=True)
class TextFrame:
    frame_id: str
    label: str
    region: Region
    role: str = "body"
    order: int = 1
    field_id: str = ""
    paper_grid: PaperGrid | None = None

    def __post_init__(self):
        if isinstance(self.region, dict):
            object.__setattr__(self, "region", Region(**self.region))
        if isinstance(self.paper_grid, dict):
            object.__setattr__(self, "paper_grid", PaperGrid(**self.paper_grid))
        if (
            not isinstance(self.region, Region)
            or not self.frame_id
            or not self.label
            or not isinstance(self.frame_id, str)
            or not isinstance(self.label, str)
            or self.role not in {"body", "field", "page_number"}
            or type(self.order) is not int
            or not 1 <= self.order <= 1000
            or (self.role == "field" and not IDENTIFIER.fullmatch(self.field_id))
            or (self.role != "field" and self.field_id != "")
        ):
            raise ValueError("Invalid template text frame")
        if self.paper_grid is not None and (
            self.role != "body" or not isinstance(self.paper_grid, PaperGrid)
            or self.paper_grid.last_mm > self.region.height_mm
        ):
            raise ValueError("纸张行格仅用于正文框，基线须位于框内")


@dataclass(frozen=True)
class PageLayout:
    layout_id: str
    label: str
    frames: tuple[TextFrame, ...] = ()
    rules: tuple[TemplateRule, ...] = ()
    background: TemplateBackground | None = None
    source_page: int | None = None
    source_sha256: str = ""
    source_size_mm: tuple[float, float] | None = None

    def __post_init__(self):
        for key, cls in (("frames", TextFrame), ("rules", TemplateRule)):
            raw = getattr(self, key)
            if not isinstance(raw, (tuple, list)) or len(raw) > 100:
                raise ValueError("Too many layout objects")
            values = tuple(cls(**v) if isinstance(v, dict) else v for v in raw)
            if any(not isinstance(v, cls) for v in values):
                raise ValueError("Invalid layout object")
            object.__setattr__(self, key, values)
        if isinstance(self.background, dict):
            object.__setattr__(self, "background", TemplateBackground(**self.background))
        if self.background is not None and not isinstance(self.background, TemplateBackground):
            raise ValueError("Invalid layout background")
        if self.source_size_mm is not None:
            values = tuple(self.source_size_mm)
            if (
                len(values) != 2
                or not _numbers(values)
                or not 0 < min(values) <= max(values) <= 2000
            ):
                raise ValueError("Invalid PDF physical dimensions")
            object.__setattr__(self, "source_size_mm", values)
        if (
            not isinstance(self.layout_id, str)
            or not self.layout_id
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.layout_id)
            or not isinstance(self.label, str)
            or not self.label
            or len({f.frame_id for f in self.frames}) != len(self.frames)
            or len({f.order for f in self.body_frames}) != len(self.body_frames)
            or (
                self.source_page is not None
                and (type(self.source_page) is not int or self.source_page < 1)
            )
            or (self.source_sha256 and not re.fullmatch("[0-9a-f]{64}", self.source_sha256))
        ):
            raise ValueError("Invalid layout identity, body order or PDF provenance")
        for i, a in enumerate(self.frames):
            for b in self.frames[i + 1 :]:
                x, y, r, s = a.region.bounds
                u, v, w, z = b.region.bounds
                if max(x, u) < min(r, w) and max(y, v) < min(s, z):
                    raise ValueError(f"Text frames overlap: {a.label} / {b.label}")

    @property
    def body_frames(self):
        return tuple(sorted((f for f in self.frames if f.role == "body"), key=lambda f: f.order))


@dataclass(frozen=True)
class FlowTemplate:
    SCHEMA: ClassVar[str] = SCHEMA
    name: str = "简单模板"
    kind: str = "simple"
    width_mm: float = 210
    height_mm: float = 297
    margins_mm: tuple[float, ...] = (20, 20, 20, 20)  # top, right, bottom, left
    layouts: tuple[PageLayout, ...] = ()
    start_pages: tuple[str, ...] = ()
    loop_pages: tuple[str, ...] = ()
    finish_cycle: bool = False
    fields: tuple[NamedField, ...] = ()
    mode: str = "preprinted"
    offset_x_mm: float = 0
    offset_y_mm: float = 0
    calibration: str = "unreviewed"
    migration: tuple[tuple[str, str], ...] = ()
    schema_version: str = SCHEMA
    revision: TemplateRevision | None = None

    def __post_init__(self):
        for key, cls in (("layouts", PageLayout), ("fields", NamedField)):
            values = getattr(self, key)
            if not isinstance(values, (list, tuple)) or len(values) > 64:
                raise ValueError("Template collection exceeds 64 entries")
            values = tuple(cls(**v) if isinstance(v, dict) else v for v in values)
            if any(not isinstance(v, cls) for v in values):
                raise ValueError("Invalid template collection")
            object.__setattr__(self, key, values)
        for key in ("margins_mm", "start_pages", "loop_pages", "migration"):
            object.__setattr__(
                self, key, tuple(tuple(v) if isinstance(v, list) else v for v in getattr(self, key))
            )
        if (
            self.schema_version != SCHEMA
            or self.kind not in {"simple", "custom"}
            or not isinstance(self.name, str)
            or not self.name
            or not _numbers((self.width_mm, self.height_mm, self.offset_x_mm, self.offset_y_mm))
            or not 0
            < min(self.width_mm, self.height_mm)
            <= max(self.width_mm, self.height_mm)
            <= 2000
            or type(self.finish_cycle) is not bool
            or self.mode not in {"preprinted", "blank"}
            or self.calibration not in {"unreviewed", "user-measured"}
            or len(self.margins_mm) != 4
            or not _numbers(self.margins_mm)
            or min(self.margins_mm) < 0
            or len({f.field_id for f in self.fields}) != len(self.fields)
            or len({p.layout_id for p in self.layouts}) != len(self.layouts)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.migration)
        ):
            raise ValueError("Invalid template v3")
        if self.kind == "simple":
            if (
                self.layouts
                or self.start_pages
                or self.loop_pages
                or self.fields
                or self.finish_cycle
            ):
                raise ValueError(
                    "Simple templates have one repeated body region and no field declarations"
                )
            top, right, bottom, left = self.margins_mm
            if left + right >= self.width_mm or top + bottom >= self.height_mm:
                raise ValueError("Margins leave no body area")
        else:
            ids = {p.layout_id for p in self.layouts}
            if (
                not self.loop_pages
                or len(self.start_pages) + len(self.loop_pages) > 128
                or any(v not in ids for v in (*self.start_pages, *self.loop_pages))
            ):
                raise ValueError("Custom templates require a valid ordered loop page group")
        declared = {f.field_id for f in self.fields}
        for p in self.effective_layouts:
            for f in p.frames:
                if f.role == "field" and f.field_id not in declared:
                    raise ValueError(f"Frame references undeclared field: {f.field_id}")
                a, b, c, d = f.region.bounds
                self.inside(a, b)
                self.inside(c, d)
            for r in p.rules:
                for x, y in r.points:
                    self.inside(x, y, r.width_mm / 2)
        if sum(len(p.background.png_base64) for p in self.layouts if p.background) > 12_000_000:
            raise ValueError("Template backgrounds exceed 12 MB encoded budget")

    def inside(self, x, y, radius=0):
        x, y = x + self.offset_x_mm, y + self.offset_y_mm
        if not radius <= x <= self.width_mm - radius or not radius <= y <= self.height_mm - radius:
            raise ValueError("Template geometry including calibration lies outside paper")

    @property
    def effective_layouts(self):
        if self.kind == "custom":
            return self.layouts
        top, right, bottom, left = self.margins_mm
        f = TextFrame(
            "body",
            "正文",
            Region("body", left, top, self.width_mm - left - right, self.height_mm - top - bottom),
        )
        return (PageLayout("simple", "简单模板", (f,)),)

    @property
    def effective_loop(self):
        return self.loop_pages if self.kind == "custom" else ("simple",)

    def layout(self, index):
        key = (
            self.start_pages[index]
            if index < len(self.start_pages)
            else self.effective_loop[(index - len(self.start_pages)) % len(self.effective_loop)]
        )
        return next(p for p in self.effective_layouts if p.layout_id == key)

    @property
    def page(self):
        return PageProfile(self.width_mm, self.height_mm, 0)

    def skeleton(self):
        return "".join(f":::field {f.field_id}\n\n:::\n\n" for f in self.fields) + "# 正文\n\n"


def migrate_layout(template):
    """Explicit copy of legacy geometry, never infer a source-to-field mapping."""
    fields = tuple(
        NamedField(
            s.slot_id,
            s.label,
            s.required,
            "text" if s.kind == "text" else "markdown",
        )
        for s in getattr(template, "slots", ())
    )
    by_region = {s.region: s.slot_id for s in getattr(template, "slots", ())}
    layouts = []
    for key, face in (("first", template.first), ("continuation", template.continuation)):
        frames = [TextFrame("body", "正文", face.body)]
        for i, r in enumerate(face.reserved):
            if r.name not in by_region:
                number = len(by_region) + 1
                while f"field_{number}" in {f.field_id for f in fields}:
                    number += 1
                by_region[r.name] = f"field_{number}"
            fid = by_region[r.name]
            if fid not in {f.field_id for f in fields}:
                fields = (*fields, NamedField(fid, r.name))
            frames.append(TextFrame(f"field-{i + 1}", r.name, r, "field", field_id=fid))
        layouts.append(
            PageLayout(
                key,
                "原首页" if key == "first" else "原续页",
                tuple(frames),
                face.rules,
                face.background,
            )
        )
    return FlowTemplate(
        name=template.name,
        kind="custom",
        width_mm=template.width_mm,
        height_mm=template.height_mm,
        layouts=tuple(layouts),
        start_pages=("first",),
        loop_pages=("continuation",),
        fields=fields,
        mode=template.mode,
        offset_x_mm=template.offset_x_mm,
        offset_y_mm=template.offset_y_mm,
        calibration=template.calibration,
        migration=(
            ("source_schema", template.schema_version),
            ("source_sha256", digest(asdict(template))),
            ("content_mapping", "manual; original document and source retained"),
            (
                "legacy_field_review",
                "scales, anchors and page policies require explicit review; no source binding conversion",
            ),
        ),
    )


def resized(template, width, height):
    """Paper change keeps millimetre geometry; reference background stretches to paper."""
    return replace(template, width_mm=width, height_mm=height)
