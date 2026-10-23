"""Paired export and Qt page-load observations on fixed embedded projects."""

import argparse
import json
import math
import statistics
import tempfile
import threading
import time
from hashlib import sha256
from pathlib import Path

from PySide6 import QtWidgets

from inkstruct.document.package import load_package
from inkstruct.editor.app import PageCanvas
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.editor.mixed import build_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan


def elapsed(callback, *args, **kwargs):
    start = time.perf_counter()
    result = callback(*args, **kwargs)
    return (time.perf_counter() - start) * 1000, result


def digests(directory):
    return {p.name: sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 3:
        parser.error("Choose a new output file and at least three observations")
    app = QtWidgets.QApplication([])
    records = []
    for project in args.projects:
        original_hash = sha256(project.read_bytes()).hexdigest()
        p = load_package(project)
        snapshot = build_markdown(
            session=p.session,
            revision=1,
            resolver=p.resolver,
            run="",
            symbols="",
            page=p.page,
            style=p.style,
            flow=p.flow,
            cancelled=threading.Event(),
        )["snapshot"]
        plan = plan_from_snapshot(snapshot)
        cache = MarkdownBuildCache().routes
        canvas = PageCanvas()
        observations = []
        with tempfile.TemporaryDirectory(prefix="inkstruct-export-cache-") as temporary:
            root = Path(temporary)
            # Warm decisions once; each timed export still creates all SVG and JSON files.
            export_plan(plan, root / "seed", optimize=True, route_cache=cache)
            expected = digests(root / "seed")
            for index in range(args.repeats):
                full_ms, _ = elapsed(export_plan, plan, root / f"full-{index}", optimize=True)
                hit_ms, _ = elapsed(
                    export_plan, plan, root / f"hit-{index}", optimize=True, route_cache=cache
                )
                assert digests(root / f"full-{index}") == expected
                assert digests(root / f"hit-{index}") == expected
                canvas.preview_cache.clear()
                load_ms, _ = elapsed(canvas.load_page, snapshot, 0)
                renderer = canvas.renderer
                hit_load_ms, _ = elapsed(canvas.load_page, snapshot, 0)
                assert canvas.renderer is renderer
                # Separate actual offscreen painting from parsed-SVG reuse.
                app.processEvents()
                paint_ms, image = elapsed(canvas.grab)
                assert not image.isNull()
                observations.append(
                    {
                        "uncached_export_ms": full_ms,
                        "cached_export_ms": hit_ms,
                        "first_page_load_ms": load_ms,
                        "cached_page_load_ms": hit_load_ms,
                        "offscreen_page_grab_ms": paint_ms,
                    }
                )
        assert sha256(project.read_bytes()).hexdigest() == original_hash
        record = {
            "project": str(project),
            "project_sha256": original_hash,
            "pages": len(plan.pages),
            "samples": observations,
            "files": expected,
            "route_cache": cache.statistics(),
            "preview_cache": canvas.preview_cache.statistics(),
            "summary": {
                key: {
                    "p50": statistics.median(v[key] for v in observations),
                    "p95_nearest_rank": sorted(v[key] for v in observations)[
                        math.ceil(0.95 * len(observations)) - 1
                    ],
                }
                for key in observations[0]
            },
        }
        records.append(record)
        print(json.dumps({"pages": record["pages"], **record["summary"]}), flush=True)
        canvas.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "scope": "Already loaded fixed projects; five paired uncached and warmed-route exports, including SVG/manifest serialization and writes to new temporary directories, excluding initial layout/plan conversion and OS fsync. Every SVG and JSON byte hash is equal. Qt page load covers serialization and SVG parsing or cache lookup; offscreen painting measured separately. No visible-frame or physical plotter claim.",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
