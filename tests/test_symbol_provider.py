import copy
import csv
import io
import json

import pytest

from inkstruct.assets.resolver import AssetResolver, SelectedAsset, gap_capture_csv
from inkstruct.assets.symbol_provider import SymbolProfile, SymbolProvider, adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown


def specimen(char="1", sid="s1", height=10):
    return {
        "schema_version": "inkstruct_symbol_sample_v1",
        "character": char,
        "sample_id": sid,
        "writer_id": "fixture",
        "capture": {"coordinate_space": "logical_px"},
        "guides": {"em_px": 100, "origin_x_px": 10, "baseline_y_px": 80},
        "strokes": [
            {
                "points": [
                    {"x": 20, "y": height, "t_ms": 0, "pressure": 0.3},
                    {"x": 40, "y": 80, "t_ms": 50, "pressure": 0.8},
                ]
            }
        ],
    }


def asset(**kwargs):
    return adapt_symbol(json.dumps(specimen(**kwargs)).encode())


def test_symbol_profile_does_not_rescale_when_tall_symbols_are_added():
    digit = asset()
    raw = copy.deepcopy(json.loads(digit.original_json))
    original = SymbolProvider([digit])
    expanded = SymbolProvider([digit, asset(char="∫", sid="integral", height=-50)])
    assert original.pools["1"] == expanded.pools["1"]
    assert expanded.profile.key == original.profile.key
    assert json.loads(digit.original_json) == raw
    points = digit.strokes[0]
    assert points[1][0] - points[0][0] == pytest.approx(0.2)
    assert points[1][1] - points[0][1] == pytest.approx(0.7)
    assert digit.metrics.baseline == 0.88
    assert digit.machine_capability == "centerline"


def test_han_and_symbols_share_the_same_measurement_contract():
    from inkstruct.assets.glyph_provider import AssetPoint, GlyphAsset, GlyphMetrics, GlyphProvider

    han = GlyphAsset(
        "han-asset",
        "人",
        b'{"source":"fixture"}',
        ((AssetPoint(0.1, 0.1, 0, 0.5, "down"), AssetPoint(0.9, 0.9, 30, 0.6, "up")),),
        GlyphMetrics(),
        (0.1, 0.1, 0.9, 0.9),
    )
    resolver = AssetResolver(GlyphProvider({"人": han}), SymbolProvider([asset()]))
    resolved = [resolver.resolve(o) for o in parse_markdown("人1").occurrences]
    assert all(g.metrics.baseline == 0.88 and g.metrics.advance > 0 for g in resolved)
    assert all(len(g.bounds) == 4 and g.machine_capability == "centerline" for g in resolved)
    assert resolved[0].original_json == han.original_json
    assert resolved[0].strokes == (((0.1, 0.1), (0.9, 0.9)),)


def test_selection_survives_edits_undo_save_restore_and_added_samples():
    provider = SymbolProvider([asset(sid=f"s{i}", height=10 + i) for i in range(5)])
    session = SourceSession("111")
    resolver = AssetResolver(symbols=provider, seed=42)
    before = parse_markdown(session)
    chosen = [resolver.resolve(o).asset_id for o in before.occurrences]
    session.apply(0, 0, "111 ")
    after = parse_markdown(session)
    assert [resolver.resolve(o).asset_id for o in after.occurrences[-3:]] == chosen
    expanded = SymbolProvider([*provider.pools["1"], asset(sid="new", height=20)])
    selections = [SelectedAsset(**r) for r in resolver.selection_records()]
    reopened = AssetResolver(symbols=expanded, seed=999, selections=selections)
    assert [reopened.resolve(o).asset_id for o in after.occurrences[-3:]] == chosen
    session.undo()
    assert [reopened.resolve(o).asset_id for o in parse_markdown(session).occurrences] == chosen


def test_missing_selected_asset_or_changed_calibration_never_silently_reselects():
    selected = asset()
    doc = parse_markdown("1")
    resolver = AssetResolver(symbols=SymbolProvider([selected]))
    resolver.resolve(doc.occurrences[0])
    records = tuple(resolver.selections.values())
    changed = SymbolProfile(baseline=0.9)
    altered = adapt_symbol(selected.original_json, changed)
    for provider in (
        SymbolProvider([asset(sid="replacement")]),
        SymbolProvider([altered], profile=changed),
    ):
        restored = AssetResolver(symbols=provider, selections=records)
        with pytest.raises(ValueError, match="no reselection"):
            restored.resolve(doc.occurrences[0])
        assert restored.gaps(doc.occurrences)[0]["action"] == "restore-selected-resource"


def test_resource_gap_csv_is_collector_compatible_and_keeps_other_gaps_separate():
    doc = parse_markdown("A α A 缺 👩‍💻 1")
    resolver = AssetResolver(symbols=SymbolProvider([asset()]))
    gaps = resolver.gaps(doc.occurrences)
    rows = list(csv.DictReader(io.StringIO(gap_capture_csv(gaps))))
    assert {r["character"] for r in rows} == {"A", "α"}
    assert all(r["repeats"] == "5" for r in rows)
    assert next(g for g in gaps if g["character"] == "缺")["action"] == "generate-han"
    assert next(g for g in gaps if g["character"] == "👩‍💻")["action"] == "unsupported-cluster"
    assert len(next(g for g in gaps if g["character"] == "A")["source_ranges"]) == 2


def test_single_point_is_preserved_and_declares_adaptation_required():
    data = specimen()
    data["strokes"][0]["points"] = data["strokes"][0]["points"][:1]
    glyph = adapt_symbol(json.dumps(data).encode())
    assert glyph.machine_capability == "point-adaptation-required"
    assert len(glyph.strokes[0]) == 1


@pytest.mark.parametrize("field,value", [("x", float("nan")), ("pressure", 2), ("t_ms", -1)])
def test_bad_symbol_geometry_or_dynamics_rejected(field, value):
    data = specimen()
    data["strokes"][0]["points"][1][field] = value
    with pytest.raises(ValueError):
        adapt_symbol(json.dumps(data).encode())


def test_resource_cli_writes_csv_and_refuses_to_overwrite(tmp_path, capsys):
    from inkstruct.cli import main

    source, output = tmp_path / "source.md", tmp_path / "capture.csv"
    source.write_text("A α 缺", encoding='utf-8')
    argv = ["document", "resources", str(source), "--capture-csv", str(output)]
    assert main(argv) == 0
    assert len(json.loads(capsys.readouterr().out)["gaps"]) == 3
    original = output.read_bytes()
    assert main(argv) == 2
    assert output.read_bytes() == original
