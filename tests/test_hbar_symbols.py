"""Recorded hbar/dot reuse works with existing fonts and frozen documents."""

import copy
import csv
import io
import json
from itertools import pairwise

import pytest
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver, gap_capture_csv
from inkstruct.assets.symbol_provider import SymbolProvider, adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.resources import inspect_resources
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage, decode, from_embedded
from inkstruct.fonts.importer import build_font
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.parser import parse_math
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.punctuation import capture_character
from inkstruct.symbol_capture import parse_symbol_file, symbol_info


def source(char, sid=None, *, style=None, writer="fixture"):
    raw = specimen(char, sid or char)
    raw["writer_id"] = writer
    points = [(20, 10), (20, 80), (35, 45), (50, 55), (50, 80)] if char == "h" else [
        (20, 45), (40, 44), (60, 45)]
    if char in ".．":
        points = [(30, 78), (31, 79)]
    raw["strokes"][0]["points"] = [
        {"x": x, "y": y, "t_ms": i * 10, "pressure": .2 + i * .1,
         "pen_state": "end" if i == len(points) - 1 else "down"}
        for i, (x, y) in enumerate(points)]
    raw["guides"]["math_axis_em"] = .25
    if style:
        raw["variant"] = {"letter_style": style}
    return adapt_symbol(json.dumps(raw, ensure_ascii=False).encode())


def resolver(*glyphs):
    return AssetResolver(symbols=SymbolProvider(glyphs or [source("h"), source("−")]))


def test_existing_recordings_compose_hbar_without_changing_source_or_dynamics():
    h, minus = source("h"), source("−")
    before = (h.original_json, minus.original_json, h.strokes, minus.strokes)
    r = resolver(h, minus)
    made = r.pools["ℏ"][0]
    core = decode(made.original_json)
    construction = core["summary"]["symbol_construction"]
    assert core["summary"]["source_kind"] == "composed"
    assert [s["character"] for s in construction["sources"]] == ["h", "−"]
    assert [s["asset_id"] for s in construction["source_assets"]] == [h.asset_id, minus.asset_id]
    assert made.strokes[0] == h.strokes[0]
    assert from_embedded(made.original_json) == made
    assert (h.original_json, minus.original_json, h.strokes, minus.strokes) == before
    for index, original in enumerate((h, minus)):
        old = json.loads(original.original_json)["strokes"][0]["points"]
        new = core["trajectory"]["strokes"][index]["points"]
        shift = construction["component_time_shifts_ms"][index]
        assert [p["pressure"] for p in new] == [p["pressure"] for p in old]
        assert [p["pen_state"] for p in new] == [p["pen_state"] for p in old]
        assert [p["t_ms"] for p in new] == [p["t_ms"] + shift for p in old]
    bar = made.strokes[-1]
    assert max(x for x, _ in bar) - min(x for x, _ in bar) < h.bounds[2] - h.bounds[0]
    assert max(y for _, y in bar) - min(y for _, y in bar) == pytest.approx(
        minus.bounds[3] - minus.bounds[1])


def test_hbar_follows_h_style_and_ascii_minus_is_an_explicit_fallback():
    r = resolver(source("h", "upright", style="upright"),
                 source("h", "italic", style="italic"), source("-"))
    boxes = [measure_math(parse_math(code).root, r, owner=code)
             for code in (r"\hbar", r"\mathrm{\hbar}")]
    assert all(b.ready for b in boxes)
    assert [b.glyphs[0].glyph.font_core["record"]["letter_style"] for b in boxes] == ["italic", "upright"]
    assert all(g.font_core["summary"]["symbol_construction"]["sources"][1]["character"] == "-"
               for g in r.pools["ℏ"])


def test_hbar_independent_capture_wins_and_different_writers_never_mix():
    independent = source("ℏ")
    r = resolver(source("h"), source("−"), independent)
    assert r.pools["ℏ"] == (independent,)
    r = AssetResolver(embedded=[source("h"), source("−", writer="other")])
    assert "ℏ" not in r.pools


def test_hbar_source_gaps_request_h_and_minus_and_resource_scan_stays_read_only():
    document = parse_markdown(r"$\hbar$")
    for supplied, missing in (([], {"h", "−"}), ([source("h")], {"−"}), ([source("−")], {"h"})):
        r = AssetResolver(embedded=supplied)
        report = inspect_resources(document, r)
        assert {gap["character"] for gap in report["gaps"]} == missing
        rows = list(csv.DictReader(io.StringIO(gap_capture_csv(report["gaps"]))))
        assert {row["character"] for row in rows} == missing
        assert not r.selection_records()
    assert not inspect_resources(document, resolver())["gaps"]


def test_hbar_old_font_sources_persist_and_frozen_choice_never_reselects(tmp_path):
    r = resolver()
    session = SourceSession(r"$\hbar$")
    before = layout_markdown(parse_markdown(session), r)
    assert before.plotter_exportable, before.diagnostics
    plan_from_snapshot(before)
    selected = r.selection_records()
    path = tmp_path / "hbar.inkdoc"
    save_package(path, session, r, PageProfile(), StyleProfile())
    restored = load_package(path)
    assert layout_markdown(parse_markdown(restored.session), restored.resolver) == before
    assert restored.resolver.selection_records() == selected
    expanded = AssetResolver(embedded=[*r.pools["h"], *r.pools["−"], source("h", "extra"), source("−", "extra-minus")],
                             selections=tuple(r.selections.values()))
    after = layout_markdown(parse_markdown(session), expanded)
    assert after.pages == before.pages and after.fragments == before.fragments
    assert expanded.selection_records() == selected
    changed = AssetResolver(embedded=[source("h", "replacement"), source("−")],
                            selections=tuple(r.selections.values()))
    assert not layout_markdown(parse_markdown(session), changed).exportable
    assert inspect_resources(parse_markdown(session), changed)["gaps"][0]["action"] == "restore-selected-resource"


def test_fullwidth_dot_reuses_recorded_dot_existing_font_and_capture_list(tmp_path):
    dot = source(".")
    r = resolver(dot)
    full = r.pools["．"][0]
    assert full.strokes == dot.strokes and full.metrics.advance >= 1
    assert full.font_core["summary"]["shared_punctuation"]["source_asset_id"] == dot.asset_id
    assert full.font_core["trajectory"]["strokes"][0]["points"][0]["pressure"] == .2
    assert capture_character("．") == "."
    assert symbol_info("．")["math_class_hint"] == "punctuation"
    file = tmp_path / "dots.txt"
    file.write_text(".．", encoding="utf-8")
    assert [char for char, _, _ in parse_symbol_file(file)] == ["."]
    report = inspect_resources(parse_markdown(".．"), AssetResolver())
    rows = list(csv.DictReader(io.StringIO(gap_capture_csv(report["gaps"]))))
    assert [row["character"] for row in rows] == ["."]
    r = resolver(dot, source("．"))
    assert r.pools["．"][0].provider_version.startswith("symbol-sample")


def test_font_build_includes_hbar_sources_and_shared_dot(tmp_path):
    folder = tmp_path / "samples"
    folder.mkdir()
    for glyph in [source("h", style="italic"), source("−"), source(".")]:
        (folder / (str(ord(glyph.character)) + ".json")).write_bytes(glyph.original_json)
    output = tmp_path / "new.inkfont"
    build_font(output, writer="fixture", name="derived", symbols=folder)
    font = FontPackage(output)
    assert font.verify()
    hbar = next(font.glyphs("ℏ"))
    assert hbar.font_core["record"]["letter_style"] == "italic"
    assert hbar.font_core["summary"]["symbol_construction"]["rule"] == "hbar-from-h-and-minus"
    assert next(font.glyphs("．")).strokes == next(font.glyphs(".")).strokes


@pytest.mark.parametrize("source_text", ["12．3", "| 1．2 |\n| --- |\n| 3．4 |\n"])
def test_builtin_fullwidth_decimal_dot_exports_and_reopens(source_text, tmp_path):
    from inkstruct.assets.builtin import numeric_assets

    builtin = numeric_assets()
    assert builtin["．"].strokes == builtin["."].strokes
    assert builtin["．"].asset_id != builtin["."].asset_id
    assert builtin["．"].metrics.advance == 1
    r = AssetResolver(builtin_numbers=True)
    session = SourceSession(source_text)
    snapshot = layout_markdown(parse_markdown(session), r)
    assert snapshot.plotter_exportable, snapshot.diagnostics
    plan_from_snapshot(snapshot)
    path = tmp_path / "builtin-dot.inkdoc"
    save_package(path, session, r, PageProfile(), StyleProfile())
    restored = load_package(path)
    assert layout_markdown(parse_markdown(restored.session), restored.resolver) == snapshot
    # A document containing only a historical embedded decimal-point resource
    # also gets the explicit width variant when edited to add a fullwidth dot.
    old = AssetResolver(embedded=[builtin["."]])
    assert old.pools["．"] == (builtin["．"],)


def test_recorded_decimal_point_wins_over_the_builtin_width_variant():
    dot = source(".")
    r = AssetResolver(embedded=[dot], builtin_numbers=True)
    chosen = r.resolve(parse_markdown("．").occurrences[0])
    assert chosen.strokes == dot.strokes
    assert chosen.font_core["summary"]["shared_punctuation"]["source_asset_id"] == dot.asset_id


def test_existing_font_core_sources_work_without_rebuilding_font(tmp_path):
    folder = tmp_path / "core-samples"
    folder.mkdir()
    for glyph in [source("h", style="italic"), source("−"), source(".")]:
        (folder / (str(ord(glyph.character)) + ".json")).write_bytes(glyph.original_json)
    output = tmp_path / "source-font.inkfont"
    build_font(output, writer="fixture", name="old-font-fixture", symbols=folder)
    font = FontPackage(output)
    old_glyphs = tuple(g for g in font.glyphs() if g.character not in {"ℏ", "．"})
    originals = {g.asset_id: g.original_json for g in old_glyphs}
    r = AssetResolver(embedded=old_glyphs)
    assert {"ℏ", "．"} <= r.pools.keys()
    assert measure_math(parse_math(r"\hbar").root, r, owner="old-core").ready
    assert originals == {g.asset_id: g.original_json for g in old_glyphs}


def test_selected_ascii_minus_hbar_survives_adding_unicode_minus():
    h, ascii_minus = source("h"), source("-")
    r = resolver(h, ascii_minus)
    session = SourceSession(r"$\hbar$")
    before = layout_markdown(parse_markdown(session), r)
    selected = r.selection_records()
    expanded = AssetResolver(embedded=[h, ascii_minus, source("−")],
                             selections=tuple(r.selections.values()))
    after = layout_markdown(parse_markdown(session), expanded)
    assert after.exportable, after.diagnostics
    assert after.pages == before.pages and after.fragments == before.fragments
    assert expanded.selection_records() == selected
    # New occurrences prefer the dedicated mathematical minus, while historical
    # ASCII-source constructions remain available to existing frozen choices.
    fresh = resolver(h, ascii_minus, source("−"))
    box = measure_math(parse_math(r"\hbar").root, fresh, owner="fresh")
    assert box.ready
    assert box.glyphs[0].glyph.font_core["summary"]["symbol_construction"]["sources"][1]["character"] == "−"


@pytest.mark.parametrize("target,initial,supplied,text", [
    ("ℏ", [source("h"), source("−")], source("ℏ"), r"$\hbar$"),
    ("．", [source(".")], source("．"), "1．"),
])
def test_adding_independent_target_keeps_frozen_derivation_but_supplies_new_choices(target, initial, supplied, text):
    r = AssetResolver(embedded=initial, builtin_numbers=True)
    session = SourceSession(text)
    before = layout_markdown(parse_markdown(session), r)
    selected = r.selection_records()
    expanded = AssetResolver(embedded=[*initial, supplied], builtin_numbers=True,
                             selections=tuple(r.selections.values()))
    after = layout_markdown(parse_markdown(session), expanded)
    assert after.exportable, after.diagnostics
    assert after.pages == before.pages and after.fragments == before.fragments
    assert expanded.selection_records() == selected
    # The restored historical candidate is available exclusively for existing
    # choices. A new occurrence takes the independently supplied target.
    occurrence = next(o for o in parse_markdown(text).occurrences if o.text == target)
    fresh = AssetResolver(embedded=[g for pool in expanded.pools.values() for g in pool])
    assert fresh.resolve(occurrence).asset_id == supplied.asset_id


def test_adding_recorded_period_preserves_a_frozen_builtin_fullwidth_dot():
    from inkstruct.assets.builtin import numeric_assets

    r = AssetResolver(builtin_numbers=True)
    session = SourceSession("1．")
    before = layout_markdown(parse_markdown(session), r)
    selected = r.selection_records()
    old = numeric_assets()
    dot = source(".")
    expanded = AssetResolver(embedded=[old["1"], old["."], old["．"], dot],
                             selections=tuple(r.selections.values()))
    after = layout_markdown(parse_markdown(session), expanded)
    assert after.exportable, after.diagnostics
    assert after.pages == before.pages and after.fragments == before.fragments
    assert expanded.selection_records() == selected
    fresh = AssetResolver(embedded=[g for pool in expanded.pools.values() for g in pool])
    chosen = fresh.resolve(parse_markdown("．").occurrences[0])
    assert chosen.strokes == dot.strokes
    assert chosen.font_core["summary"]["shared_punctuation"]["source_asset_id"] == dot.asset_id


def point_on_ink(point, strokes):
    x, y = point
    for stroke in strokes:
        for first, last in pairwise(stroke):
            dx, dy = last[0] - first[0], last[1] - first[1]
            if (abs(dx * (y - first[1]) - dy * (x - first[0])) <= 1e-10
                    and min(first[0], last[0]) - 1e-10 <= x <= max(first[0], last[0]) + 1e-10
                    and min(first[1], last[1]) - 1e-10 <= y <= max(first[1], last[1]) + 1e-10):
                return True
    return False


@pytest.mark.parametrize("slanted", [False, True])
def test_hbar_crossbar_actually_intersects_upright_and_slanted_h(slanted):
    h = source("h")
    if slanted:
        raw = json.loads(h.original_json)
        points = [(95, 10), (35, 90), (60, 50), (85, 60), (85, 90)]
        for point, (x, y) in zip(raw["strokes"][0]["points"], points, strict=True):
            point.update(x=x, y=y)
        h = adapt_symbol(json.dumps(raw).encode())
    made = resolver(h, source("−")).pools["ℏ"][0]
    construction = made.font_core["summary"]["symbol_construction"]
    crossing = construction["hbar_crossing_em"]
    assert crossing[1] == pytest.approx(h.bounds[1] + .25 * (h.bounds[3] - h.bounds[1]))
    assert point_on_ink(crossing, h.strokes)
    assert point_on_ink(crossing, made.strokes[len(h.strokes):])
    assert made.strokes[:len(h.strokes)] == h.strokes
    affine = construction["component_affines_em"][1]
    source_x, source_y = construction["minus_crossing_em"]
    assert (source_x * affine[0] + affine[4], source_y + affine[5]) == pytest.approx(crossing)
    if slanted:
        # The former bbox-left placement ended before this ascender crossing.
        assert h.bounds[0] - .05 + construction["bar_extent_em"] < crossing[0]
    else:
        assert abs(min(x for st in made.strokes[1:] for x, _ in st) - (h.bounds[0] - .05)) < .02


def test_hbar_retains_corrected_h_optical_reference_frame(tmp_path):
    from inkstruct.fonts.core import resolved_candidate, semantic_hash, trajectory_hashes

    folder = tmp_path / "corrected-h"
    folder.mkdir()
    h, minus = source("h", style="italic"), source("−")
    for glyph in (h, minus):
        (folder / (str(ord(glyph.character)) + ".json")).write_bytes(glyph.original_json)
    output = tmp_path / "source.inkfont"
    build_font(output, writer="fixture", name="correction-fixture", symbols=folder)
    font = FontPackage(output)
    original = next(font.glyphs("h"))
    core = copy.deepcopy(original.font_core)
    frame = {"bounds": list(original.bounds), "metrics": dict(core["metrics"])}
    frame["metrics"]["baseline"] = .92
    core["summary"]["optical_layout_frame"] = frame
    for stroke in core["trajectory"]["strokes"]:
        for point in stroke["points"]:
            point["x"] += .3
            point["y"] -= .08
    core["record"].update(**trajectory_hashes(core["trajectory"]),
                          source_summary_hash=semantic_hash(core["summary"]))
    corrected = resolved_candidate(core["record"], core["trajectory"], core["metrics"],
                                   core["summary"], core["identity"])
    made = AssetResolver(embedded=[corrected, next(font.glyphs("−"))]).pools["ℏ"][0]
    assert made.strokes[:len(corrected.strokes)] == corrected.strokes
    assert made.layout_metrics.baseline == corrected.layout_metrics.baseline == .92
    assert made.layout_metrics.ascent == corrected.layout_metrics.ascent
    assert made.layout_metrics.descent == corrected.layout_metrics.descent
    bar = [point for stroke in made.strokes[len(corrected.strokes):] for point in stroke]
    expected = (min(frame["bounds"][0], min(x for x, _ in bar)),
                min(frame["bounds"][1], min(y for _, y in bar)),
                max(frame["bounds"][2], max(x for x, _ in bar)),
                max(frame["bounds"][3], max(y for _, y in bar)))
    assert made.layout_bounds == pytest.approx(expected)
    assert made.font_core["record"]["letter_style"] == "italic"
