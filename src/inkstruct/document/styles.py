"""Versioned flow settings; independent from the legacy plain-text style profile."""

import math
from dataclasses import asdict, dataclass, field

from ..math.style import MathStyle
from .code_style import CodeStyle
from .flow_template import FlowTemplate
from .footnote_style import FootnoteStyle
from .glyph_corrections import GlyphCorrection
from .han_variation import HanVariation
from .images import MAX_IMAGE_CATALOG_BYTES, MAX_IMAGE_RESOURCES, ImageStyle, RasterResource
from .line_svg import SCHEMA as SVG_SCHEMA
from .line_svg import LineSvgResource
from .table_style import TableStyle
from .template import PageTemplate, TemplateBinding, template_from_record

FLOW_STYLE_VERSIONS = tuple(f"inkstruct_flow_style_v{version}" for version in range(1, 8))


def omit_versioned_fields(record):
    version = FLOW_STYLE_VERSIONS.index(record["schema_version"]) + 1
    for introduced, keys in ((3, ("latin_spacing",)), (4, ("punctuation_spacing",)),
                             (5, ("paragraph_align", "han_variation")), (6, ("han_spacing",)),
                             (7, ("digits_follow_latin",))):
        if version < introduced:
            for key in keys:
                record.pop(key)


@dataclass(frozen=True)
class FlowStyle:
    paragraph_gap_mm: float = 2
    heading_gap_mm: float = 3
    first_line_indent_mm: float = 0
    list_indent_mm: float = 8
    quote_indent_mm: float = 4
    heading_scales: tuple[float, ...] = (1.6, 1.4, 1.2, 1.1, 1, 1)
    schema_version: str = "inkstruct_flow_style_v1"
    table: TableStyle = field(default_factory=TableStyle)
    table_overrides: tuple[tuple[str, TableStyle], ...] = ()
    math: MathStyle = field(default_factory=MathStyle)
    code: CodeStyle = field(default_factory=CodeStyle)
    template: PageTemplate | None = None
    template_bindings: tuple[TemplateBinding, ...] = ()
    images: tuple[RasterResource | LineSvgResource, ...] = ()
    image: ImageStyle = field(default_factory=lambda: ImageStyle(height_mm=60))
    image_overrides: tuple[tuple[str, ImageStyle], ...] = ()
    footnote: FootnoteStyle = field(default_factory=FootnoteStyle)
    markdown_dialect: str = "markdown"
    glyph_corrections: tuple[GlyphCorrection, ...] = ()
    latin_spacing: str = "capture"
    punctuation_spacing: str = "capture"
    paragraph_align: str = "left"
    han_variation: HanVariation = field(default_factory=HanVariation)
    han_spacing: str = "full"
    digits_follow_latin: bool = False

    def layout_record(self):
        record = asdict(self)
        if self.han_spacing == "full":
            record.pop("han_spacing")
        if not self.digits_follow_latin:
            record.pop("digits_follow_latin")
        return record

    def __post_init__(self):
        if self.schema_version not in FLOW_STYLE_VERSIONS:
            raise ValueError("Unsupported flow style version")
        if self.paragraph_align not in {"left", "justify"}:
            raise ValueError("Unknown paragraph alignment")
        if isinstance(self.han_variation, dict):
            object.__setattr__(self, "han_variation", HanVariation(**self.han_variation))
        if not isinstance(self.han_variation, HanVariation):
            raise ValueError("Invalid Chinese variation configuration")  # noqa: TRY004 - serialized configuration
        if self.han_spacing not in {"full", "handwriting"}:
            raise ValueError("Unknown Han spacing policy")
        if self.punctuation_spacing not in {"capture", "handwriting"}:
            raise ValueError("Unknown punctuation spacing policy")
        if self.latin_spacing not in {"capture", "handwriting"}:
            raise ValueError("Unknown Latin spacing policy")
        if type(self.digits_follow_latin) is not bool:
            raise ValueError("Invalid body digit spacing policy")
        version = FLOW_STYLE_VERSIONS.index(self.schema_version)
        if self.digits_follow_latin:
            version = 6
        elif self.han_spacing == "handwriting":
            version = max(version, 5)
        elif self.paragraph_align != "left" or self.han_variation != HanVariation():
            version = max(version, 4)
        elif self.punctuation_spacing != "capture":
            version = max(version, 3)
        elif self.latin_spacing != "capture":
            version = max(version, 2)
        object.__setattr__(self, "schema_version", FLOW_STYLE_VERSIONS[version])
        corrections = tuple(GlyphCorrection(**v) if isinstance(v, dict) else v
                            for v in self.glyph_corrections)
        if (len(corrections) > 4096 or any(not isinstance(v, GlyphCorrection) for v in corrections)
                or len({v.key for v in corrections}) != len(corrections)):
            raise ValueError("字符校正重复或超过 4096 条")
        object.__setattr__(self, "glyph_corrections", corrections)
        if self.markdown_dialect not in {"markdown", "obsidian"}:
            raise ValueError("Unknown Markdown dialect")
        if isinstance(self.footnote, dict):
            object.__setattr__(self, "footnote", FootnoteStyle(**self.footnote))
        if not isinstance(self.footnote, FootnoteStyle):
            raise ValueError("Invalid footnote style")  # noqa: TRY004 - serialized configuration
        images = tuple(
            (LineSvgResource(**v) if v.get("schema_version") == SVG_SCHEMA else RasterResource(**v))
            if isinstance(v, dict)
            else v
            for v in self.images
        )
        if len(images) > MAX_IMAGE_RESOURCES or any(
            not isinstance(v, (RasterResource, LineSvgResource)) for v in images
        ):
            raise ValueError("Invalid image catalog")
        if len({v.source for v in images}) != len(images):
            raise ValueError("Duplicate image source")
        if (
            sum(len(v.original_base64) + len(getattr(v, "png_base64", "")) for v in images)
            > MAX_IMAGE_CATALOG_BYTES
        ):
            raise ValueError("Image catalog exceeds its 128 MB encoded-data budget")
        object.__setattr__(self, "images", images)
        if isinstance(self.image, dict):
            object.__setattr__(self, "image", ImageStyle(**self.image))
        if not isinstance(self.image, ImageStyle):
            raise ValueError("Invalid image style")  # noqa: TRY004 - serialized configuration
        image_overrides = tuple(
            (key, ImageStyle(**v) if isinstance(v, dict) else v) for key, v in self.image_overrides
        )
        if (
            len(image_overrides) > 1000
            or len({k for k, _ in image_overrides}) != len(image_overrides)
            or any(
                not isinstance(k, str) or not k or not isinstance(v, ImageStyle)
                for k, v in image_overrides
            )
        ):
            raise ValueError("Invalid image style overrides")
        object.__setattr__(self, "image_overrides", image_overrides)
        bindings = tuple(
            TemplateBinding(**v) if isinstance(v, dict) else v for v in self.template_bindings
        )
        if len(bindings) > 1000 or any(not isinstance(v, TemplateBinding) for v in bindings):
            raise ValueError("Invalid template field bindings")
        ids = [node_id for b in bindings for node_id in b.node_ids]
        if len({b.region for b in bindings}) != len(bindings) or len(set(ids)) != len(ids):
            raise ValueError("Template fields cannot share regions or source nodes")
        object.__setattr__(self, "template_bindings", bindings)
        if isinstance(self.template, dict):
            object.__setattr__(self, "template", template_from_record(self.template))
        if self.template is not None and not isinstance(self.template, (PageTemplate, FlowTemplate)):
            raise ValueError("Invalid page template")
        if isinstance(self.template, FlowTemplate):
            if bindings:
                raise ValueError("Template v3 uses named fields, not legacy node bindings; migrate explicitly")
            if self.schema_version == "inkstruct_flow_style_v1":
                object.__setattr__(self, "schema_version", "inkstruct_flow_style_v2")
        if isinstance(self.code, dict):
            object.__setattr__(self, "code", CodeStyle(**self.code))
        if not isinstance(self.code, CodeStyle):
            raise ValueError("Invalid code style")  # noqa: TRY004 - serialized configuration
        if isinstance(self.math, dict):
            record = dict(self.math)
            # Serialized records predating an explicit source used geometric bars.
            record.setdefault("fraction_source", "geometric")
            # Old projects used the ordinary script ratio for operator limits.
            record.setdefault("limits_scale", record.get("script_scale", 0.7))
            object.__setattr__(self, "math", MathStyle(**record))
        if not isinstance(self.math, MathStyle):
            raise ValueError("Invalid math style")  # noqa: TRY004 - serialized configuration
        if isinstance(self.table, dict):
            object.__setattr__(self, "table", TableStyle(**self.table))
        if not isinstance(self.table, TableStyle):
            raise ValueError("Invalid default table style")  # noqa: TRY004 - serialized configuration
        overrides = tuple(
            (key, TableStyle(**value) if isinstance(value, dict) else value)
            for key, value in self.table_overrides
        )
        if (
            len(overrides) > 1000
            or len({key for key, _ in overrides}) != len(overrides)
            or any(
                not isinstance(key, str) or not key or not isinstance(value, TableStyle)
                for key, value in overrides
            )
        ):
            raise ValueError("Invalid table style overrides")
        object.__setattr__(self, "table_overrides", overrides)
        values = (
            self.paragraph_gap_mm,
            self.heading_gap_mm,
            self.first_line_indent_mm,
            self.list_indent_mm,
            self.quote_indent_mm,
        )
        if any(not math.isfinite(v) or not 0 <= v <= 100 for v in values):
            raise ValueError("Flow distances must be within 0–100 mm")
        if min(self.list_indent_mm, self.quote_indent_mm) <= 0:
            raise ValueError("List and quote indentation must be positive")
        object.__setattr__(self, "heading_scales", tuple(self.heading_scales))
        if len(self.heading_scales) != 6 or any(
            not math.isfinite(v) or not 0.5 <= v <= 4 for v in self.heading_scales
        ):
            raise ValueError("Six heading scales within 0.5–4 are required")

    def table_for(self, node_id):
        return dict(self.table_overrides).get(node_id, self.table)

    @property
    def named_fields(self):
        return isinstance(self.template, FlowTemplate)

    def image_for(self, node_id):
        return dict(self.image_overrides).get(node_id, self.image)
