"""Routing cache must reuse decisions, never stale geometry, provenance or export identity."""

import json
from dataclasses import replace

import pytest

from inkstruct.cache import BoundedCache
from inkstruct.plotter import export
from inkstruct.plotter.schema import PlotPage, PlotPlan, PlotStroke
from inkstruct.plotter.svg import page_svg


def page():
    points = [
        ((80, 80), (81, 81)),
        ((10, 10), (20, 10)),
        ((50, 20), (40, 20)),
        ((15, 80), (10, 90)),
    ]
    return PlotPage(
        0,
        100,
        100,
        tuple(
            PlotStroke(
                f"s{i}",
                p,
                occurrence_id=f"o{i}",
                source_stroke_id=f"asset:{i}",
                execution_domain="body" if i < 3 else "note",
            )
            for i, p in enumerate(points)
        ),
    )


def cache():
    return BoundedCache(max_entries=4, max_weight=1000000)


def test_hit_skips_search_and_rebuilds_from_current_geometry_and_provenance(monkeypatch):
    original = page()
    c = cache()
    first = export.route_page(original, optimize=True, cache=c)
    modified = replace(
        original,
        index=2,
        width_mm=110,
        strokes=tuple(
            replace(
                s,
                stroke_id=s.stroke_id + "-new",
                source_stroke_id="new:" + s.source_stroke_id,
                occurrence_id=s.occurrence_id + "-new",
                width_mm=0.5,
                points=(s.points[0], (30, 30), s.points[-1]),
            )
            for s in original.strokes
        ),
    )
    expected = export.route_page(modified, optimize=True)

    def forbidden(*a, **kw):
        raise AssertionError("route cache failed to bypass search")

    monkeypatch.setattr(export, "optimize_paths", forbidden)
    actual = export.route_page(modified, optimize=True, cache=c)
    assert actual == expected and c.statistics()["hits"] == 1
    assert page_svg(actual.page) != page_svg(first.page)
    assert actual.source_indices == first.source_indices
    assert all(s.stroke_id.endswith("-new") and s.width_mm == 0.5 for s in actual.page.strokes)
    assert all((30, 30) in s.points for s in actual.page.strokes)
    assert page() == original


@pytest.mark.parametrize(
    "change", ["start", "endpoint", "source_order", "domain", "optimize", "version", "cost_model"]
)
def test_routing_inputs_invalidate_and_match_uncached(change, monkeypatch):
    p = page()
    c = cache()
    export.route_page(p, optimize=True, cache=c)
    start = (0.0, 0.0)
    optimize = True
    if change == "start":
        start = (90.0, 90.0)
    elif change == "endpoint":
        p = replace(p, strokes=(replace(p.strokes[0], points=((79, 80), (81, 81))), *p.strokes[1:]))
    elif change == "source_order":
        p = replace(p, strokes=(p.strokes[1], p.strokes[0], *p.strokes[2:]))
    elif change == "domain":
        p = replace(p, strokes=tuple(replace(s, execution_domain="all") for s in p.strokes))
    elif change == "optimize":
        optimize = False
    elif change == "version":
        monkeypatch.setattr(export, "ROUTING_VERSION", "new-test-version")
    else:
        monkeypatch.setattr(export, "COST_MODEL", "new-test-cost-model")
    expected = export.route_page(p, optimize=optimize, start=start)
    actual = export.route_page(p, optimize=optimize, start=start, cache=c)
    assert actual == expected and c.statistics()["hits"] == 0
    assert actual.after_mm <= actual.before_mm


def test_export_recreates_manifest_and_preserves_new_directory_rule(tmp_path):
    c = cache()
    p = page()
    first = PlotPlan("doc-a", "snapshot-a", (p,))
    export.export_plan(first, tmp_path / "a", optimize=True, route_cache=c)
    second = PlotPlan("doc-b", "snapshot-b", (p,))
    scope = {"mode": "table", "table_id": "new-source"}
    export.export_plan(second, tmp_path / "b", optimize=True, export_scope=scope, route_cache=c)
    export.export_plan(second, tmp_path / "control", optimize=True, export_scope=scope)
    assert c.statistics()["hits"] == 1
    for file in (tmp_path / "control").iterdir():
        assert file.read_bytes() == (tmp_path / "b" / file.name).read_bytes()
    manifest = json.loads((tmp_path / "b/plotter.json").read_text())
    assert manifest["document_id"] == "doc-b" and manifest["snapshot_id"] == "snapshot-b"
    assert manifest["export_scope"] == scope and manifest["allow_reverse"]
    before = {f.name: f.read_bytes() for f in (tmp_path / "b").iterdir()}
    with pytest.raises(FileExistsError):
        export.export_plan(second, tmp_path / "b", optimize=True, route_cache=c)
    assert before == {f.name: f.read_bytes() for f in (tmp_path / "b").iterdir()}


def test_empty_page_and_invalid_start_do_not_bypass_validation():
    p = PlotPage(0, 100, 100, ())
    c = cache()
    assert export.route_page(p, optimize=True, cache=c) == export.route_page(p, optimize=True)
    assert export.route_page(p, optimize=True, cache=c).source_indices == ()
    with pytest.raises(ValueError):
        export.route_page(p, optimize=True, start=(float("nan"), 0), cache=c)


def test_evicted_route_recomputes_and_oversized_decisions_are_not_retained():
    c = BoundedCache(max_entries=1, max_weight=100000)
    p = page()
    first = export.route_page(p, optimize=True, cache=c)
    export.route_page(p, optimize=True, start=(10, 10), cache=c)
    assert export.route_page(p, optimize=True, cache=c) == first
    assert c.statistics()["hits"] == 0 and c.statistics()["evictions"] == 2
    small = BoundedCache(max_entries=1, max_weight=1)
    assert export.route_page(p, optimize=True, cache=small) == first
    assert small.statistics()["entries"] == 0 and small.statistics()["skipped"] == 1
