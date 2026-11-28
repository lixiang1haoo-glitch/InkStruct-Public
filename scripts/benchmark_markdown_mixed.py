"""Fixed 1/10/50-page benchmark with independent processes and archived raw observations.

Run from the repository with its installed Python. Outputs must use a new directory.
Cold means a fresh Python process; OS filesystem caches are not flushed. Warm means
repeated full layout with loaded assets, not incremental layout or a measured UI frame.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import threading
import time
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/markdown_mixed/performance"


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def rss_mb():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024**2 if sys.platform == "darwin" else 1024)


def timed(call):
    start = time.perf_counter()
    result = call()
    return result, (time.perf_counter() - start) * 1000


@contextlib.contextmanager
def layout_stages(module):
    """Time disjoint top-level measurement and line-breaking calls; remainder includes painting."""
    values = {"measurement_ms": 0.0, "line_break_ms": 0.0}
    originals = {}

    def wrap(fn, key):
        def wrapped(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                values[key] += (time.perf_counter() - start) * 1000

        return wrapped

    for name in ("measure_runs", "measure_table", "measure_code", "measure_image", "break_lines"):
        originals[name] = getattr(module, name)
        setattr(
            module,
            name,
            wrap(originals[name], "line_break_ms" if name == "break_lines" else "measurement_ms"),
        )
    try:
        yield values
    finally:
        for name, value in originals.items():
            setattr(module, name, value)


def prepare(output, glyph_project=None):
    from inkstruct.assets.resolver import AssetResolver
    from inkstruct.document.editing import SourceSession
    from inkstruct.document.markdown import parse_markdown
    from inkstruct.document.package import load_package, save_package
    from inkstruct.document.schema import PageProfile, StyleProfile
    from inkstruct.layout.blocks import layout_markdown

    records = json.loads((FIXTURES / "manifest.json").read_text())["fixtures"]
    embedded = ()
    if glyph_project:
        resource_project = load_package(glyph_project)
        embedded = tuple(
            glyph for char in "0123456789." for glyph in resource_project.resolver.pools[char]
        )
        dump(
            output / "glyph-resources.json",
            {
                "project_sha256": sha256(glyph_project.read_bytes()).hexdigest(),
                "writers": sorted({g.writer_id for g in embedded}),
                "variants": len(embedded),
                "asset_ids": sorted({g.asset_id for g in embedded}),
            },
        )
    for item in records:
        raw = (FIXTURES / item["path"]).read_bytes()
        assert sha256(raw).hexdigest() == item["sha256"]
        source = raw.decode()
        session = SourceSession(source, document_id=f"fixed-performance-{item['pages']}")
        session.atom_ids = tuple(
            sha256(f"{session.document_id}:{i}".encode()).hexdigest()[:32]
            for i in range(len(source))
        )
        resolver = AssetResolver(embedded=embedded, builtin_numbers=True)
        snapshot = layout_markdown(parse_markdown(session), resolver)
        assert snapshot.plotter_exportable and len(snapshot.pages) == item["pages"]
        package = output / f"{item['pages']:02d}-pages.inkdoc"
        save_package(package, session, resolver, PageProfile(), StyleProfile(), optimize=True)
        item["package_sha256"] = sha256(package.read_bytes()).hexdigest()
    dump(output / "inputs.json", records)


def worker(package, output):
    began = time.perf_counter()
    from inkstruct.document.markdown import parse_markdown
    from inkstruct.document.package import load_package
    from inkstruct.layout import blocks
    from inkstruct.plotter import export
    from inkstruct.plotter.adapters import plan_from_snapshot
    from inkstruct.renderers.pages import page_png

    imports = (time.perf_counter() - began) * 1000
    p, read_ms = timed(lambda: load_package(package))
    phases = {"imports_ms": imports, "package_read_ms": read_ms}
    cancelled = threading.Event()

    def layout_once(prefix):
        document, phases[prefix + "_parse_ms"] = timed(
            lambda: parse_markdown(p.session, dialect=p.flow.markdown_dialect, cancelled=cancelled)
        )
        with layout_stages(blocks) as stages:
            snapshot, phases[prefix + "_layout_ms"] = timed(
                lambda: blocks.layout_markdown(
                    document, p.resolver, page=p.page, style=p.style, flow=p.flow
                )
            )
        for key, value in stages.items():
            phases[prefix + "_" + key] = value
        phases[prefix + "_pagination_geometry_validation_ms"] = max(
            0, phases[prefix + "_layout_ms"] - sum(stages.values())
        )
        phases[prefix + "_total_ms"] = phases[prefix + "_parse_ms"] + phases[prefix + "_layout_ms"]
        assert snapshot.plotter_exportable
        return document, snapshot

    document, cold = layout_once("cold")
    phases["first_layout_ready_ms"] = (time.perf_counter() - began) * 1000
    _, warm = layout_once("warm")
    assert cold.pages == warm.pages
    before = {f.occurrence_id: f.asset_id for f in warm.fragments}
    position = p.session.source.index("12.50")
    p.session.apply(position, position + 1, "2")
    _, edited = layout_once("local_edit_full")
    unchanged = set(before) & {f.occurrence_id for f in edited.fragments}
    assert all(
        before[f.occurrence_id] == f.asset_id
        for f in edited.fragments
        if f.occurrence_id in unchanged
    )
    assert p.session.undo()
    _, restored = layout_once("undo_full")
    assert restored.pages == warm.pages
    plan, phases["plot_plan_ms"] = timed(lambda: plan_from_snapshot(restored))
    routing = [0.0]
    routes = []
    original = export.route_page

    def measured(*args, **kwargs):
        route, elapsed = timed(lambda: original(*args, **kwargs))
        routing[0] += elapsed
        assert route.after_mm <= route.before_mm + 1e-7
        routes.append({"before_mm": route.before_mm, "after_mm": route.after_mm})
        return route

    export.route_page = measured
    try:
        _, phases["machine_export_total_ms"] = timed(
            lambda: export.export_plan(plan, output / "machine", optimize=True)
        )
    finally:
        export.route_page = original
    phases["routing_ms"] = routing[0]
    phases["machine_serialization_write_ms"] = max(
        0, phases["machine_export_total_ms"] - routing[0]
    )
    phases["raster_render_ms"] = phases["png_encode_write_ms"] = 0.0
    previews = output / "preview"
    previews.mkdir()
    for i in range(len(restored.pages)):
        image, elapsed = timed(lambda i=i: page_png(restored, i, dpi=144))
        phases["raster_render_ms"] += elapsed
        _, elapsed = timed(lambda image=image, i=i: image.save(previews / f"page-{i + 1:03d}.png"))
        phases["png_encode_write_ms"] += elapsed
        image.close()
    svgs = sorted((output / "machine").glob("page-*.svg"))
    report = {
        "phases_ms": phases,
        "peak_rss_mb": rss_mb(),
        "pages": len(restored.pages),
        "scalars": len(p.session.source),
        "nodes": sum(1 for n in document.nodes for _ in n.walk()),
        "fragments": len(restored.fragments),
        "paths": sum(len(page.strokes) for page in plan.pages),
        "points": sum(len(stroke.points) for page in plan.pages for stroke in page.strokes),
        "svg_bytes": sum(f.stat().st_size for f in svgs),
        "svg_sha256": [sha256(f.read_bytes()).hexdigest() for f in svgs],
        "routes": routes,
        "unchanged_occurrences_after_edit": len(unchanged),
        "rss_scope": "Process high-water including imports, four snapshots and exports; platform ru_maxrss",
    }
    dump(output / "sample.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--hardware-json",
        type=Path,
        help="optional independently recorded CPU/memory when sandbox blocks sysctl",
    )
    parser.add_argument(
        "--glyph-project",
        type=Path,
        help="optional native project providing real numeric glyphs; outputs contain private samples",
    )
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.output)
        return
    if args.repeats < 3:
        parser.error("Use at least three independent observations per size")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "inputs"
    inputs.mkdir()
    prepare(inputs, args.glyph_project)
    cpu = (
        subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if sys.platform == "darwin"
        else platform.processor()
    )
    memory = (
        subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False
        ).stdout.strip()
        if sys.platform == "darwin"
        else None
    )
    environment = {
        "platform": platform.platform(),
        "python": sys.version,
        "cpu": cpu,
        "cpu_count": os.cpu_count(),
        "physical_memory_bytes": int(memory) if memory else None,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ["inkstruct", "numpy", "Pillow", "markdown-it-py", "PySide6"]
        },
        "source_sha256": {
            str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
            for d in ["document", "assets", "layout", "math", "scene", "plotter", "renderers"]
            for p in sorted((ROOT / "src/inkstruct" / d).glob("*.py"))
        },
        "benchmark_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "versions": {
            module: {
                key: value
                for key, value in vars(importlib.import_module("inkstruct." + module)).items()
                if isinstance(value, str) and (key.endswith("VERSION") or key == "SCHEMA")
            }
            for module in (
                "document.markdown",
                "document.package",
                "document.editing",
                "layout.template_fields",
                "layout.blocks",
                "math.schema",
                "math.handwritten",
                "plotter.export",
                "document.obsidian",
                "assets.resolver",
            )
        },
    }
    if args.hardware_json:
        hardware = json.loads(args.hardware_json.read_text())
        if not hardware.get("cpu") or not isinstance(hardware.get("physical_memory_bytes"), int):
            raise ValueError("Hardware record must include CPU and memory bytes")
        environment.update({key: hardware[key] for key in ("cpu", "physical_memory_bytes")})
        environment["hardware_record"] = hardware
    dump(output / "environment.json", environment)
    results = {}
    for pages in (1, 10, 50):
        case = output / f"{pages:02d}-pages"
        case.mkdir()
        observations = []
        for index in range(args.repeats):
            destination = case / f"run-{index + 1:02d}"
            destination.mkdir()
            started = time.perf_counter()
            with (destination / "process.log").open("w") as log:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--worker",
                        str(inputs / f"{pages:02d}-pages.inkdoc"),
                        "--output",
                        str(destination),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                    check=False,
                )
            if completed.returncode:
                raise RuntimeError(f"Benchmark failed: {destination}/process.log")
            sample = json.loads((destination / "sample.json").read_text())
            sample["phases_ms"]["process_wall_ms"] = (time.perf_counter() - started) * 1000
            assert sample["pages"] == pages
            if observations:
                assert sample["svg_sha256"] == observations[0]["svg_sha256"]
            observations.append(sample)
            dump(destination / "sample.json", sample)
            # Keep the first complete export, all raw timings and all content hashes.
            if index:
                shutil.rmtree(destination / "machine")
                shutil.rmtree(destination / "preview")
            print(
                f"PASS {pages} pages {index + 1}/{args.repeats}: layout={sample['phases_ms']['warm_total_ms']:.1f} ms export={sample['phases_ms']['machine_export_total_ms']:.1f} ms RSS={sample['peak_rss_mb']:.1f} MB",
                flush=True,
            )

        def quantiles(values):
            return {
                "p50": statistics.median(values),
                "p95_nearest_rank": sorted(values)[math.ceil(0.95 * len(values)) - 1],
                "min": min(values),
                "max": max(values),
            }

        results[str(pages)] = {
            "observations": args.repeats,
            "phases_ms": {
                key: quantiles([s["phases_ms"][key] for s in observations])
                for key in observations[0]["phases_ms"]
            },
            "peak_rss_mb": quantiles([s["peak_rss_mb"] for s in observations]),
            "scale": {
                key: observations[0][key]
                for key in [
                    "pages",
                    "scalars",
                    "nodes",
                    "fragments",
                    "paths",
                    "points",
                    "svg_bytes",
                ]
            },
        }
        dump(
            output / "summary.json",
            {
                "cases": results,
                "method": "Fresh process each observation; warm/full and local-edit/full layout with cancellation enabled; OS caches not flushed. P95 nearest rank, small sample. Fixed numeric mixed documents; no claim of dense Chinese workloads or interactive frame performance.",
                "glyphs": "embedded project numeric samples"
                if args.glyph_project
                else "builtin numeric",
            },
        )


if __name__ == "__main__":
    main()
