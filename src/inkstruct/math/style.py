"""Independent mathematical dimensions; raw captured glyphs stay immutable."""

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MathStyle:
    em_mm: float = 6.0
    axis_em: float = 0.25
    binary_gap_em: float = 0.18
    relation_gap_em: float = 0.28
    operator_gap_em: float = 0.12
    script_scale: float = 0.7
    limits_scale: float = 0.7
    fraction_scale: float = 0.8
    script_clearance_em: float = 0.12  # Legacy serialized field; automatic placement ignores it.
    superscript_raise_em: float = 0.55
    subscript_drop_em: float = 0.3
    fraction_clearance_em: float = 0.12
    radical_clearance_em: float = 0.12
    limits_clearance_em: float = 0.12
    large_operator_scale: float = 1.0
    small_matrix_scale: float = 0.7
    accent_clearance_em: float = 0.12
    accent_height_em: float = 0.18
    array_rule_clearance_em: float = 0.12
    tag_scale: float = 1.0
    tag_gap_em: float = 1.0
    alignment_row_gap_em: float = 0.5
    alignment_pair_gap_em: float = 1.5
    matrix_row_gap_em: float = 0.3
    matrix_col_gap_em: float = 0.75
    delimiter_clearance_em: float = 0.12
    delimiter_width_em: float = 0.4
    fraction_source: str = "sample"
    radical_source: str = "geometric"
    delimiter_source: str = "geometric"
    min_em_stroke_ratio: float = 6.0
    display_align: str = "center"
    metrics_profile: str = "capture-guides-v1-unreviewed"
    schema_version: str = "inkstruct_math_style_v1"
    spacing_policy: str = "capture"

    @classmethod
    def handwriting(cls, **overrides):
        """Application defaults; legacy construction and saved v1 styles stay exact."""
        values = {
            "spacing_policy": "handwriting", "schema_version": "inkstruct_math_style_v2",
            "binary_gap_em": .08, "relation_gap_em": .12, "operator_gap_em": .06,
            "fraction_clearance_em": .06, "radical_clearance_em": .06,
            "delimiter_clearance_em": .06, "delimiter_width_em": .3,
            "radical_source": "sample", "delimiter_source": "sample",
        }
        values.update(overrides)
        return cls(**values)

    def __post_init__(self):
        if self.schema_version not in {"inkstruct_math_style_v1", "inkstruct_math_style_v2"}:
            raise ValueError("Unsupported math style version")
        if self.spacing_policy not in {"capture", "handwriting"}:
            raise ValueError("Unknown math spacing policy")
        if self.spacing_policy == "handwriting":
            object.__setattr__(self, "schema_version", "inkstruct_math_style_v2")
        if any(
            value not in {"geometric", "sample"}
            for value in (
                self.fraction_source,
                self.radical_source,
                self.delimiter_source,
            )
        ):
            raise ValueError("Unknown math construction source")
        if not math.isfinite(self.em_mm) or not 0 < self.em_mm <= 2000:
            raise ValueError("Math em must be finite and positive")
        if any(
            not math.isfinite(v) or not 0 <= v <= 2
            for v in (self.axis_em, self.binary_gap_em, self.relation_gap_em, self.operator_gap_em)
        ):
            raise ValueError("Math axis and spacing must be within 0–2 em")
        dimensions = (
            self.script_clearance_em,
            self.superscript_raise_em,
            self.subscript_drop_em,
            self.fraction_clearance_em,
            self.radical_clearance_em,
            self.limits_clearance_em,
            self.accent_clearance_em,
            self.accent_height_em,
            self.array_rule_clearance_em,
            self.tag_gap_em,
            self.alignment_row_gap_em,
            self.alignment_pair_gap_em,
            self.matrix_row_gap_em,
            self.matrix_col_gap_em,
            self.delimiter_clearance_em,
            self.delimiter_width_em,
        )
        if any(not math.isfinite(v) or not 0 <= v <= 2 for v in dimensions):
            raise ValueError("Math structure dimensions must be within 0–2 em")
        if (
            not math.isfinite(self.large_operator_scale)
            or not 0.5 <= self.large_operator_scale <= 3
        ):
            raise ValueError("Large operator scale must be within 0.5–3")
        if self.display_align not in {"center", "left"}:
            raise ValueError("Unknown display math alignment")
        if any(
            not math.isfinite(v) or not 0.5 <= v <= 1
            for v in (
                self.script_scale,
                self.limits_scale,
                self.fraction_scale,
                self.tag_scale,
                self.small_matrix_scale,
            )
        ):
            raise ValueError("Math script and fraction scales must be within 0.5–1")
        if not math.isfinite(self.min_em_stroke_ratio) or self.min_em_stroke_ratio < 6:
            raise ValueError("Math em must allow at least six pen widths")
        if not isinstance(self.metrics_profile, str) or not self.metrics_profile:
            raise ValueError("Math metric provenance is required")


def math_style_record(style):
    record = asdict(style)
    if style.schema_version == "inkstruct_math_style_v1":
        record.pop("spacing_policy")
    return record
