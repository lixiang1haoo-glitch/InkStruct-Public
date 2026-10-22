from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace
from xml.etree import ElementTree as ET

import pytest

from inkstruct.assets.glyph_provider import GlyphMetrics, GlyphProvider, adapt_glyph
from inkstruct.cli import main
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.source import (
    clusters,
    parse_plain_text,
    scalar_to_utf16,
    utf16_to_scalar,
)
from inkstruct.layout.plain import CLOSING, OPENING, layout_document
from inkstruct.renderers.pages import export_pages, page_png, page_svg


def glyph(character="人", **changes):
    value = {
        "schema_version": "personal_trajectory_v1",
        "character": character,
        "codepoint": f"U+{ord(character):04X}",
        "locale": "zh-Hans",
        "writer_id": "test",
        "structure_version": "test-v1",
        "profile_version": "test-v1",
        "generator": "fixture",
        "confidence": 1.0,
        "strokes": [
            {
                "standard_stroke_id": "s1",
                "order": 1,
                "confidence": 1.0,
                "points": [
                    {"x": 0.1, "y": 0.1, "t_ms": 0, "pressure": 0.4, "pen_state": "down"},
                    {"x": 0.5, "y": 0.5, "t_ms": 30, "pressure": 0.8, "pen_state": "up"},
                ],
            },
            {
                "standard_stroke_id": "s2",
                "order": 2,
                "confidence": 1.0,
                "points": [
                    {"x": 0.5, "y": 0.4, "t_ms": 90, "pressure": 0.5, "pen_state": "down"},
                    {"x": 0.9, "y": 0.9, "t_ms": 130, "pressure": 0.2, "pen_state": "end"},
                ],
            },
        ],
        "source_components": {"fixture_extra_metadata": True},
    }
    value.update(changes)
    return value


def provider(text="人"):
    return GlyphProvider(
        {c: adapt_glyph(glyph(c), metrics=GlyphMetrics()) for c in set(text) if not c.isspace()}
    )


def test_adapter_preserves_all_geometry_dynamics_and_unknown_metadata():
    value = glyph()
    original = copy.deepcopy(value)
    asset = adapt_glyph(value)
    assert json.loads(asset.original_json) == original
    assert asset.strokes[0][-1].pen_state == "up"
    assert asset.strokes[1][-1].pen_state == "end"
    assert asset.strokes[1][0].t_ms == 90
    value["strokes"][0]["points"][0]["x"] = 0.7
    assert asset.strokes[0][0].x == 0.1
    with pytest.raises(FrozenInstanceError):
        asset.strokes[0][0].x = 0.6


@pytest.mark.parametrize(
    "field,value",
    [
        ("x", float("nan")),
        ("y", float("inf")),
        ("pressure", 2),
        ("t_ms", -1),
        ("pen_state", "unknown"),
    ],
)
def test_invalid_assets_rejected(field, value):
    data = glyph()
    data["strokes"][0]["points"][0][field] = value
    with pytest.raises(ValueError):
        adapt_glyph(data)


def test_non_han_requires_calibration():
    with pytest.raises(ValueError, match="calibrated"):
        adapt_glyph(glyph("a"))
    assert adapt_glyph(glyph("a"), metrics=GlyphMetrics(advance=0.6)).metrics.advance == 0.6


def test_utf16_round_trip_crlf_combining_non_bmp():
    source = "人𠀀e\u0301\r\n👩\u200d🔬"
    for i in range(len(source) + 1):
        assert utf16_to_scalar(source, scalar_to_utf16(source, i)) == i
    with pytest.raises(ValueError, match="surrogate"):
        utf16_to_scalar(source, 2)
    assert [text for _, text in clusters(source)] == ["人", "𠀀", "e\u0301", "\r\n", "👩\u200d🔬"]
    assert [text for _, text in clusters("🇨🇳👍🏽\n")] == ["🇨🇳", "👍🏽", "\n"]


def test_repeated_occurrences_and_source_coverage_across_pages():
    source = "人人 人\t人\r\n\r\n" + "人" * 80 + "\n"
    doc = parse_plain_text(source, page=PageProfile(35, 40, 5))
    snap = layout_document(doc, provider())
    assert snap.exportable
    assert len(snap.pages) > 2
    assert "".join(f.text for f in snap.fragments) == source
    assert [(f.span.start, f.span.end) for f in snap.fragments] == [
        (o.span.start, o.span.end) for o in doc.occurrences
    ]
    assert len({f.occurrence_id for f in snap.fragments}) == len(snap.fragments)
    assert len({f.asset_id for f in snap.fragments if f.asset_id}) == 1
    for f in snap.fragments:
        if f.ink_bounds:
            x0, y0, x1, y1 = f.ink_bounds
            assert 5 <= x0 <= x1 <= 30
            assert 5 <= y0 <= y1 <= 35


def test_blank_lines_and_trailing_newline_occupy_pages():
    snap = layout_document(
        parse_plain_text("\r\n\n\n", page=PageProfile(30, 28, 5)), GlyphProvider({})
    )
    assert snap.exportable
    assert len(snap.pages) == 2
    assert "".join(f.text for f in snap.fragments) == "\r\n\n\n"


@pytest.mark.parametrize("text", ["人人，人人。人人", "人人（人人）人人", "人「人」人！人？"])
def test_kinsoku_on_wrapped_lines(text):
    snap = layout_document(parse_plain_text(text, page=PageProfile(29, 100, 5)), provider(text))
    assert snap.exportable
    lines = {}
    for f in snap.fragments:
        lines.setdefault(f.line_index, []).append(f.text)
    assert len(lines) > 1
    for line in lines.values():
        assert line[0] not in CLOSING
        assert line[-1] not in OPENING


def test_long_latin_word_is_diagnosed_not_split_or_looped():
    text = "abcdefghijk"
    snap = layout_document(parse_plain_text(text, page=PageProfile(25, 40, 5)), provider(text))
    assert {d.code for d in snap.diagnostics} >= {"line-width-overflow"}
    assert len(snap.pages) == 1
    assert len({f.line_index for f in snap.fragments}) == 1
    assert "".join(f.text for f in snap.fragments) == text


def test_oversized_height_makes_bounded_progress():
    doc = parse_plain_text("人\n人\n人", page=PageProfile(30, 15, 5))
    snap = layout_document(doc, provider())
    assert len(snap.pages) == 3
    assert sum(d.code == "line-height-overflow" for d in snap.diagnostics) == 3


def test_asset_metrics_expand_line_height_and_share_baseline():
    assets = {
        "人": adapt_glyph(glyph()),
        "a": adapt_glyph(glyph("a"), metrics=GlyphMetrics(0.6, 1.3, 1.3, 0.5)),
    }
    snap = layout_document(parse_plain_text("人a\n人"), GlyphProvider(assets))
    one, tall, _, next_line = snap.fragments
    assert one.baseline_mm == tall.baseline_mm
    assert next_line.logical_bounds[1] >= tall.logical_bounds[3]


def test_missing_unsupported_and_export_gate(tmp_path):
    doc = parse_plain_text("人未e\u0301👩\u200d🔬")
    snap = layout_document(doc, provider())
    assert [f.status for f in snap.fragments] == ["ready", "missing", "unsupported", "unsupported"]
    assert len(snap.diagnostics) == 3
    output = tmp_path / "export"
    with pytest.raises(ValueError, match="block"):
        export_pages(snap, output)
    assert not output.exists()
    export_pages(snap, output, debug=True)
    assert "NOT A FINISHED EXPORT" in (output / "debug-page-001.svg").read_text()
    assert not (output / "page-001.svg").exists()


def test_complete_job_key_and_geometry_determinism():
    doc, assets = parse_plain_text("人人"), provider()
    first = layout_document(doc, assets, request_id="same")
    same = layout_document(doc, assets, request_id="same")
    assert first.job_key == same.job_key
    assert first.pages[0].paint_ops == same.pages[0].paint_ops
    variants = [
        layout_document(doc, assets),
        layout_document(replace(doc, revision=1), assets, request_id="same"),
        layout_document(replace(doc, style=StyleProfile(em_mm=7)), assets, request_id="same"),
        layout_document(doc, GlyphProvider({}), request_id="same"),
        layout_document(
            doc,
            GlyphProvider({"人": adapt_glyph(glyph(), metrics=GlyphMetrics(advance=1.1))}),
            request_id="same",
        ),
    ]
    assert all(s.job_key != first.job_key for s in variants)


def test_svg_and_png_retain_endpoints_and_physical_geometry():
    snap = layout_document(parse_plain_text("人"), provider())
    root = ET.fromstring(page_svg(snap, 0))
    polylines = root.findall("{http://www.w3.org/2000/svg}polyline")
    assert len(polylines) == 2
    for op, element in zip(snap.pages[0].paint_ops, polylines, strict=True):
        coords = [tuple(map(float, pair.split(","))) for pair in element.attrib["points"].split()]
        for actual, expected in zip(coords, op.points, strict=True):
            assert actual == pytest.approx(expected)
        assert float(element.attrib["stroke-width"]) == 0.3
    image = page_png(snap, 0, dpi=254)
    assert image.size == (2100, 2970)
    x, y = snap.pages[0].paint_ops[-1].points[-1]
    assert image.getpixel((round(x * 10), round(y * 10))) != (255, 255, 255)


def test_single_point_stroke_draws_dot():
    value = glyph()
    value["strokes"] = value["strokes"][:1]
    value["strokes"][0]["points"] = value["strokes"][0]["points"][:1]
    snap = layout_document(parse_plain_text("人"), GlyphProvider({"人": adapt_glyph(value)}))
    assert "<circle" in page_svg(snap, 0)


def test_export_failure_removes_staging_and_keeps_old_output(tmp_path, monkeypatch):
    snap = layout_document(parse_plain_text("人"), provider())
    output = tmp_path / "pages"
    output.mkdir()
    (output / "old").write_text("keep")
    with pytest.raises(FileExistsError):
        export_pages(snap, output)
    assert (output / "old").read_text() == "keep"
    from inkstruct.renderers import pages

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pages, "page_png", fail)
    with pytest.raises(OSError, match="disk full"):
        export_pages(snap, tmp_path / "new")
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("dpi", [0, -1, float("nan"), 100000])
def test_png_resource_limits(dpi):
    with pytest.raises(ValueError):
        page_png(layout_document(parse_plain_text(""), GlyphProvider({})), 0, dpi=dpi)


@pytest.mark.parametrize("plotter", [False, True])
def test_run_adapter_and_cli_keep_original_bytes(tmp_path, capsys, plotter):
    trajectory = tmp_path / "run" / "trajectories"
    trajectory.mkdir(parents=True)
    raw = json.dumps(glyph(), ensure_ascii=False, indent=2).encode()
    path = trajectory / "U+4EBA.json"
    path.write_bytes(raw)
    source = tmp_path / "source.txt"
    source.write_bytes("人人\r\n 人".encode())
    output = tmp_path / "pages"
    assert (
        main(
            [
                "document",
                "render",
                str(source),
                "--run",
                str(trajectory.parent),
                "--output",
                str(output),
                *(["--plotter", "--optimize-paths"] if plotter else []),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["exportable"]
    if plotter:
        report = json.loads((output / "plotter.json").read_bytes())
        assert report["optimized"] and report["allow_reverse"]
        assert len(report["pages"][0]["strokes"]) == 6
        svg = ET.fromstring((output / "page-001.svg").read_bytes())
        assert all(p.tag == "{http://www.w3.org/2000/svg}path" for p in svg)
    else:
        report = json.loads((output / "layout.json").read_bytes())
        assert report["kind"] == "finished-pages"
        fs = report["snapshot"]["pages"][0]["fragments"]
        assert "".join(f["text"] for f in fs) == source.read_bytes().decode()
    assert path.read_bytes() == raw
    source.write_text("缺")
    assert (
        main(
            [
                "document",
                "render",
                str(source),
                "--run",
                str(trajectory.parent),
                "--output",
                str(tmp_path / "missing"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "missing").exists()


def test_mismatched_and_corrupt_asset_diagnostics(tmp_path):
    root = tmp_path / "trajectories"
    root.mkdir()
    (root / "U+4EBA.json").write_text(json.dumps(glyph("天")))
    (root / "U+5929.json").write_text("{broken")
    assets = GlyphProvider.from_run(tmp_path, "人天")
    assert set(assets.failures) == {"人", "天"}
    snap = layout_document(parse_plain_text("人天"), assets)
    assert all(f.status == "failed" for f in snap.fragments)


def test_hard_break_cannot_hide_impossible_kinsoku():
    text = "人（\n）人"
    snap = layout_document(parse_plain_text(text), provider(text))
    assert sum(d.code == "forbidden-line-boundary" for d in snap.diagnostics) == 2
    assert "".join(f.text for f in snap.fragments) == text


@pytest.mark.parametrize("character", list("⺀⺈⺊⺌⺍⺗⺮⺳⺼"))
def test_full_library_radicals_use_chinese_em_contract(character):
    asset = adapt_glyph(glyph(character))
    snap = layout_document(parse_plain_text(character), GlyphProvider({character: asset}))
    assert snap.exportable
    assert snap.fragments[0].status == "ready"
    assert snap.fragments[0].asset_id == asset.asset_id
