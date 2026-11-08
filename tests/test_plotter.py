import json
import random
import re
import sys
from dataclasses import asdict, replace
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from inkstruct.document.schema import Diagnostic, PageProfile, SourceSpan
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan, route_page
from inkstruct.plotter.routing import optimize_paths
from inkstruct.plotter.schema import PlotPage, PlotPlan, PlotStroke
from inkstruct.plotter.svg import page_svg
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp
from inkstruct.table_editor.core import compile_html


def snapshot(ops=None):
    ops = ops if ops is not None else (PaintOp("occ-1", ((10, 10), (11, 12)), 0.3),)
    return LayoutSnapshot(
        "snapshot", "key", "doc", 1, PageProfile(), (Page(0, (), ops),), (), "resources", "fixture"
    )


@pytest.mark.parametrize("name", ["numeric", "merged"])
def test_frozen_table_output_and_routing_are_identical(name):
    fixture = Path(__file__).parent / "fixtures" / "table_output" / name
    drawing, svg = compile_html(fixture.with_suffix(".html").read_text())
    assert svg == fixture.with_suffix(".svg").read_text()
    route = optimize_paths((*drawing.borders, *drawing.numbers))
    assert json.loads(json.dumps(asdict(route))) == json.loads(
        fixture.with_suffix(".route.json").read_text()
    )


@pytest.mark.parametrize(
    "points", [((1, 1),), ((1, 1), (1, 1)), ((1, 1), (1.00000001, 1)), ((1, 1), (float("nan"), 1))]
)
def test_unwriteable_strokes_are_blocked(points):
    with pytest.raises(ValueError):
        plan_from_snapshot(snapshot((PaintOp("problem", points, 0.3),)))


def test_adapter_blocks_errors_unknown_ops_and_colour():
    with pytest.raises(ValueError, match="document errors"):
        plan_from_snapshot(
            replace(
                snapshot(),
                diagnostics=(Diagnostic("missing", "Missing resource", SourceSpan(0, 1)),),
            )
        )
    with pytest.raises(ValueError, match="Unsupported"):
        plan_from_snapshot(snapshot((object(),)))
    with pytest.raises(ValueError, match="colour"):
        plan_from_snapshot(snapshot((PaintOp("red", ((10, 10), (20, 10)), 0.3, "red"),)))
    with pytest.raises(ValueError, match="bounds"):
        plan_from_snapshot(snapshot((PaintOp("outside", ((0, 0), (1, 1)), 0.3),)))


def test_machine_svg_uses_only_paths_and_preserves_snapshot():
    original = snapshot()
    plan = plan_from_snapshot(original)
    page = plan.pages[0]
    assert original == snapshot()
    root = ET.fromstring(page_svg(page))
    assert len(root) == 1
    assert root[0].tag == "{http://www.w3.org/2000/svg}path"
    assert re.findall(r"[A-Za-z]", root[0].get("d")) == ["M", "L"]
    assert root[0].get("d") == "M 10.000000 10.000000 L 11.000000 12.000000"
    assert page.strokes[0].occurrence_id == "occ-1"


def test_constrained_routing_keeps_domains_provenance_and_non_regression():
    rng = random.Random(412)
    for trial in range(12):
        strokes = tuple(
            PlotStroke(
                f"stroke-{i}",
                tuple((rng.uniform(1, 200), rng.uniform(1, 290)) for _ in range(3)),
                occurrence_id=f"occ-{i}",
                source_stroke_id=f"asset-{i}",
                execution_domain=("first", "second", "first")[i // 5],
            )
            for i in range(15)
        )
        page = PlotPage(0, 210, 297, strokes)
        original = route_page(page)
        assert original.page == page
        route = route_page(page, optimize=True)
        assert route.after_mm <= original.after_mm
        assert tuple(s.execution_domain for s in route.page.strokes) == tuple(
            s.execution_domain for s in strokes
        )
        for start in range(0, 15, 5):
            assert set(route.source_indices[start : start + 5]) == set(range(start, start + 5))
        for s, index, rev in zip(route.page.strokes, route.source_indices, route.reversed_paths):
            assert (
                s == replace(strokes[index], points=strokes[index].points[::-1])
                if rev
                else (s == strokes[index])
            )


def test_atomic_multi_page_export_with_sidecar(tmp_path):
    first = PlotPage(0, 210, 297, (PlotStroke("s", ((20, 20), (1, 1))),))
    plan = PlotPlan("doc", "snapshot", (first, replace(first, index=1)))
    output = tmp_path / "export"
    export_plan(plan, output, optimize=True)
    manifest = json.loads((output / "plotter.json").read_text())
    assert manifest["allow_reverse"] and manifest["optimized"]
    assert [p["file"] for p in manifest["pages"]] == ["page-001.svg", "page-002.svg"]
    assert all(p["strokes"][0]["reversed"] for p in manifest["pages"])
    assert all(p["after_mm"] < p["before_mm"] for p in manifest["pages"])
    with pytest.raises(FileExistsError):
        export_plan(plan, output)
    assert len(list(output.iterdir())) == 3


def test_failed_export_leaves_no_partial_directory(tmp_path, monkeypatch):
    import inkstruct.plotter.export as exporter

    def fail(page):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(exporter, "page_svg", fail)
    with pytest.raises(OSError):
        export_plan(plan_from_snapshot(snapshot()), tmp_path / "out")
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows directory publication')
def test_export_recovers_from_transient_windows_directory_lock(tmp_path, monkeypatch):
    from pathlib import Path
    original = Path.rename
    locked = True

    def rename(path, target):
        nonlocal locked
        if locked:
            locked = False
            error = PermissionError('temporary directory lock')
            error.winerror = 5
            raise error
        return original(path, target)

    monkeypatch.setattr(Path, 'rename', rename)
    output = tmp_path / 'export'
    export_plan(plan_from_snapshot(snapshot()), output)
    assert (output / 'plotter.json').is_file()
    assert (output / 'page-001.svg').is_file()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows directory publication')
def test_export_retry_preserves_destination_created_by_another_writer(tmp_path, monkeypatch):
    from pathlib import Path
    output = tmp_path / 'export'

    def rename(path, target):
        output.mkdir()
        (output / 'existing.txt').write_text('keep', encoding='utf-8')
        error = PermissionError('temporary directory lock')
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, 'rename', rename)
    with pytest.raises(FileExistsError):
        export_plan(plan_from_snapshot(snapshot()), output)
    assert (output / 'existing.txt').read_text(encoding='utf-8') == 'keep'
    assert list(tmp_path.iterdir()) == [output]


def test_mutable_input_detached_and_invalid_page_ids_rejected():
    points = [[1, 1], [2, 2]]
    stroke = PlotStroke("test", points)
    points[0][0] = 99
    assert stroke.points[0] == (1, 1)
    with pytest.raises(ValueError, match="Duplicate"):
        PlotPage(0, 210, 297, (stroke, stroke))
    with pytest.raises(ValueError, match="order"):
        PlotPlan("doc", "snapshot", (PlotPage(1, 210, 297, (stroke,)),))
