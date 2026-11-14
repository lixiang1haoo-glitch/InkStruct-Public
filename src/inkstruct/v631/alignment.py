"""Experimental ordered pen-down alignment with independently reusable parts."""

from dataclasses import dataclass
from itertools import pairwise

import numpy as np


MIN_COVERAGE = .70
MIN_MARGIN = .045
MAX_STROKES = 32


def stations(points, count):
    arc = np.r_[0., np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
    step = np.linspace(0, arc[-1], count)
    xy = np.column_stack([np.interp(step, arc, points[:, i]) for i in (0, 1)])
    tangent = np.gradient(xy, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
    return xy, tangent, float(arc[-1])


def normalized(traces, extent=None):
    ink = np.concatenate(traces if extent is None else extent)
    lo, hi = ink.min(axis=0), ink.max(axis=0)
    scale = max(hi-lo)
    if scale <= 1e-8:
        raise ValueError("没有足够的墨迹范围")
    return [(p-(lo+hi)/2)*.85/scale+.5 for p in traces]


def match(references, observed):
    """Measure ordered spatial and directional coverage without producing cut points."""
    ref = np.concatenate([r[0] for r in references])
    tangents = np.concatenate([r[1] for r in references])
    points, directions, length = observed
    distance = np.linalg.norm(ref[:, None]-points, axis=2)
    tolerance = np.repeat([.065 + .10 * min(r[2], .8) for r in references], 18)
    hits = (distance <= tolerance[:, None]) & (tangents @ directions.T >= .25)
    n, m = hits.shape
    scores = np.zeros((n+1, m+1))
    matched = np.zeros((n+1, m+1), dtype=bool)
    for i in range(n):
        choice = np.where(hits[i], scores[i, :-1]+1-.35*distance[i]/tolerance[i], -1.)
        scores[i+1, 1:] = np.maximum(scores[i, 1:], np.maximum.accumulate(choice))
        matched[i+1, 1:] = hits[i] & (choice >= scores[i+1, 1:])
    covered = np.zeros(n, dtype=bool)
    i, j = n, m
    while i and j:
        if matched[i, j]:
            covered[i-1] = True
            i, j = i-1, j-1
        elif scores[i, j] == scores[i-1, j]:
            i -= 1
        else:
            j -= 1
    coverage = covered.reshape(-1, 18).mean(axis=1)
    endpoint = float(max(distance[0, 0], distance[-1, -1]))
    nominal = sum(r[2] for r in references) + sum(
        np.linalg.norm(a[0][-1]-b[0][0]) for a, b in pairwise(references)
    )
    ratio = float(length / max(nominal, 1e-9))
    distinct = True
    if len(references) == 2:
        # A shared portion of the two templates cannot alone prove that both
        # standard strokes were present in the captured segment.
        separation = np.linalg.norm(ref[:18, None]-ref[None, 18:], axis=2)
        same_direction = tangents[:18] @ tangents[18:].T >= .65
        shared = (separation < .072) & same_direction
        for unique, evidence in ((~shared.any(axis=1), covered[:18]),
                                 (~shared.any(axis=0), covered[18:])):
            if unique.sum() < 4 or evidence[unique].mean() < .55:
                distinct = False
    trusted = bool(min(coverage) >= MIN_COVERAGE and endpoint <= .19 and .48 <= ratio <= 1.67 and distinct)
    residual = 1-float(scores[n, m])/n+.75*endpoint
    return trusted, residual, tuple(float(c) for c in coverage)


@dataclass(frozen=True)
class Edge:
    slots: tuple[int, ...]
    raw: tuple[int, ...]
    cost: float
    trusted: bool = False
    coverage: tuple[float, ...] = ()


def best_path(n, m, edges, forbidden=None):
    cells = {(0, 0): (0., ())}
    for i in range(n+1):
        for j in range(m+1):
            if (i, j) not in cells:
                continue
            cost, path = cells[i, j]
            for edge in edges[i, j]:
                if edge == forbidden:
                    continue
                dest = (i+len(edge.slots), j+len(edge.raw))
                new = cost + edge.cost
                if dest not in cells or new < cells[dest][0]:
                    cells[dest] = (new, (*path, edge))
    return cells.get((n, m), (float("inf"), ()))


def align_groups(sample, graph):
    """Keep ambiguous/weak matches for positioning, but never as reusable ink."""
    raw = [np.asarray([(p.x, p.y) for p in s.points]) for s in sample.strokes]
    n, m = len(graph.strokes), len(raw)
    if not (0 < n <= MAX_STROKES and 0 < m <= MAX_STROKES):
        raise ValueError("笔数超出连笔原型的处理范围")
    min_ink = .008 * min(sample.canvas_width, sample.canvas_height)
    main = [p for p in raw if np.linalg.norm(np.diff(p, axis=0), axis=1).sum() >= min_ink]
    if not main:
        raise ValueError("只有零散触点")
    observed = normalized(raw, main)
    user = [stations(p, 100) for p in observed]
    refs = [stations(p, 18) for p in normalized([np.asarray(s.median) for s in graph.strokes])]
    edges = {}
    for i in range(n+1):
        for j in range(m+1):
            options = []
            if i < n:
                options.append(Edge((i,), (), .39))
            if j < m:
                options.append(Edge((), (j,), .32))
            if i < n and j < m:
                trusted, residual, coverage = match(refs[i:i+1], user[j])
                has_ink = np.linalg.norm(np.diff(raw[j], axis=0), axis=1).sum() >= min_ink
                if has_ink:
                    options.append(Edge((i,), (j,), residual*.32 + (0 if trusted else .27),
                                        trusted, coverage))
                if i+1 < n and has_ink:
                    trusted, residual, coverage = match(refs[i:i+2], user[j])
                    if trusted:
                        options.append(Edge((i, i+1), (j,), .06 + residual*.55, True, coverage))
                if j+1 < m:
                    # An extra lift competes as an explanation. It is review
                    # evidence only and never combines two physical trajectories.
                    combined = stations(np.concatenate(observed[j:j+2]), 100)
                    near = np.linalg.norm(observed[j][-1]-observed[j+1][0]) <= .09
                    if near and match(refs[i:i+1], combined)[0]:
                        options.append(Edge((i,), (j, j+1), .22))
            edges[i, j] = options
    score, path = best_path(n, m, edges)
    confirmed = {}
    for edge in path:
        if edge.trusted:
            alternative, _ = best_path(n, m, edges, forbidden=edge)
            if alternative-score >= MIN_MARGIN:
                confirmed[edge] = alternative-score
    return observed, path, confirmed
