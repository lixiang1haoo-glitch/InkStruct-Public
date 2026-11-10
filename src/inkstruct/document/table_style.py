"""Independent, serializable table dimensions; all lengths are millimetres."""

import json
import math
from dataclasses import dataclass, replace

from .schema import digest


@dataclass(frozen=True)
class TableStyle:
    width_mm: float = 160
    min_row_height_mm: float = 8
    digit_height_mm: float = 3.8
    padding_top_mm: float = 0.3
    padding_right_mm: float = 0.3
    padding_bottom_mm: float = 0.3
    padding_left_mm: float = 0.3
    text_em_mm: float = 5
    line_height_mm: float = 6
    stroke_width_mm: float = 0.3
    numeric_height_em: float = 0.7
    numeric_profile: str = "builtin-numeric-cap-v1"
    numeric_spacing: str = "compact-advance"
    width_mode: str = "content"
    columns: tuple[float, ...] = ()
    column_alignments: tuple[str, ...] = ()
    fixed_row_height: bool = False
    repeat_header: bool = True
    schema_version: str = "inkstruct_table_style_v1"
    total_width_mode: str = "fixed"

    def __post_init__(self):
        if self.schema_version != "inkstruct_table_style_v1":
            raise ValueError("Unsupported table style version")
        dimensions = [
            self.width_mm,
            self.min_row_height_mm,
            self.digit_height_mm,
            self.text_em_mm,
            self.line_height_mm,
            self.stroke_width_mm,
            self.numeric_height_em,
        ]
        padding = [
            self.padding_top_mm,
            self.padding_right_mm,
            self.padding_bottom_mm,
            self.padding_left_mm,
        ]
        if any(not math.isfinite(v) or not 0 < v <= 2000 for v in dimensions) or any(
            not math.isfinite(v) or not 0 <= v <= 100 for v in padding
        ):
            raise ValueError("Table dimensions must be finite positive values; padding may be zero")
        if self.width_mode not in {"content", "equal", "ratio", "fixed"}:
            raise ValueError("Unknown table column width mode")
        if self.total_width_mode not in {"fixed", "content"}:
            raise ValueError("Unknown table total width mode")
        if self.total_width_mode == "content" and self.width_mode == "fixed":
            raise ValueError("固定列宽需要手动指定表格总宽")
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "column_alignments", tuple(self.column_alignments))
        if len(self.columns) > 50 or any(not math.isfinite(v) or v <= 0 for v in self.columns):
            raise ValueError("Column sizes must be finite positive values")
        if any(
            v not in {"auto", "left", "right", "center", "decimal"} for v in self.column_alignments
        ):
            raise ValueError("Invalid column alignment")
        if self.width_mode in {"fixed", "ratio"} and not self.columns:
            raise ValueError("Fixed/ratio column mode requires column sizes")
        if type(self.fixed_row_height) is not bool or type(self.repeat_header) is not bool:
            raise ValueError("Table switches must be booleans")
        if not isinstance(self.numeric_profile, str) or not self.numeric_profile:
            raise ValueError("A numeric profile provenance is required")
        if self.numeric_spacing not in {"compact-advance", "legacy-ink"}:
            raise ValueError("Unsupported numeric spacing profile")


def omit_default_total_width_mode(flow_record):
    for table in (flow_record["table"], *(style for _, style in flow_record["table_overrides"])):
        if table["total_width_mode"] == "fixed":
            table.pop("total_width_mode")


def calibrate_tables(flow, symbols):
    """Freeze the legacy numeric-bank vertical frame on explicit sample import.

    Only digits and the decimal point participate. A later integral/descender
    cannot resize them, and reopening a project uses the persisted calibration.
    """
    glyphs = [g for c, pool in symbols.pools.items() if c in "0123456789." for g in pool]
    if not glyphs:
        return flow
    caps = [float(json.loads(g.original_json)["guides"].get("cap_height_em", 0.7)) for g in glyphs]
    if any(not math.isfinite(c) or c <= 0 for c in caps):
        raise ValueError("Invalid numeric capture cap-height guide")
    top = min([-c for c in caps] + [g.bounds[1] - g.metrics.baseline for g in glyphs])
    bottom = max([0] + [g.bounds[3] - g.metrics.baseline for g in glyphs])
    profile = "numeric_profile_v1:" + digest(sorted(g.asset_id for g in glyphs))

    def calibrated(style):
        return replace(style, numeric_height_em=bottom - top, numeric_profile=profile)

    return replace(
        flow,
        table=calibrated(flow.table),
        table_overrides=tuple((key, calibrated(style)) for key, style in flow.table_overrides),
    )
