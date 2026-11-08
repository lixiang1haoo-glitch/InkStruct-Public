import re
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from inkstruct.table_editor.app import EXAMPLE, atomic_save
from inkstruct.table_editor.core import (
    BUILTIN_GLYPHS,
    NumericGlyph,
    Settings,
    compile_html,
    parse_table,
)


def test_plotter_svg_has_only_paths_and_absolute_ml_and_physical_units():
    drawing, svg = compile_html("<table><tr><td>0123456789.50</td></tr></table>")
    root = ET.fromstring(svg)
    assert root.attrib["width"] == "210.000000mm"
    assert root.attrib["viewBox"] == "0 0 210.000000 297.000000"
    assert len(root) == len(drawing.borders) + len(drawing.numbers)
    for child in root:
        assert child.tag == "{http://www.w3.org/2000/svg}path"
        assert child.attrib["fill"] == "none"
        assert set(re.findall(r"[A-Za-z]", child.attrib["d"])) <= {"M", "L"}
        assert len(re.findall("M", child.attrib["d"])) == 1
        assert "L" in child.attrib["d"]
        assert "transform" not in child.attrib
    assert len(drawing.borders) == 4
    # Decimal point is a short non-zero pen movement, not a circle or zero-length dot.
    dot = drawing.numbers[-3]
    assert len(dot) == 2 and dot[0] != dot[1]


def test_shared_borders_drawn_once_and_span_interiors_absent():
    d, _ = compile_html("<table><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>")
    assert len(d.borders) == 6
    merged, _ = compile_html(EXAMPLE, Settings(table_width=180, row_height=14))
    # First column spans rows 1/2; row-2 boundary starts at column 2.
    middle = [s for s in merged.borders if s[0][1] == s[1][1] == 29]
    assert middle == [((75.0, 29.0), (195.0, 29.0))]
    # Last two columns merge in row 1; their divider starts only at row 2.
    vertical = [s for s in merged.borders if s[0][0] == s[1][0] == 135]
    assert vertical == [((135.0, 29.0), (135.0, 57.0))]


def test_fractional_rows_do_not_duplicate_shared_edges():
    source = "<table>" + "<tr><td></td><td></td></tr>" * 10 + "</table>"
    d, _ = compile_html(source, Settings(row_height=1.1))
    assert len(d.borders) == 14


@pytest.mark.parametrize(
    "source",
    [
        "<table><tr><td>汉字</td></tr></table>",
        "<table><tr><td>1.2.3</td></tr></table>",
        "<table><tr><td>-1</td></tr></table>",
        "<table><tr><td>1e3</td></tr></table>",
        "<table><tr><td><script>1</script></td></tr></table>",
        '<table><tr><td rowspan="2">1</td></tr></table>',
        "<table><tr><td>1</td><td>2</td></tr><tr><td>3</td></tr></table>",
        "<table><tr><td>1</tr></table>",
        '<table><tr><td style="display:none">1</td></tr></table>',
        '<table><tr><td rowspan="0">1</td></tr></table>',
        '<table><tr><td></td><td rowspan="2"></td></tr><tr><td colspan="2"></td></tr></table>',
    ],
)
def test_invalid_or_unsupported_content_is_blocked(source):
    with pytest.raises(ValueError):
        compile_html(source)


def test_entities_blank_cells_and_alignment():
    table = parse_table("<table><tbody><tr><td>&#49;.25</td><td> </td></tr></tbody></table>")
    assert table.rows[0][0].text == "1.25"
    source = '<table><tr><td align="left">12</td><td style="text-align:right">12</td></tr></table>'
    d, _ = compile_html(source)
    first = d.numbers[:3]  # 1 uses two strokes, 2 one stroke.
    second = d.numbers[3:]
    assert min(x for s in first for x, _ in s) == pytest.approx(15.6)
    assert max(x for s in second for x, _ in s) == pytest.approx(174.4)


@pytest.mark.parametrize(
    "settings",
    [
        Settings(table_width=200),
        Settings(row_height=300),
        Settings(digit_height=20),
        Settings(column_weights=(1, 2)),
        Settings(column_weights=(float("nan"),)),
        Settings(stroke_width=0),
        Settings(margin=0),
        Settings(table_width=float("inf")),
    ],
)
def test_overflow_and_invalid_dimensions_block_export(settings):
    with pytest.raises(ValueError):
        compile_html("<table><tr><td>12.50</td></tr></table>", settings)


def test_column_ratios_and_custom_glyph_contract():
    s = Settings(table_width=180, row_height=14, column_weights=(1, 2))
    d, _ = compile_html("<table><tr><td>1</td><td>2</td></tr></table>", s)
    assert ((75.0, 15.0), (75.0, 29.0)) in d.borders
    custom = dict(BUILTIN_GLYPHS)
    custom["1"] = NumericGlyph((((0.0, 0.0), (0.1, 1.0)),), 0.3)
    d, svg = compile_html("<table><tr><td>1</td></tr></table>", glyphs=custom)
    assert len(d.numbers) == 1 and "L" in svg
    custom["1"] = replace(custom["1"], strokes=(((0.0, 0.0), (0.0, 0.0)),))
    with pytest.raises(ValueError):
        compile_html("<table><tr><td>1</td></tr></table>", glyphs=custom)


def test_failed_export_preserves_previous_file(tmp_path, monkeypatch):
    p = tmp_path / "table.svg"
    p.write_text("original")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("inkstruct.table_editor.app.os.replace", fail)
    with pytest.raises(OSError):
        atomic_save(p, "new")
    assert p.read_text() == "original"
    assert list(tmp_path.iterdir()) == [p]
