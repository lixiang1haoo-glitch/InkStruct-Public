"""Audit a real symbol ZIP and publish portable specimens and mixed-layout evidence.

No source archive or historical project is modified. Use a new output directory.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from inkstruct.assets.glyph_provider import GlyphProvider
from inkstruct.assets.resolver import AssetResolver, SelectedAsset, gap_capture_csv
from inkstruct.assets.symbol_provider import SymbolProvider
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import calibrate_tables
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.math.parser import SYMBOLS
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan, route_page
from inkstruct.plotter.svg import page_svg
from inkstruct.renderers.pages import export_pages
from inkstruct.symbol_capture import CATALOG


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def publish(name, session, resolver, flow, output):
    target = output / name
    target.mkdir()
    page, style = PageProfile(), StyleProfile()
    doc = parse_markdown(session)
    snapshot = layout_markdown(doc, resolver, page=page, style=style, flow=flow)
    assert snapshot.plotter_exportable, snapshot.diagnostics
    assert Counter(f.occurrence_id for f in snapshot.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    # Verify each math specimen is uniformly scaled/translated, never bbox-fitted.
    lookup = {g.asset_id: g for pool in resolver.pools.values() for g in pool}
    math_points = formulas = 0
    for root in doc.nodes:
        for node in root.walk():
            if not node.math:
                continue
            formulas += 1
            measured = measure_math(
                node.math,
                resolver,
                owner=node.node_id,
                style=flow.math,
                stroke_width=style.stroke_width_mm,
                display=node.kind == "math_block",
            )
            scales = {g.occurrence.occurrence_id: g.em_mm for g in measured.glyphs}
            for fragment in (f for f in snapshot.fragments if f.node_id == node.node_id):
                glyph = lookup[fragment.asset_id]
                ops = [
                    op
                    for op in snapshot.pages[fragment.page_index].paint_ops
                    if op.occurrence_id == fragment.occurrence_id
                ]
                assert len(ops) == len(glyph.strokes)
                em = scales[fragment.occurrence_id]
                for op, stroke in zip(ops, glyph.strokes, strict=True):
                    assert len(op.points) == len(stroke)
                    dx, dy = (op.points[0][i] - stroke[0][i] * em for i in (0, 1))
                    for (x, y), (sx, sy) in zip(op.points, stroke, strict=True):
                        assert abs(x - dx - sx * em) < 1e-8
                        assert abs(y - dy - sy * em) < 1e-8
                        math_points += 1
    (target / "source.md").write_text(session.source)
    project = target / f"{name}.inkdoc"
    save_package(project, session, resolver, page, style, flow=flow, optimize=True)
    loaded = load_package(project)
    restored = layout_markdown(
        parse_markdown(loaded.session),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    assert snapshot == restored
    assert resolver.selection_records() == loaded.resolver.selection_records()
    assert {g.asset_id: g.original_json for pool in resolver.pools.values() for g in pool} == {
        g.asset_id: g.original_json for pool in loaded.resolver.pools.values() for g in pool
    }
    export_pages(snapshot, target / "preview", dpi=180)
    plan = plan_from_snapshot(snapshot)
    export_plan(plan, target / "machine", optimize=True)
    routes = []
    for p in plan.pages:
        route = route_page(p, optimize=True)
        assert route.after_mm <= route.before_mm + 1e-8
        assert sorted(route.source_indices) == list(range(len(p.strokes)))
        for stroke, idx, rev in zip(
            route.page.strokes, route.source_indices, route.reversed_paths, strict=True
        ):
            assert stroke.points == (p.strokes[idx].points[::-1] if rev else p.strokes[idx].points)
        svg = (target / "machine" / f"page-{p.index + 1:03d}.svg").read_text()
        assert svg == page_svg(route.page)
        root = ET.fromstring(svg)
        assert all(
            e.tag == "{http://www.w3.org/2000/svg}path"
            and set(re.findall("[A-Za-z]", e.attrib["d"])) == {"M", "L"}
            and "transform" not in e.attrib
            for e in root
        )
        routes.append(
            {
                "page": p.index + 1,
                "paths": len(p.strokes),
                "before_mm": route.before_mm,
                "after_mm": route.after_mm,
                "reversed": sum(route.reversed_paths),
            }
        )
    return {
        "pages": len(snapshot.pages),
        "formulas": formulas,
        "fragments": len(snapshot.fragments),
        "math_points_checked": math_points,
        "used_assets": len({f.asset_id for f in snapshot.fragments if f.asset_id}),
        "diagnostics": [asdict(d) for d in snapshot.diagnostics],
        "routing": routes,
        "roundtrip_exact": True,
        "strict_ml_svg": True,
        "geometry_unchanged_by_routing": True,
    }


def atlas(symbols, output):
    from PIL import Image, ImageDraw

    rows = []
    chars = sorted(symbols.pools)
    for start in range(0, len(chars), 20):
        image = Image.new("RGB", (1200, 20 * 120), "white")
        draw = ImageDraw.Draw(image)
        for row, c in enumerate(chars[start : start + 20]):
            draw.text((5, row * 120 + 8), f"U+{ord(c):04X}", fill="black")
            cards = []
            for i, g in enumerate(symbols.pools[c]):
                # Same fixed guide frame for every sample; no sample-specific scaling.
                x0, y0 = 90 + i * 108, row * 120 + 15
                for y, color in [(0.18, "#cbd5e1"), (0.63, "#93c5fd"), (0.88, "#fca5a5")]:
                    draw.line((x0, y0 + y * 80, x0 + 90, y0 + y * 80), fill=color)
                paths = []
                for stroke in g.strokes:
                    draw.line(
                        [(x0 + x * 80, y0 + y * 80) for x, y in stroke], fill="#172033", width=2
                    )
                    paths.append(
                        '<polyline points="' + " ".join(f"{x},{y}" for x, y in stroke) + '"/>'
                    )
                cards.append(
                    f'<figure><svg viewBox="-0.15 0 1.4 1.2"><path d="M0 .18H1.1 M0 .63H1.1 M0 .88H1.1" stroke="#cbd5e1" stroke-width=".01"/>'
                    f'<g fill="none" stroke="#172033" stroke-width=".018">{"".join(paths)}</g></svg>'
                    f"<figcaption>{i + 1} · {len(g.strokes)} 笔<br>{escape(g.sample_id[:8])}</figcaption></figure>"
                )
            rows.append(
                f"<section><h2>{escape(c)} <small>U+{ord(c):04X}</small></h2><div>{''.join(cards)}</div></section>"
            )
        image.save(output / f"atlas-{start // 20 + 1:02d}.png")
    (output / "atlas.html").write_text(
        '<!doctype html><html lang="zh"><meta charset="utf-8"><title>符号样本对照</title><style>'
        "body{font:16px system-ui;margin:32px;color:#172033}section{border-top:1px solid #ddd}section div{display:flex;flex-wrap:wrap}figure{width:120px;margin:8px}svg{width:120px;height:110px}figcaption{font:12px monospace}small{font-weight:normal}</style>"
        f"<h1>{len(chars)} 字符 · {sum(map(len, symbols.pools.values()))} 样本</h1><p>固定 em 比例。横线依次为大写高度、数学轴、基线；参考线不进入机器导出。标签是查看用字体，字形均为原始采集轨迹。</p>"
        + "".join(rows)
        + "</html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--source", type=Path, default=Path("examples/markdown_symbols_20261013.md")
    )
    args = parser.parse_args()
    symbols = SymbolProvider.from_zip(args.archive)
    glyphs = [g for c in sorted(symbols.pools) for g in symbols.pools[c]]
    assert all(g.machine_capability == "centerline" for g in glyphs)
    args.output.mkdir(parents=True, exist_ok=False)
    flow = calibrate_tables(FlowStyle(), symbols)
    commands = []
    for command, character in SYMBOLS.items():
        if character not in symbols.pools:
            continue
        doc = parse_markdown("$\\" + command + "$")
        result = layout_markdown(doc, AssetResolver(symbols=symbols), flow=flow)
        assert result.plotter_exportable, (command, result.diagnostics)
        assert any(
            f.asset_id in {g.asset_id for g in symbols.pools[character]} for f in result.fragments
        )
        commands.append({"command": "\\" + command, "character": character})
    write_json(args.output / "command-probes.json", commands)
    capture_records = [json.loads(g.original_json) for g in glyphs]
    for raw, glyph in zip(capture_records, glyphs, strict=True):
        assert raw["stats"]["stroke_count"] == len(glyph.strokes)
        assert raw["stats"]["point_count"] == sum(map(len, glyph.strokes))
        assert raw["codepoint"] == f"U+{ord(glyph.character):04X}"
    write_json(
        args.output / "capture-audit.json",
        {
            "all_centerlines": True,
            "stats_match_geometry": True,
            "guide_profiles": dict(
                Counter(json.dumps(r["guides"], sort_keys=True) for r in capture_records)
            ),
            "calibration_status": dict(
                Counter(r["metrics"]["calibration_status"] for r in capture_records)
            ),
            "review_status": dict(Counter(r["variant"]["review_status"] for r in capture_records)),
        },
    )
    inventory = []
    for c, pool in sorted(symbols.pools.items()):
        inventory.append(
            {
                "character": c,
                "codepoint": f"U+{ord(c):04X}",
                "count": len(pool),
                "stroke_counts": sorted({len(g.strokes) for g in pool}),
                "samples": [
                    {
                        "sample_id": g.sample_id,
                        "asset_id": g.asset_id,
                        "bounds": g.bounds,
                        "capability": g.machine_capability,
                    }
                    for g in pool
                ],
            }
        )
    write_json(args.output / "inventory.json", inventory)
    atlas(symbols, args.output)
    # A specimen inventory is literal code, not prose subject to punctuation line breaks.
    source = (
        "```\n"
        + "\n".join(" ".join(c for _ in pool) for c, pool in sorted(symbols.pools.items()))
        + "\n```\n"
    )
    session = SourceSession(source, document_id="user001-symbol-specimens-20261013")
    doc = parse_markdown(session)
    occurrences = [o for o in doc.occurrences if not o.text.isspace()]
    assert [o.text for o in occurrences] == [g.character for g in glyphs]
    selected = [
        SelectedAsset(o.occurrence_id, o.text, g.asset_id, g.sample_id, g.metrics_key)
        for o, g in zip(occurrences, glyphs, strict=True)
    ]
    specimens = publish(
        "specimens", session, AssetResolver(symbols=symbols, selections=selected), flow, args.output
    )
    assert specimens["used_assets"] == len(glyphs)
    session = SourceSession(args.source.read_text(), document_id="user001-symbol-mixed-20261013")
    doc = parse_markdown(session)
    generated = GlyphProvider.from_run(args.run, "".join(o.text for o in doc.occurrences))
    mixed = publish(
        "mixed", session, AssetResolver(generated, symbols, seed=1013), flow, args.output
    )
    gap_doc = parse_markdown(
        " ".join(CATALOG[k] for k in ("英文大写", "英文小写", "希腊字母", "希腊变体"))
    )
    gaps = AssetResolver(symbols=symbols).gaps(gap_doc.occurrences)
    (args.output / "missing-letter-capture.csv").write_text(gap_capture_csv(gaps))
    assert sha256(args.archive.read_bytes()).hexdigest() == symbols.archive_hash
    write_json(
        args.output / "verification.json",
        {
            "archive": str(args.archive),
            "archive_sha256": symbols.archive_hash,
            "characters": len(symbols.pools),
            "samples": len(glyphs),
            "real_sample_commands_verified": len(commands),
            "specimens": specimens,
            "mixed": mixed,
            "table_style": asdict(flow.table),
            "math_style": asdict(flow.math),
            "missing_letters": len(gaps),
            "calibration": "guide_based_unreviewed",
            "physical_plotter_test": False,
            "raw_archive_unchanged": True,
        },
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "characters": len(symbols.pools),
                "samples": len(glyphs),
                "specimen_pages": specimens["pages"],
                "mixed_pages": mixed["pages"],
                "formulas": mixed["formulas"],
            }
        )
    )


if __name__ == "__main__":
    main()
