"""Explicit physical template geometry; raster recognition is not a layout input."""

import base64
import io
import math
from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar

from .schema import PageProfile
from .template_revision import SCHEMA as REVISION_SCHEMA
from .template_revision import TemplateRevision
from .template_validation import TemplateValidationError, converted


@dataclass(frozen=True)
class TemplateBackground:
    """Embedded PNG reference only; never a machine operation."""

    png_base64: str
    sha256: str

    def __post_init__(self):
        from PIL import Image

        if not isinstance(self.png_base64, str) or len(self.png_base64) > 2_000_000:
            raise ValueError("Template background exceeds its size budget")
        try:
            raw = base64.b64decode(self.png_base64, validate=True)
            if sha256(raw).hexdigest() != self.sha256:
                raise ValueError("Template background hash mismatch")
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != "PNG" or image.width * image.height > 4_000_000:
                    raise ValueError(
                        "Template background must be a PNG of at most 4 million pixels"
                    )
                image.verify()
        except (OSError, SyntaxError) as error:
            raise ValueError("Invalid template background PNG") from error

    def png_bytes(self):
        return base64.b64decode(self.png_base64, validate=True)


def _numbers(values):
    return all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values
    )


@dataclass(frozen=True)
class Region:
    name: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or not _numbers(self.bounds):
            raise ValueError("Invalid template region")
        if min(self.width_mm, self.height_mm) <= 0:
            raise ValueError("Template region must have positive area")

    @property
    def bounds(self):
        return self.x_mm, self.y_mm, self.x_mm + self.width_mm, self.y_mm + self.height_mm


@dataclass(frozen=True)
class Anchor:
    name: str
    x_mm: float
    y_mm: float

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or not _numbers((self.x_mm, self.y_mm)):
            raise ValueError("Invalid template anchor")


@dataclass(frozen=True)
class TemplateRule:
    name: str
    points: tuple[tuple[float, float], ...]
    width_mm: float = 0.3

    def __post_init__(self):
        points = tuple(tuple(p) for p in self.points)
        if (
            not isinstance(self.name, str)
            or not self.name
            or not 2 <= len(points) <= 10000
            or any(len(p) != 2 or not _numbers(p) for p in points)
            or not _numbers((self.width_mm,))
            or not 0 < self.width_mm <= 5
        ):
            raise ValueError("Invalid template rule")
        object.__setattr__(self, "points", points)


@dataclass(frozen=True)
class TemplateFace:
    body: Region
    rules: tuple[TemplateRule, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    reserved: tuple[Region, ...] = ()
    background: TemplateBackground | None = None

    def __post_init__(self):
        if isinstance(self.background, dict):
            object.__setattr__(
                self, "background", converted(self.background, TemplateBackground, "background")
            )
        if self.background is not None and not isinstance(self.background, TemplateBackground):
            raise ValueError("Invalid template background")
        if isinstance(self.body, dict):
            object.__setattr__(self, "body", converted(self.body, Region, "body"))
        if not isinstance(self.body, Region):
            raise ValueError("Invalid template body")  # noqa: TRY004 - serialized configuration
        for name, cls in (("rules", TemplateRule), ("anchors", Anchor), ("reserved", Region)):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)) or len(values) > 1000:
                raise TemplateValidationError(
                    "template-collection-invalid", "Invalid template geometry", ((name,),)
                )
            items = tuple(converted(v, cls, name, i) for i, v in enumerate(values))
            if len(items) > 1000 or any(not isinstance(v, cls) for v in items):
                raise ValueError("Invalid template geometry")
            if len({v.name for v in items}) != len(items):
                duplicate = next(
                    v.name
                    for i, v in enumerate(items)
                    if any(old.name == v.name for old in items[:i])
                )
                raise TemplateValidationError(
                    "template-name-duplicate",
                    "Duplicate template geometry name",
                    tuple((name, i, "name") for i, v in enumerate(items) if v.name == duplicate),
                )
            object.__setattr__(self, name, items)
        regions = (self.body, *self.reserved)
        paths = (("body",), *(("reserved", i) for i in range(len(self.reserved))))
        if len({r.name for r in regions}) != len(regions):
            duplicate = next(
                v.name
                for i, v in enumerate(regions)
                if any(old.name == v.name for old in regions[:i])
            )
            raise TemplateValidationError(
                "template-name-duplicate",
                "Duplicate template region name",
                tuple((*p, "name") for p, r in zip(paths, regions) if r.name == duplicate),
            )
        for i, a in enumerate(regions):
            for j, b in enumerate(regions[i + 1 :], i + 1):
                if max(a.bounds[0], b.bounds[0]) < min(a.bounds[2], b.bounds[2]) and max(
                    a.bounds[1], b.bounds[1]
                ) < min(a.bounds[3], b.bounds[3]):
                    raise TemplateValidationError(
                        "template-regions-overlap",
                        "Template content regions overlap",
                        (paths[i], paths[j]),
                    )


@dataclass(frozen=True)
class PageTemplate:
    SCHEMA: ClassVar[str] = "inkstruct_page_template_v1"
    name: str
    width_mm: float
    height_mm: float
    first: TemplateFace
    continuation: TemplateFace
    mode: str = "preprinted"
    offset_x_mm: float = 0
    offset_y_mm: float = 0
    source_sha256: str = ""
    calibration: str = "unreviewed"
    schema_version: str = "inkstruct_page_template_v1"
    revision: TemplateRevision | None = None

    def __post_init__(self):
        for key in ("first", "continuation"):
            value = getattr(self, key)
            if isinstance(value, dict):
                value = converted(value, TemplateFace, key)
                object.__setattr__(self, key, value)
            if not isinstance(value, TemplateFace):
                raise ValueError("Invalid template face")  # noqa: TRY004 - serialized configuration
        if (
            not isinstance(self.name, str)
            or not self.name
            or self.schema_version != self.SCHEMA
            or self.mode not in {"preprinted", "blank"}
            or self.calibration not in {"unreviewed", "user-measured"}
            or not _numbers((self.width_mm, self.height_mm, self.offset_x_mm, self.offset_y_mm))
            or min(self.width_mm, self.height_mm) <= 0
        ):
            raise ValueError("Invalid page template")
        if self.source_sha256 and (
            len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
        ):
            raise ValueError("Invalid template source hash")
        # Lines are measured once. A different continuation width needs reflow,
        # which v1 deliberately refuses rather than shrinking/reusing wrong wraps.
        if abs(self.first.body.width_mm - self.continuation.body.width_mm) > 1e-9:
            raise TemplateValidationError(
                "template-body-width-mismatch",
                "Template v1 requires equal first and continuation body widths",
                (("first", "body", "width_mm"), ("continuation", "body", "width_mm")),
            )
        # Table pagination uses one continuation capacity. Require it to fit every
        # first-page atomic row group, including a table that starts on page one.
        if self.continuation.body.height_mm < self.first.body.height_mm:
            raise TemplateValidationError(
                "template-body-height-mismatch",
                "Continuation body must be at least as tall as first body",
                (("first", "body", "height_mm"), ("continuation", "body", "height_mm")),
            )
        for face_name in ("first", "continuation"):
            face = getattr(self, face_name)
            for i, region in enumerate((face.body, *face.reserved)):
                path = (face_name, "body") if i == 0 else (face_name, "reserved", i - 1)
                a, b, c, d = region.bounds
                self._inside(a, b, 0, path)
                self._inside(c, d, 0, path)
            for i, anchor in enumerate(face.anchors):
                self._inside(anchor.x_mm, anchor.y_mm, 0, (face_name, "anchors", i))
            for i, rule in enumerate(face.rules):
                for j, (x, y) in enumerate(rule.points):
                    self._inside(x, y, rule.width_mm / 2, (face_name, "rules", i, "points", j))

    def _inside(self, x, y, radius, path=()):
        x, y = x + self.offset_x_mm, y + self.offset_y_mm
        if not radius <= x <= self.width_mm - radius or not radius <= y <= self.height_mm - radius:
            raise TemplateValidationError(
                "template-outside-paper",
                "Template geometry including calibration lies outside paper",
                (path, ("offset_x_mm",), ("offset_y_mm",)),
            )

    def face(self, page_index):
        return self.first if page_index == 0 else self.continuation

    def bounds(self, page_index):
        a, b, c, d = self.face(page_index).body.bounds
        return (
            a + self.offset_x_mm,
            b + self.offset_y_mm,
            c + self.offset_x_mm,
            d + self.offset_y_mm,
        )

    @property
    def page(self):
        return PageProfile(self.width_mm, self.height_mm, 0)


def template_from_record(value):
    """Version dispatch; v1 remains byte-for-byte unchanged on serialization."""
    from dataclasses import replace

    from .schema import digest

    if value.get("schema_version") == REVISION_SCHEMA:
        if (set(value) != {'schema_version', 'revision', 'template'}
                or not isinstance(value['template'], dict) or not isinstance(value['revision'], dict)):
            raise ValueError("无效模板修订封装")
        metadata = TemplateRevision(**value['revision'])
        inner = value['template']
        if inner.get('schema_version') == REVISION_SCHEMA or digest(inner) != metadata.content_hash:
            raise ValueError("模板修订与内容身份不一致")
        return replace(template_from_record(inner), revision=metadata)
    if 'revision' in value:
        if value['revision'] is not None:
            raise ValueError("模板修订必须使用独立封装")
        value = {key: item for key, item in value.items() if key != 'revision'}
    if value.get("schema_version") == "inkstruct_page_template_v3":
        from .flow_template import FlowTemplate
        return FlowTemplate(**value)
    if value.get("schema_version", PageTemplate.SCHEMA) == PageTemplate.SCHEMA:
        return PageTemplate(**value)
    from .template_slots import SlottedPageTemplate

    if value.get("schema_version") == SlottedPageTemplate.SCHEMA:
        return SlottedPageTemplate(**value)
    raise ValueError("Unsupported page template version")


@dataclass(frozen=True)
class TemplateBinding:
    """Move complete top-level source nodes into a named reserved region.

    Repeated fields retain source occurrence IDs. No independent copy of field
    text is stored in the template or project configuration.
    """

    region: str
    node_ids: tuple[str, ...]
    pages: str = "first"
    scale: float = 1
    anchor: str | None = None
    schema_version: str = "inkstruct_template_binding_v1"

    def __post_init__(self):
        if not isinstance(self.node_ids, (tuple, list)):
            raise ValueError("Template field source IDs must be an array")  # noqa: TRY004 - serialized configuration
        ids = tuple(self.node_ids)
        if (
            not isinstance(self.region, str)
            or not self.region
            or not 1 <= len(ids) <= 1000
            or any(not isinstance(v, str) or not v for v in ids)
            or len(set(ids)) != len(ids)
            or self.pages not in {"first", "all"}
            or not _numbers((self.scale,))
            or not 0.25 <= self.scale <= 4
            or (self.anchor is not None and (not isinstance(self.anchor, str) or not self.anchor))
            or self.schema_version != "inkstruct_template_binding_v1"
        ):
            raise ValueError("Invalid template field binding")
        object.__setattr__(self, "node_ids", ids)
