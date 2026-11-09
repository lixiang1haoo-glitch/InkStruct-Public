"""Deterministic pen-up routing; drawing points and stroke segmentation stay intact."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .schema import PathPoints, Point


@dataclass(frozen=True)
class Route:
    paths: tuple[PathPoints, ...]
    source_indices: tuple[int, ...]
    reversed_paths: tuple[bool, ...]
    before_mm: float
    after_mm: float

    @property
    def saved_percent(self) -> float:
        return 100 * (self.before_mm - self.after_mm) / self.before_mm if self.before_mm else 0.0


def travel_distance(paths: tuple[PathPoints, ...], start: Point = (0.0, 0.0)) -> float:
    """Distance from the page origin to first stroke and between strokes; no return home."""
    total = 0.0
    for path in paths:
        total += math.dist(start, path[0])
        start = path[-1]
    return total


def _greedy(paths, allow_reverse, start, order=None):
    # Exact nearest endpoint within each block. Bound work for very large tables.
    # Typical small tables are one block; blocks retain input order above 512 paths.
    indices = list(range(len(paths))) if order is None else order
    order = []
    current = start
    for offset in range(0, len(paths), 512):
        remaining = set(indices[offset : offset + 512])
        while remaining:
            candidates = ((math.dist(current, paths[i][0]), i, False) for i in remaining)
            best = min(candidates)
            if allow_reverse:
                best = min(
                    best, min((math.dist(current, paths[i][-1]), i, True) for i in remaining)
                )
            _, i, reversed_path = best
            order.append((i, reversed_path))
            current = paths[i][0] if reversed_path else paths[i][-1]
            remaining.remove(i)
    return order


def _orient(paths, order, start):
    """Dynamic program: optimal forward/reverse choices for a fixed path order."""
    if not order:
        return []
    previous = [0.0, 0.0]
    parents = []
    for position, index in enumerate(order):
        costs, links = [], []
        for reverse in (False, True):
            entry = paths[index][-1] if reverse else paths[index][0]
            if not position:
                costs.append(math.dist(start, entry))
                links.append(0)
                continue
            prior = paths[order[position - 1]]
            candidates = [
                (previous[r] + math.dist(prior[0] if r else prior[-1], entry), r) for r in (0, 1)
            ]
            cost, link = min(candidates)
            costs.append(cost)
            links.append(link)
        parents.append(links)
        previous = costs
    state = min(range(2), key=lambda r: (previous[r], r))
    result = []
    for position in range(len(order) - 1, -1, -1):
        result.append((order[position], bool(state)))
        state = parents[position][state]
    return list(reversed(result))


def _cost(paths, order, start):
    total = 0.0
    for i, rev in order:
        total += math.dist(start, paths[i][-1] if rev else paths[i][0])
        start = paths[i][0] if rev else paths[i][-1]
    return total


def _two_opt(paths, order, start, budget=1_000_000):
    """Reverse route intervals and all their stroke directions.

    Internal pen-up edges keep the same lengths, so only the two boundary
    edges need checking. Includes the first stroke and the free final endpoint.
    Fixed evaluation limits preserve determinism and bound long-table work.
    """
    nodes = [2 * i + int(rev) for i, rev in order]
    endpoints = [point for path in paths for point in (path[0], path[-1])]
    n = len(nodes)
    span = n if n <= 512 else 128
    for _ in range(4):
        improved = False
        for i in range(n):
            prior = endpoints[nodes[i - 1] ^ 1] if i else start
            entry = endpoints[nodes[i]]
            old_first = math.dist(prior, entry)
            best_gain, best_j = -1e-9, None
            for j in range(i, min(n, i + span)):
                if budget <= 0:
                    return [(node // 2, bool(node % 2)) for node in nodes]
                budget -= 1
                exit_point = endpoints[nodes[j] ^ 1]
                gain = math.dist(prior, exit_point) - old_first
                if j + 1 < n:
                    following = endpoints[nodes[j + 1]]
                    gain += math.dist(entry, following) - math.dist(exit_point, following)
                if gain < best_gain:
                    best_gain, best_j = gain, j
            if best_j is not None:
                nodes[i : best_j + 1] = [node ^ 1 for node in reversed(nodes[i : best_j + 1])]
                improved = True
        if not improved:
            break
    return [(node // 2, bool(node % 2)) for node in nodes]


def optimize_paths(
    paths: tuple[PathPoints, ...], *, allow_reverse: bool = True, start: Point = (0.0, 0.0)
) -> Route:
    """Heuristic order search, guaranteed not to exceed original pen-up distance.

    Reversal preserves the drawn polyline, but can change physical pen dynamics.
    No stroke is joined, split, simplified, translated or resampled.
    """
    if len(start) != 2 or not all(math.isfinite(v) for v in start):
        raise ValueError("无效的空行程起点")
    for path in paths:
        if len(path) < 2 or not all(math.isfinite(v) for p in path for v in p):
            raise ValueError("路径需包含至少两个有限坐标点")
    paths = tuple(tuple(path) for path in paths)
    original = [(i, False) for i in range(len(paths))]
    best = original
    before = travel_distance(paths, start)
    best_cost = before
    forward = _greedy(paths, False, start)
    candidates = [forward]
    if allow_reverse:
        reverse_greedy = _greedy(paths, True, start)
        candidates.extend(
            _orient(paths, [i for i, _ in order], start)
            for order in (original, forward, reverse_greedy)
        )
    for candidate in candidates:
        cost = _cost(paths, candidate, start)
        if cost < best_cost - 1e-9:
            best, best_cost = candidate, cost
    if allow_reverse and paths:
        # Keep every v1 candidate as a fallback. Add spatial sweeps to escape
        # nearest-neighbour traps and source-order block boundaries.
        seeds = [best]
        centers = [((p[0][0] + p[-1][0]) / 2, (p[0][1] + p[-1][1]) / 2) for p in paths]
        for axis in (0, 1):
            sweep = sorted(
                range(len(paths)), key=lambda i: (centers[i][axis], centers[i][1 - axis], i)
            )
            seeds.append(_orient(paths, sweep, start))
            if len(paths) > 512:
                spatial = _greedy(paths, True, start, sweep)
                seeds.append(_orient(paths, [i for i, _ in spatial], start))
        # Refine three distinct initial routes. For large jobs prefer the
        # cheapest seeds; each search is independently bounded.
        seeds = list(dict.fromkeys(tuple(seed) for seed in seeds))
        seeds = sorted(seeds, key=lambda order: _cost(paths, order, start))[:3]
        for seed in seeds:
            candidate = seed
            for _ in range(2):
                candidate = _two_opt(paths, candidate, start)
                candidate = _orient(paths, [i for i, _ in candidate], start)
            cost = _cost(paths, candidate, start)
            if cost < best_cost - 1e-9:
                best, best_cost = candidate, cost
    return Route(
        tuple(paths[i][::-1] if rev else paths[i] for i, rev in best),
        tuple(i for i, _ in best),
        tuple(rev for _, rev in best),
        before,
        best_cost,
    )
