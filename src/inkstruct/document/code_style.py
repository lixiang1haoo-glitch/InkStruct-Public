"""Physical code grid: no wrapping, glyph squeezing or syntax highlighting ink."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeStyle:
    em_mm: float = 4
    advance_mm: float = 5
    line_height_mm: float = 6
    tab_columns: int = 4
    wrap_lines: bool = False
    schema_version: str = "inkstruct_code_style_v1"

    def __post_init__(self):
        if any(
            not math.isfinite(v) or not 0 < v <= 2000
            for v in (self.em_mm, self.advance_mm, self.line_height_mm)
        ):
            raise ValueError("Code dimensions must be finite and positive")
        if type(self.tab_columns) is not int or not 1 <= self.tab_columns <= 16:
            raise ValueError("Code tab stops must be within 1–16 columns")
        if type(self.wrap_lines) is not bool:
            raise ValueError("Code wrap setting must be boolean")
        if self.schema_version != "inkstruct_code_style_v1":
            raise ValueError("Unsupported code style version")
