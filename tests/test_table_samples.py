import copy
import json
import zipfile

import pytest

from inkstruct.table_editor.app import EXAMPLE, create_window, main
from inkstruct.table_editor.core import compile_html
from inkstruct.table_editor.samples import load_sample_zip


def make_archive(path, *, change=None):
    records = []
    for c in "0123456789":
        for i in range(5):
            records.append(
                {
                    "schema_version": "inkstruct_symbol_sample_v1",
                    "writer_id": "synthetic",
                    "sample_id": f"{c}-{i}",
                    "character": c,
                    "capture": {"coordinate_space": "logical_px"},
                    "guides": {
                        "em_px": 100,
                        "baseline_y_px": 80,
                        "origin_x_px": 10,
                        "cap_height_em": 0.7,
                    },
                    "strokes": [
                        {
                            "points": [
                                {"x": 20, "y": 12 + i},
                                {"x": 20, "y": 12 + i},
                                {"x": 45 + i, "y": 82},
                            ]
                        }
                    ],
                }
            )
    if change:
        change(records)
    with zipfile.ZipFile(path, "w") as z:
        for i, record in enumerate(records):
            z.writestr(f"synthetic/{i}.json", json.dumps(record))
    return records


def test_bank_isotropic_transform_preserves_points_and_relative_sizes(tmp_path):
    source = tmp_path / "samples.zip"
    records = make_archive(source)
    original = source.read_bytes()
    bank = load_sample_zip(source)
    assert source.read_bytes() == original
    assert bank.writer_id == "synthetic" and len(bank.samples["0"]) == 5
    assert bank.top_em == -0.7 and bank.bottom_em == 0.02
    for sample, raw in zip(bank.samples["0"], records[:5]):
        assert len(sample.glyph.strokes) == len(raw["strokes"])
        # Every displacement uses the same x/y scale. Repeated points remain.
        actual = sample.glyph.strokes[0]
        points = raw["strokes"][0]["points"]
        assert actual[0] == actual[1]
        for p, a in zip(points, actual):
            assert a[0] - actual[0][0] == pytest.approx((p["x"] - points[0]["x"]) / 72)
            assert a[1] - actual[0][1] == pytest.approx((p["y"] - points[0]["y"]) / 72)


def test_selection_repeatable_per_occurrence_and_shared_across_routing(tmp_path):
    source = tmp_path / "samples.zip"
    make_archive(source)
    bank = load_sample_zip(source)
    text = "<table><tr><td>" + "0" * 30 + ".125</td></tr></table>"
    a, b, c = bank.select(42), bank.select(42), bank.select(43)
    _, first = compile_html(text, glyphs=a)
    _, second = compile_html(text, glyphs=b)
    _, third = compile_html(text, glyphs=c)
    assert first == second and a.trace == b.trace
    assert first != third
    assert len(a.trace) == 34
    assert len({p["sample_id"] for p in a.trace[:30]}) == 5
    assert a.trace[30]["sample_id"] == "builtin:decimal-point"


@pytest.mark.parametrize(
    "failure",
    ["missing", "mixed_writer", "duplicate", "nan", "zero_length", "schema", "coordinates"],
)
def test_invalid_archive_rejected(tmp_path, failure):
    def mutate(records):
        if failure == "missing":
            records[:] = [r for r in records if r["character"] != "9"]
        elif failure == "mixed_writer":
            records[0]["writer_id"] = "other"
        elif failure == "duplicate":
            records.append(copy.deepcopy(records[0]))
        elif failure == "nan":
            records[0]["strokes"][0]["points"][0]["x"] = float("nan")
        elif failure == "zero_length":
            records[0]["strokes"][0]["points"] = [{"x": 1, "y": 1}] * 3
        elif failure == "schema":
            records[0]["schema_version"] = "wrong"
        else:
            records[0]["capture"]["coordinate_space"] = "device_px"

    source = tmp_path / "bad.zip"
    make_archive(source, change=mutate)
    with pytest.raises(ValueError):
        load_sample_zip(source)


def test_cli_loads_samples(tmp_path, capsys):
    source, html, svg = (tmp_path / n for n in ("samples.zip", "table.html", "table.svg"))
    make_archive(source)
    html.write_text(EXAMPLE)
    assert (
        main(
            [
                "--samples",
                str(source),
                "--sample-seed",
                "42",
                "--input",
                str(html),
                "--output",
                str(svg),
            ]
        )
        == 0
    )
    assert "小数点使用内置短线" in capsys.readouterr().out
    assert svg.read_text() == compile_html(EXAMPLE, glyphs=load_sample_zip(source).select(42))[1]


def test_ui_import_seed_project_roundtrip_and_changed_source_guard(tmp_path, monkeypatch):
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    source, project = tmp_path / "samples.zip", tmp_path / "project.inktable"
    make_archive(source)
    window = create_window()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a: (str(source), ""))
    window.open_samples()
    window.sample_seed.setValue(42)
    window.refresh()
    initial_svg, trace = window.svg, window.glyph_trace.copy()
    assert "synthetic" in window.sample_label.text() and trace
    window.refresh()
    assert window.svg == initial_svg and window.glyph_trace == trace
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(project), ""))
    window.save_project()
    restored = create_window()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a: (str(project), ""))
    restored.open_project()
    assert restored.svg == initial_svg and restored.glyph_trace == trace
    assert restored.sample_seed.value() == 42
    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: warnings.append(a[-1]))
    make_archive(source, change=lambda records: records[0].update(sample_id="changed"))
    restored.open_project()
    assert warnings and "样本压缩包已变化" in warnings[-1]
    assert restored.svg == initial_svg
    restored.set_sample_bank(None)
    restored.refresh()
    assert restored.svg == compile_html(EXAMPLE)[1] and restored.glyph_trace == []
    restored.project_dirty = False
    restored.close()
    window.close()
    app.processEvents()


def test_recorded_decimal_uses_shared_scale_and_reproducible_variants(tmp_path):
    def add_dots(records):
        for i in range(5):
            dot = copy.deepcopy(records[0])
            dot.update(character=".", sample_id=f"dot-{i}")
            dot["strokes"][0]["points"] = [{"x": 20, "y": 76}, {"x": 21 + i / 2, "y": 78}]
            records.append(dot)

    path = tmp_path / "decimal.zip"
    make_archive(path, change=add_dots)
    bank = load_sample_zip(path)
    assert "手写小数点 5 份" in bank.summary
    for sample in bank.samples["."]:
        points = sample.glyph.strokes[0]
        assert points[-1][1] - points[0][1] == pytest.approx(2 / 72)
        assert 0.9 < points[0][1] < points[-1][1] < 1
        assert sample.glyph.advance < 0.3
    source = "<table><tr><td>1.01</td><td>2.32</td></tr></table>"
    selection = bank.select(42)
    _, svg = compile_html(source, glyphs=selection)
    dots = [p for p in selection.trace if p["character"] == "."]
    assert len(dots) == 2 and all(p["sample_id"].startswith("dot-") for p in dots)
    assert svg == compile_html(source, glyphs=bank.select(42))[1]
