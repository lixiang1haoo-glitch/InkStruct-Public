"""Persisted footnote dimensions; ratios follow the surrounding text size."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FootnoteStyle:
    reference_scale: float = 0.7
    reference_raise_em: float = 0.45
    text_scale: float = 0.7
    line_height_scale: float = 0.75
    body_gap_mm: float = 2
    note_gap_mm: float = 2
    separator_length_mm: float = 30
    page_fraction: float = 0.4
    label_indent_mm: float = 6
    schema_version: str = "inkstruct_footnote_style_v1"

    def __post_init__(self):
        ranges = {
            "reference_scale": (0.1, 1),
            "reference_raise_em": (0, 2),
            "text_scale": (0.1, 2),
            "line_height_scale": (0.1, 3),
            "body_gap_mm": (0, 100),
            "note_gap_mm": (0, 100),
            "separator_length_mm": (1, 1000),
            "page_fraction": (0.1, 0.9),
            "label_indent_mm": (1, 100),
        }
        for key, (low, high) in ranges.items():
            value = getattr(self, key)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError(f"Footnote {key} must be within {low}–{high}")
        if self.schema_version != "inkstruct_footnote_style_v1":
            raise ValueError("Unsupported footnote style version")
