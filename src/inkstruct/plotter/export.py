from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from itertools import groupby
from pathlib import Path

from .routing import optimize_paths, travel_distance
from .schema import PlotPage, PlotPlan, Point
from .svg import page_svg

ROUTING_VERSION = "routing_v2"
COST_MODEL = "euclidean_pen_up_from_start_no_return"
ROUTE_CACHE_VERSION = "endpoint-order-cache-v1"


def route_key(page, optimize, start):
    return (ROUTE_CACHE_VERSION, ROUTING_VERSION, COST_MODEL, bool(optimize), tuple(start),
            tuple((s.points[0], s.points[-1], s.execution_domain) for s in page.strokes))


@dataclass(frozen=True)
class RouteOrder:
    """Cache decisions only; geometry and provenance always come from the caller."""

    indices: tuple[int, ...]
    reversed_paths: tuple[bool, ...]


@dataclass(frozen=True)
class RoutedPage:
    page: PlotPage
    source_indices: tuple[int, ...]
    reversed_paths: tuple[bool, ...]
    before_mm: float
    after_mm: float
    start: Point


def route_page(
    page: PlotPage,
    *,
    optimize: bool = False,
    start: Point = (0.0, 0.0),
    cache=None,
) -> RoutedPage:
    if len(start) != 2 or not all(math.isfinite(v) for v in start):
        raise ValueError("Plot start must have two finite coordinates")
    paths = tuple(s.points for s in page.strokes)
    key = route_key(page, optimize, start) if cache is not None else None
    cached = cache.get(key) if cache is not None else None
    before = travel_distance(paths, start)
    indices, reversals = [], []
    current = start
    if cached is not None:
        indices, reversals = list(cached.indices), list(cached.reversed_paths)
    else:
        for _, members in groupby(
            enumerate(page.strokes), key=lambda pair: pair[1].execution_domain
        ):
            group = list(members)
            if optimize:
                route = optimize_paths(tuple(s.points for _, s in group), start=current)
                indices.extend(group[i][0] for i in route.source_indices)
                reversals.extend(route.reversed_paths)
                current = route.paths[-1][-1]
            else:
                indices.extend(i for i, _ in group)
                reversals.extend(False for _ in group)
    strokes = tuple(
        replace(page.strokes[i], points=page.strokes[i].points[::-1]) if rev else page.strokes[i]
        for i, rev in zip(indices, reversals, strict=True)
    )
    after = travel_distance(tuple(s.points for s in strokes), start)
    # Local improvements can worsen the entry into the next constrained domain.
    # Preserve the entire feasible baseline in that case, including directions.
    if after > before:
        strokes = page.strokes
        indices = list(range(len(strokes)))
        reversals = [False] * len(strokes)
        after = before
    if cache is not None and cached is None:
        cache.put((key,), RouteOrder(tuple(indices), tuple(reversals)), 256 + len(paths) * 512)
    return RoutedPage(
        replace(page, strokes=strokes), tuple(indices), tuple(reversals), before, after, start
    )


def export_plan(
    plan: PlotPlan,
    output: Path,
    *,
    optimize: bool = False,
    start: Point = (0.0, 0.0),
    export_scope: dict | None = None,
    route_cache=None,
    page_indices=None,
    routing=None,
    control=None,
    progress=None,
) -> Path:
    """Atomically publish a new directory with one machine SVG per page and provenance."""
    output = Path(output)
    if page_indices is not None and (not page_indices or tuple(sorted(set(page_indices))) != tuple(page_indices)
                                    or any(type(i) is not int or not 0 <= i < len(plan.pages) for i in page_indices)):
        raise ValueError('Invalid export page selection')
    if output.exists():
        raise FileExistsError(f"Use a new output directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".inkstruct-plotter-", dir=output.parent))
    try:
        reports = []
        pages = tuple(p for p in plan.pages if page_indices is None or p.index in page_indices)
        if routing is None:
            routes = (route_page(p, optimize=optimize, start=start, cache=route_cache) for p in pages)
        else:
            routes = routing.routes(pages, optimize=optimize, start=start, cache=route_cache,
                                    control=control, progress=progress)
        for number, route in enumerate(routes, 1):
            if control is not None:
                control.check()
            page = route.page
            filename = f"page-{page.index + 1:03d}.svg"
            (staging / filename).write_text(page_svg(route.page), encoding="utf-8")
            reports.append(
                {
                    "page_index": page.index,
                    "file": filename,
                    "start_mm": start,
                    "before_mm": route.before_mm,
                    "after_mm": route.after_mm,
                    "strokes": [
                        {
                            "stroke_id": stroke.stroke_id,
                            "source_stroke_id": stroke.source_stroke_id,
                            "occurrence_id": stroke.occurrence_id,
                            "execution_domain": stroke.execution_domain,
                            "source_index": i,
                            "reversed": rev,
                        }
                        for stroke, i, rev in zip(
                            route.page.strokes,
                            route.source_indices,
                            route.reversed_paths,
                            strict=True,
                        )
                    ],
                }
            )
            if progress is not None:
                progress("write", number, len(pages))
        manifest = {
            "schema_version": "inkstruct_plot_export_v1",
            "document_id": plan.document_id,
            "snapshot_id": plan.snapshot_id,
            "optimized": optimize,
            "allow_reverse": optimize,
            "routing_version": ROUTING_VERSION,
            "cost_model": COST_MODEL,
            "pages": reports,
        }
        if export_scope is not None:
            manifest["export_scope"] = export_scope
        if export_scope and export_scope.get("forced"):
            (staging / "issues.json").write_text(
                json.dumps(export_scope, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            lines = ["强制 SVG 导出问题清单", export_scope["notice"],
                     "导出页码：" + ", ".join(map(str, export_scope.get("page_numbers", ())))]
            for d in export_scope.get("diagnostics", ()):
                span = d.get("span", {})
                lines.append(f"[{d.get('severity', '')}] {d.get('code', '')}: {d.get('message', '')} "
                             f"(源码 {span.get('start', 0)}–{span.get('end', 0)})")
            for item in export_scope.get("omitted_strokes", ()):
                lines.append(f"第 {item['page_index']+1} 页 跳过笔画 {item.get('occurrence_id', '')}: {item['reason']}")
            for item in export_scope.get("omitted_images", ()):
                lines.append(f"第 {item['page_index']+1} 页 跳过图片: {item['source']}")
            (staging / "issues.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")
        (staging / "plotter.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        for attempt in range(6):
            if control is not None:
                control.check()
            if output.exists():
                raise FileExistsError(f"Output appeared during export: {output}")
            try:
                if control is None:
                    staging.rename(output)
                else:
                    control.publish(staging, output)
                break
            except PermissionError as error:
                # Windows can briefly deny renaming a newly populated directory.
                # Retry only this publication step; never overwrite a destination.
                if (sys.platform != 'win32' or getattr(error, 'winerror', None) not in (5, 32)
                        or attempt == 5):
                    raise
                time.sleep(0.02 * 2 ** attempt)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output
