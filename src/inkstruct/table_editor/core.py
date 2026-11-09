from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser

from ..plotter.schema import PathPoints, PlotPage, PlotStroke, Point  # noqa: F401
from ..plotter.svg import page_svg

NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")


@dataclass
class Cell:
    text: str = ""
    rowspan: int = 1
    colspan: int = 1
    align: str = "center"
    row: int = 0
    column: int = 0


@dataclass
class Table:
    rows: list[list[Cell]] = field(default_factory=list)
    columns: int = 0


class TableParser(HTMLParser):
    """Deliberately bounded HTML subset. No HTML is executed or fetched."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.table = Table()
        self.stack = []
        self.cell = None
        self.tables = 0

    def handle_starttag(self, tag, attrs):
        if tag not in {"table", "thead", "tbody", "tfoot", "tr", "td", "th"}:
            raise ValueError(f"第一版不支持 <{tag}>，请只输入 table/tr/td/th 和行分组")
        if tag == "table":
            if self.stack or self.tables:
                raise ValueError("每次仅支持一个表格，不支持嵌套表格")
            self.tables += 1
        elif tag in {"thead", "tbody", "tfoot"}:
            if not self.stack or self.stack[-1] != "table":
                raise ValueError("行分组必须位于 table 内")
        elif tag == "tr":
            if not self.stack or self.stack[-1] not in {"table", "thead", "tbody", "tfoot"}:
                raise ValueError("tr 必须位于表格或行分组内；请显式闭合标签")
            if len(self.table.rows) >= 100:
                raise ValueError("第一版最多支持 100 行")
            self.table.rows.append([])
        elif tag in {"td", "th"}:
            if not self.stack or self.stack[-1] != "tr":
                raise ValueError("单元格必须位于 tr 内；请显式闭合标签")
            self.cell = Cell()
        for key, value in attrs:
            if key in {"id", "class"}:
                if key == "class":
                    raise ValueError("不支持 CSS 类；请使用排版面板设置尺寸")
                continue
            if tag == "table" and (
                (key == "border" and value == "1") or (key == "cellspacing" and value == "0")
            ):
                continue
            if tag in {"td", "th"}:
                if key in {"rowspan", "colspan"}:
                    if (
                        not value
                        or not value.isascii()
                        or not value.isdecimal()
                        or not 1 <= int(value) <= 100
                    ):
                        raise ValueError(f"{key} 必须为 1—100 的整数")
                    setattr(self.cell, key, int(value))
                    continue
                if key == "align" and value in {"left", "center", "right"}:
                    self.cell.align = value
                    continue
                if key == "style":
                    declarations = [v.strip() for v in (value or "").split(";") if v.strip()]
                    for declaration in declarations:
                        pair = [v.strip().lower() for v in declaration.split(":", 1)]
                        if (
                            len(pair) != 2
                            or pair[0] != "text-align"
                            or pair[1] not in {"left", "center", "right"}
                        ):
                            raise ValueError(
                                "单元格 style 目前仅支持 text-align: left/center/right"
                            )
                        self.cell.align = pair[1]
                    continue
            if (
                tag == "table"
                and key == "style"
                and (value or "").replace(" ", "").rstrip(";").lower() == "border-collapse:collapse"
            ):
                continue
            raise ValueError(f"不支持 <{tag}> 的 {key} 属性；尺寸、框线请在排版面板设置")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            raise ValueError(f"标签闭合不匹配：{tag}；请显式闭合所有标签")
        if tag in {"td", "th"}:
            self.cell.text = self.cell.text.strip()
            if self.cell.text and not NUMBER.fullmatch(self.cell.text):
                raise ValueError(f"单元格 {self.cell.text!r} 仅支持一组数字及一个小数点")
            self.table.rows[-1].append(self.cell)
            if len(self.table.rows[-1]) > 50:
                raise ValueError("第一版最多支持 50 列")
            self.cell = None
        self.stack.pop()

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.text += data
            if len(self.cell.text) > 256:
                raise ValueError("单元格内容过长")
        elif data.strip():
            raise ValueError("表格之外不能包含文字")

    def handle_decl(self, decl):
        raise ValueError("请粘贴 HTML 表格片段，不包含文档声明")

    def handle_pi(self, data):
        raise ValueError("不支持处理指令")


def parse_table(source: str) -> Table:
    if len(source) > 200_000:
        raise ValueError("HTML 超过 200,000 字符限制")
    p = TableParser()
    p.feed(source)
    p.close()
    if p.stack or p.tables != 1 or not p.table.rows:
        raise ValueError("需要完整闭合且至少一行的 table")
    occupied = {}
    for r, row in enumerate(p.table.rows):
        col = 0
        for cell in row:
            while (r, col) in occupied:
                col += 1
            if col + cell.colspan > 50 or r + cell.rowspan > len(p.table.rows):
                raise ValueError("合并单元格超出行数或 50 列限制")
            cell.row, cell.column = r, col
            for rr in range(r, r + cell.rowspan):
                for cc in range(col, col + cell.colspan):
                    if (rr, cc) in occupied:
                        raise ValueError("合并单元格发生重叠")
                    occupied[rr, cc] = cell
            col += cell.colspan
    if not occupied:
        raise ValueError("表格不能为空")
    p.table.columns = max(c for _, c in occupied) + 1
    if len(occupied) != len(p.table.rows) * p.table.columns:
        raise ValueError("各行列数不一致；请用空 td 补齐，或正确设置 rowspan/colspan")
    return p.table


# Centerline specimens, normalized to cap-height 1. No font outlines or curves.
DIGITS = {
    "0": (
        (
            (0.3, 0),
            (0.08, 0.08),
            (0, 0.3),
            (0, 0.7),
            (0.08, 0.92),
            (0.3, 1),
            (0.52, 0.92),
            (0.6, 0.7),
            (0.6, 0.3),
            (0.52, 0.08),
            (0.3, 0),
        ),
    ),
    "1": (((0.05, 0.22), (0.3, 0), (0.3, 1)), ((0.05, 1), (0.55, 1))),
    "2": (((0, 0.18), (0.12, 0.02), (0.4, 0), (0.6, 0.15), (0.58, 0.35), (0, 1), (0.6, 1)),),
    "3": (
        (
            (0, 0.08),
            (0.35, 0),
            (0.6, 0.18),
            (0.45, 0.44),
            (0.23, 0.48),
            (0.47, 0.53),
            (0.6, 0.75),
            (0.45, 0.98),
            (0.12, 1),
            (0, 0.9),
        ),
    ),
    "4": (((0.45, 1), (0.45, 0), (0, 0.68), (0.65, 0.68)),),
    "5": (
        (
            (0.58, 0),
            (0.06, 0),
            (0.02, 0.46),
            (0.35, 0.43),
            (0.58, 0.58),
            (0.6, 0.8),
            (0.42, 1),
            (0.12, 1),
            (0, 0.9),
        ),
    ),
    "6": (
        (
            (0.55, 0.05),
            (0.3, 0),
            (0.07, 0.23),
            (0, 0.6),
            (0.04, 0.87),
            (0.23, 1),
            (0.46, 0.95),
            (0.6, 0.76),
            (0.52, 0.54),
            (0.28, 0.48),
            (0.03, 0.62),
        ),
    ),
    "7": (((0, 0), (0.6, 0), (0.21, 1)),),
    "8": (
        (
            (0.3, 0),
            (0.07, 0.08),
            (0.02, 0.3),
            (0.3, 0.5),
            (0.58, 0.72),
            (0.53, 0.94),
            (0.3, 1),
            (0.06, 0.93),
            (0, 0.72),
            (0.3, 0.5),
            (0.58, 0.3),
            (0.53, 0.07),
            (0.3, 0),
        ),
    ),
    "9": (
        (
            (0.57, 0.42),
            (0.33, 0.51),
            (0.08, 0.44),
            (0, 0.24),
            (0.12, 0.03),
            (0.36, 0),
            (0.56, 0.14),
            (0.6, 0.44),
            (0.5, 0.8),
            (0.27, 1),
            (0.05, 0.95),
        ),
    ),
    ".": (((0.03, 0.985), (0.065, 0.985)),),
}


@dataclass(frozen=True)
class NumericGlyph:
    # Coordinates are in cap-height units, positive y down; baseline = 1.
    # A future specimen adapter converts captured em metrics into this contract.
    strokes: tuple[PathPoints, ...]
    advance: float


BUILTIN_GLYPHS = {
    c: NumericGlyph(strokes, 0.2 if c == "." else 0.75) for c, strokes in DIGITS.items()
}


def number_geometry(text: str, glyphs: Mapping[str, NumericGlyph]):
    paths, cursor = [], 0.0
    for c in text:
        if c not in glyphs:
            raise ValueError(f"数字字形缺失：{c}")
        glyph = glyphs[c]
        if not math.isfinite(glyph.advance) or glyph.advance <= 0 or not glyph.strokes:
            raise ValueError(f"字形 {c} 的字宽或笔画无效")
        if sum(len(stroke) for stroke in glyph.strokes) > 4096:
            raise ValueError(f"字形 {c} 的点数超限")
        for stroke in glyph.strokes:
            if len(stroke) < 2 or not all(math.isfinite(x) and math.isfinite(y) for x, y in stroke):
                raise ValueError(f"字形 {c} 必须使用有限坐标的折线")
            if any(abs(x) > 10 or y < 0 or y > 1 for x, y in stroke):
                raise ValueError(f"字形 {c} 超出数字字高坐标范围")
            if len(set(stroke)) < 2:
                raise ValueError("小数点也必须是有长度的短线，不能使用零长路径")
            paths.append(tuple((cursor + x, y) for x, y in stroke))
        cursor += glyph.advance
    xs = [x for stroke in paths for x, _ in stroke]
    return paths, min(xs), max(xs)


@dataclass(frozen=True)
class Settings:
    page_width: float = 210
    page_height: float = 297
    margin: float = 15
    table_width: float = 160
    row_height: float = 8
    digit_height: float = 3.8
    padding: float = 0.3
    stroke_width: float = 0.3
    column_weights: tuple[float, ...] = ()


@dataclass(frozen=True)
class Drawing:
    settings: Settings
    borders: tuple[PathPoints, ...]
    numbers: tuple[PathPoints, ...]
    rows: int
    columns: int


def layout_table(
    table: Table,
    settings: Settings | None = None,
    *,
    glyphs: Mapping[str, NumericGlyph] | None = None,
) -> Drawing:
    s = settings or Settings()
    glyphs = BUILTIN_GLYPHS if glyphs is None else glyphs
    for name in (
        "page_width",
        "page_height",
        "margin",
        "table_width",
        "row_height",
        "digit_height",
        "padding",
        "stroke_width",
    ):
        val = getattr(s, name)
        if not math.isfinite(val) or val < 0 or (name not in {"margin", "padding"} and val < 0.001):
            raise ValueError("尺寸必须为有限正数，边距和留白可为零")
    if max(s.page_width, s.page_height) > 2000:
        raise ValueError("页面边长不能超过 2000 mm")
    if s.margin < s.stroke_width / 2:
        raise ValueError("页边距需至少为线宽的一半，避免墨迹越界")
    if s.table_width > s.page_width - 2 * s.margin + 1e-9:
        raise ValueError("表格宽度超出纸张可用宽度")
    if len(table.rows) * s.row_height > s.page_height - 2 * s.margin + 1e-9:
        raise ValueError("表格超出单页高度；请减少行高或行数，第一版不自动分页")
    weights = s.column_weights or (1.0,) * table.columns
    if len(weights) != table.columns or any(not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError(f"列宽比例需要 {table.columns} 个有限正数")
    total = sum(weights)
    if not math.isfinite(total):
        raise ValueError("列宽比例之和无效")
    xs = [s.margin]
    for w in weights:
        xs.append(xs[-1] + s.table_width * w / total)
    ys = [s.margin + r * s.row_height for r in range(len(table.rows) + 1)]
    edges = {}
    numbers = []
    for row in table.rows:
        for cell in row:
            left, right = xs[cell.column], xs[cell.column + cell.colspan]
            top, bottom = ys[cell.row], ys[cell.row + cell.rowspan]
            for key, start, end in [
                (("h", top), left, right),
                (("h", bottom), left, right),
                (("v", left), top, bottom),
                (("v", right), top, bottom),
            ]:
                edges.setdefault(key, []).append((start, end))
            if not cell.text:
                continue
            paths, min_x, max_x = number_geometry(cell.text, glyphs)
            text_width = (max_x - min_x) * s.digit_height
            clearance = s.padding + s.stroke_width
            if (
                text_width > right - left - 2 * clearance
                or s.digit_height > bottom - top - 2 * clearance
            ):
                raise ValueError(
                    f"第 {cell.row + 1} 行第 {cell.column + 1} 列数字放不下；请调整列宽、字号或留白"
                )
            x = {
                "left": left + clearance,
                "center": (left + right - text_width) / 2,
                "right": right - clearance - text_width,
            }[cell.align]
            y = (top + bottom - s.digit_height) / 2
            for stroke in paths:
                numbers.append(
                    tuple(
                        (x + (px - min_x) * s.digit_height, y + py * s.digit_height)
                        for px, py in stroke
                    )
                )
    borders = []
    for (axis, pos), intervals in sorted(edges.items()):
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1] + 1e-9:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        for start, end in merged:
            borders.append(
                ((start, pos), (end, pos)) if axis == "h" else ((pos, start), (pos, end))
            )
    return Drawing(s, tuple(borders), tuple(numbers), len(table.rows), table.columns)


def drawing_svg(drawing: Drawing, *, paths: tuple[PathPoints, ...] | None = None) -> str:
    s = drawing.settings
    strokes = tuple(
        PlotStroke(f"table:stroke:{i}", points, s.stroke_width)
        for i, points in enumerate(
            (*drawing.borders, *drawing.numbers) if paths is None else paths
        )
    )
    return page_svg(PlotPage(0, s.page_width, s.page_height, strokes))


def compile_html(
    source: str,
    settings: Settings | None = None,
    *,
    glyphs: Mapping[str, NumericGlyph] | None = None,
) -> tuple[Drawing, str]:
    drawing = layout_table(parse_table(source), settings, glyphs=glyphs)
    return drawing, drawing_svg(drawing)
