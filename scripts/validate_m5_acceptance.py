"""Reproducible M5 combined report using a local captured-symbol archive."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import SymbolProvider
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan, route_page
from inkstruct.plotter.svg import page_svg
from inkstruct.renderers.pages import export_pages


def verify(doc, snapshot, resolver):
    assert snapshot.plotter_exportable, snapshot.diagnostics
    assert Counter(f.occurrence_id for f in snapshot.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    lookup = {g.asset_id: g for pool in resolver.pools.values() for g in pool}
    points_checked = 0
    for page in snapshot.pages:
        by = {}
        for op in page.paint_ops:
            by.setdefault(op.occurrence_id, []).append(op)
            radius = op.width_mm / 2
            for x, y in op.points:
                assert radius <= x <= snapshot.page_profile.width_mm - radius
                assert radius <= y <= snapshot.page_profile.height_mm - radius
        foot = [f for f in page.fragments if (f.container_id or "").startswith("footnote:")]
        body = [f for f in page.fragments if f not in foot]
        if foot:
            separators = [
                op for op in page.paint_ops if op.occurrence_id.startswith("footnotes:separator:")
            ]
            assert len(separators) == 1
            y = separators[0].points[0][1]
            assert not body or max(f.logical_bounds[3] for f in body) < y
            assert y < min(f.logical_bounds[1] for f in foot)
        for fragment in page.fragments:
            if not fragment.asset_id:
                continue  # Structural task boxes have no captured specimen.
            glyph = lookup[fragment.asset_id]
            ops = by[fragment.occurrence_id]
            assert [len(op.points) for op in ops] == [len(stroke) for stroke in glyph.strokes]
            source = [p for stroke in glyph.strokes for p in stroke]
            placed = [p for op in ops for p in op.points]
            # Infer a single positive scale and translation, then check every
            # original point, including all stroke boundaries. No redraws.
            j = max(
                range(len(source)),
                key=lambda j: sum((source[j][i] - source[0][i]) ** 2 for i in (0, 1)),
            )
            axis = max((0, 1), key=lambda i: abs(source[j][i] - source[0][i]))
            scale = (placed[j][axis] - placed[0][axis]) / (source[j][axis] - source[0][axis])
            assert scale > 0
            offset = [placed[0][i] - scale * source[0][i] for i in (0, 1)]
            for a, b in zip(source, placed, strict=True):
                assert all(abs(b[i] - offset[i] - scale * a[i]) < 1e-8 for i in (0, 1))
                points_checked += 1
    return points_checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--source", type=Path, default=Path("tests/fixtures/markdown_mixed/m5_acceptance.md")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    raw_hash = sha256(args.archive.read_bytes()).hexdigest()
    symbols = SymbolProvider.from_zip(args.archive)
    resolver = AssetResolver(symbols=symbols)
    session = SourceSession(args.source.read_text())
    flow = FlowStyle(
        markdown_dialect="obsidian",
        math=MathStyle(
            fraction_source="sample", radical_source="sample", delimiter_source="sample"
        ),
    )
    page, style = PageProfile(), StyleProfile()
    doc = parse_markdown(session, dialect=flow.markdown_dialect)
    snapshot = layout_markdown(doc, resolver, page=page, style=style, flow=flow)
    point_count = verify(doc, snapshot, resolver)
    project = args.output / "m5-combined.inkdoc"
    save_package(project, session, resolver, page, style, flow=flow, optimize=True)
    loaded = load_package(project)
    restored = layout_markdown(
        parse_markdown(loaded.session, dialect=loaded.flow.markdown_dialect),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    assert restored == snapshot
    assert resolver.selection_records() == loaded.resolver.selection_records()
    originals = lambda r: {g.asset_id: g.original_json for pool in r.pools.values() for g in pool}
    assert originals(resolver) == originals(loaded.resolver)
    export_pages(snapshot, args.output / "preview", dpi=144)
    plan = plan_from_snapshot(snapshot)
    export_plan(plan, args.output / "machine", optimize=True)
    paths = 0
    for page in plan.pages:
        route = route_page(page, optimize=True)
        assert route.after_mm <= route.before_mm
        assert sorted(route.source_indices) == list(range(len(page.strokes)))
        for stroke, index, reverse in zip(
            route.page.strokes, route.source_indices, route.reversed_paths, strict=True
        ):
            original = page.strokes[index]
            assert stroke.points == (original.points[::-1] if reverse else original.points)
        svg = (args.output / "machine" / f"page-{page.index + 1:03d}.svg").read_text()
        assert svg == page_svg(route.page)
        for element in ET.fromstring(svg):
            assert element.tag == "{http://www.w3.org/2000/svg}path"
            assert "transform" not in element.attrib
            commands = re.findall("[A-Za-z]", element.attrib["d"])
            assert commands[0] == "M" and set(commands[1:]) == {"L"}
            paths += 1
    assert sha256(args.archive.read_bytes()).hexdigest() == raw_hash
    report = {
        "archive_sha256": raw_hash,
        "source_sha256": sha256(args.source.read_bytes()).hexdigest(),
        "pages": len(snapshot.pages),
        "paths": paths,
        "occurrences": len(doc.occurrences),
        "original_points_checked": point_count,
        "kinds": sorted({n.kind for root in doc.nodes for n in root.walk()}),
        "diagnostics": [asdict(d) for d in snapshot.diagnostics],
        "source_coverage_exact": True,
        "roundtrip_exact": True,
        "raw_assets_unchanged": True,
        "strict_ml": True,
        "optimized_geometry_exact": True,
        "physical_plotter_test": False,
    }
    (args.output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "diagnostics"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
