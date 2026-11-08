import itertools
import math
import random
import re
import xml.etree.ElementTree as ET
from collections import Counter

import pytest

from inkstruct.table_editor.app import EXAMPLE, main
from inkstruct.table_editor.core import compile_html, drawing_svg
from inkstruct.table_editor.routing import _orient, optimize_paths, travel_distance


def test_distance_includes_start_but_not_return():
    paths = (((3, 4), (6, 8)), ((9, 12), (100, 100)))
    assert travel_distance(paths) == 10
    assert travel_distance(paths, start=(3, 4)) == 5


def test_empty_single_and_stable_ties():
    assert optimize_paths(()).paths == ()
    assert optimize_paths(()).saved_percent == 0
    path = ((10, 0), (1, 0))
    assert optimize_paths((path,), allow_reverse=False).paths == (path,)
    route = optimize_paths((path,), allow_reverse=True)
    assert route.paths == (path[::-1],)
    assert route.after_mm == 1
    tied = (((1, 0), (1, 1)), ((1, 0), (1, 1)))
    assert optimize_paths(tied).source_indices == (0, 1)


def test_sorting_reduces_travel_without_reversing():
    paths = (((100, 0), (101, 0)), ((1, 0), (2, 0)))
    route = optimize_paths(paths, allow_reverse=False)
    assert route.source_indices == (1, 0)
    assert route.paths == paths[::-1]
    assert not any(route.reversed_paths)
    assert route.before_mm == 200
    assert route.after_mm == 99


def test_fixed_order_orientation_matches_exhaustive_search():
    paths = (((12, 4), (2, 7)), ((8, 2), (11, 0)), ((5, 9), (0, 0)))
    start = (4, 5)
    for order in itertools.permutations(range(3)):
        actual = _orient(paths, order, start)
        cost = travel_distance(tuple(paths[i][::-1] if r else paths[i] for i, r in actual), start)
        optimal = min(
            travel_distance(
                tuple(paths[i][::-1] if r else paths[i] for i, r in zip(order, rs)), start
            )
            for rs in itertools.product((False, True), repeat=3)
        )
        assert cost == pytest.approx(optimal)


@pytest.mark.parametrize("count", [2, 39, 90, 513])
def test_routes_preserve_every_stroke_and_never_increase_travel(count):
    rng = random.Random(count)
    paths = tuple(
        tuple((rng.random() * 210, rng.random() * 297) for _ in range(3)) for _ in range(count)
    )
    # Duplicate geometry must still be drawn exactly as many times as supplied.
    paths += (paths[0],)
    start = (20, 10)
    forward = optimize_paths(paths, allow_reverse=False, start=start)
    reverse = optimize_paths(paths, allow_reverse=True, start=start)
    assert reverse.after_mm <= forward.after_mm <= travel_distance(paths, start)
    assert Counter(forward.paths) == Counter(paths)
    for route in (forward, reverse):
        assert sorted(route.source_indices) == list(range(len(paths)))
        assert route.after_mm == pytest.approx(travel_distance(route.paths, start))
        for path, i, rev in zip(route.paths, route.source_indices, route.reversed_paths):
            assert path == (paths[i][::-1] if rev else paths[i])
        assert sum(
            math.dist(a, b) for p in route.paths for a, b in itertools.pairwise(p)
        ) == pytest.approx(sum(math.dist(a, b) for p in paths for a, b in itertools.pairwise(p)))
    assert reverse == optimize_paths(paths, allow_reverse=True, start=start)


@pytest.mark.parametrize(
    "paths,start",
    [((((0, 0),),), (0, 0)), ((((0, 0), (float("nan"), 1)),), (0, 0)), ((), (float("inf"), 0))],
)
def test_invalid_geometry_is_rejected(paths, start):
    with pytest.raises(ValueError):
        optimize_paths(paths, start=start)


def test_optimized_svg_preserves_strokes_and_machine_contract():
    drawing, baseline = compile_html(EXAMPLE)
    route = optimize_paths((*drawing.borders, *drawing.numbers), allow_reverse=True)
    optimized = ET.fromstring(drawing_svg(drawing, paths=route.paths))
    original = ET.fromstring(baseline)
    assert optimized.attrib == original.attrib
    assert len(optimized) == len(original) == 39
    canonical = lambda points: min(points, points[::-1])

    def geometry(root):
        result = []
        for element in root:
            assert element.tag == "{http://www.w3.org/2000/svg}path"
            assert set(re.findall("[A-Za-z]", element.attrib["d"])) == {"M", "L"}
            coords = tuple(float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", element.attrib["d"]))
            points = tuple(zip(coords[::2], coords[1::2]))
            result.append(canonical(points))
            assert {k: v for k, v in element.attrib.items() if k != "d"} == {
                k: v for k, v in original[0].attrib.items() if k != "d"
            }
        return Counter(result)

    assert geometry(optimized) == geometry(original)


def test_cli_optimization_and_reverse_guard(tmp_path, capsys):
    source, output = tmp_path / "table.html", tmp_path / "table.svg"
    source.write_text(EXAMPLE)
    assert main(["--input", str(source), "--output", str(output), "--optimize-paths"]) == 0
    assert "空行程" in capsys.readouterr().out
    drawing, _ = compile_html(EXAMPLE)
    route = optimize_paths((*drawing.borders, *drawing.numbers), allow_reverse=True)
    assert output.read_text() == drawing_svg(drawing, paths=route.paths)
    with pytest.raises(SystemExit) as error:
        main(["--allow-reverse"])
    assert error.value.code == 2


def test_two_opt_handles_origin_free_end_and_budget():
    from inkstruct.table_editor.routing import _two_opt

    paths = (((1, 0), (2, 0)), ((100, 0), (101, 0)), ((3, 0), (4, 0)))
    order = [(i, False) for i in range(3)]
    assert _two_opt(paths, order, (0, 0), budget=0) == order
    improved = _two_opt(paths, order, (0, 0))
    result = tuple(paths[i][::-1] if rev else paths[i] for i, rev in improved)
    assert travel_distance(result) < travel_distance(paths)
    assert sorted(i for i, _ in improved) == [0, 1, 2]
    # A final stroke has no outgoing cost, but its entry still matters.
    assert _two_opt((((10, 0), (1, 0)),), [(0, False)], (0, 0)) == [(0, True)]
    assert optimize_paths((((10, 0), (1, 0)),)).reversed_paths == (True,)


@pytest.mark.parametrize("count", [10, 80, 520])
def test_new_search_never_worse_than_old_candidates(count):
    from inkstruct.table_editor.routing import _cost, _greedy

    rng = random.Random(count)
    paths = tuple(
        tuple((rng.random() * 200, rng.random() * 280) for _ in range(3)) for _ in range(count)
    )
    start = (15, 9)
    original = [(i, False) for i in range(count)]
    forward = _greedy(paths, False, start)
    reversed_greedy = _greedy(paths, True, start)
    old_candidates = [original, forward] + [
        _orient(paths, [i for i, _ in order], start)
        for order in (original, forward, reversed_greedy)
    ]
    old_cost = min(_cost(paths, order, start) for order in old_candidates)
    result = optimize_paths(paths, start=start)
    assert result.after_mm <= old_cost + 1e-9
    assert result.after_mm < old_cost - 1e-4
    assert sorted(result.source_indices) == list(range(count))
