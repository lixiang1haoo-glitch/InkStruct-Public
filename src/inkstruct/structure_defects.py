"""Source/outline diagnostics; heuristic flags never authorize a repair."""
from __future__ import annotations

import hashlib
import json

import numpy as np
from matplotlib.path import Path as PolygonPath

from .geometry import path_length, resample
from .outline_median import flatten_outline
from .structures import _parse_ids


def record_hash(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def boundary_distances(points, polygon):
    p, a, b = np.asarray(points), np.asarray(polygon[:-1]), np.asarray(polygon[1:])
    if not len(p):
        return np.asarray([])
    v = b-a
    t = np.clip(np.sum((p[:, None]-a)*v, axis=2)/np.maximum(np.sum(v*v, axis=1), 1e-12), 0, 1)
    return np.sqrt(np.min(np.sum((p[:, None]-a-t[:, :, None]*v)**2, axis=2), axis=1))


def audit_stroke(outline, median):
    m = np.asarray(median, dtype=float)
    if m.ndim != 2 or m.shape[1:] != (2,) or len(m) < 2 or not np.isfinite(m).all():
        return {'confirmed': ['invalid_median'], 'suspected': [], 'unassessed': ['outline_geometry']}
    confirmed, suspected = [], []
    old = np.c_[np.clip(m[:, 0]/1024., 0, 1), np.clip(1-m[:, 1]/1024., 0, 1)]
    restored = np.c_[m[:, 0]/1024., 1-m[:, 1]/1024.]
    clipped = np.any(np.abs(old-restored) > 1e-12, axis=1)
    if clipped.any():
        confirmed.append('import_clipping')
    if np.any((m[:, 0] < 0) | (m[:, 0] > 1024) | (m[:, 1] < -124) | (m[:, 1] > 900)):
        suspected.append('outside_documented_source_frame')
    length = path_length(m.tolist())
    if length <= 1e-9:
        confirmed.append('zero_length_median')
    vectors = np.diff(m, axis=0)
    segment_lengths = np.linalg.norm(vectors, axis=1)
    angles = np.degrees(np.arccos(np.clip(np.sum(vectors[:-1]*vectors[1:], axis=1)/np.maximum(segment_lengths[:-1]*segment_lengths[1:], 1e-12), -1, 1)))
    reversals = int(np.sum((angles > 140) & (segment_lengths[:-1] > 8) & (segment_lengths[1:] > 8)))
    if reversals:
        suspected.append('sharp_reversal_or_hook')
    result = {'confirmed': confirmed, 'suspected': suspected, 'unassessed': [], 'raw_length': length,
              'imported_length': path_length(old.tolist())*1024, 'clipped_vertices': int(clipped.sum()),
              'clipping_max_distance': float(np.max(np.linalg.norm(old-restored, axis=1))*1024),
              'large_reversals': reversals}
    try:
        polygon = flatten_outline(outline, subdivisions=12)
    except (ValueError, IndexError) as error:
        result['unassessed'].append('outline_parser: '+str(error))
        return result
    samples = np.asarray(resample(m.tolist(), 65))
    probes = np.vstack([samples, m])
    inside = PolygonPath(polygon).contains_points(probes)
    distances = np.zeros(len(probes))
    distances[~inside] = boundary_distances(probes[~inside], polygon)
    outside = distances > 8.
    diagonal = float(np.linalg.norm(np.ptp(polygon, axis=0)))
    boundary = np.asarray(resample(polygon.tolist(), 65))
    # Distance from outline to polyline is a screening proxy, not a missing-hook verdict.
    uncovered = boundary_distances(boundary, m)
    result.update(outside_fraction=float(np.mean(outside[:65])), outside_max_distance=float(distances.max()),
        endpoint_outside_max=float(max(distances[0], distances[64])), outline_diagonal=diagonal,
        length_extent_ratio=length/max(diagonal, 1e-12), boundary_coverage_gap=float(np.quantile(uncovered, .9)),
        median_outline_bbox_ratio=(np.ptp(m, axis=0)/np.maximum(np.ptp(polygon, axis=0), 1e-9)).tolist())
    if length < 10 or length < .12*diagonal:
        suspected.append('short_or_partial_path')
    if result['outside_fraction'] > .05 or result['outside_max_distance'] > 20:
        suspected.append('outside_own_outline')
    if result['endpoint_outside_max'] > 12:
        suspected.append('endpoint_outside_outline')
    if result['boundary_coverage_gap'] > max(70, .2*diagonal):
        suspected.append('coverage_gap_or_missing_turn')
    return result


def audit_mapping(graphics, dictionary, graph):
    confirmed, unresolved = [], []
    n = len(graphics.get('medians', []))
    if len(graphics.get('strokes', [])) != n:
        confirmed.append('outline_median_count_mismatch')
    if len(graph.strokes) != n or [s.stroke_id for s in graph.strokes] != [f's{i+1}' for i in range(n)] or [s.order for s in graph.strokes] != list(range(1, n+1)):
        confirmed.append('database_stroke_identity_order_mismatch')
    matches = dictionary.get('matches')
    if not isinstance(matches, list) or len(matches) != n:
        unresolved.append('missing_or_incomplete_component_matches')
    try:
        tree = _parse_ids(dictionary.get('decomposition', ''))
        nodes = {}
        def visit(node):
            nodes[node.path] = node
            for child in node.children:
                visit(child)
        visit(tree)
        if any(node.value == '？' for node in nodes.values()):
            unresolved.append('unknown_component_decomposition')
        if isinstance(matches, list):
            for i, match in enumerate(matches[:n]):
                if match is None:
                    unresolved.append('unassigned_stroke_component')
                elif not isinstance(match, list) or any(type(k) is not int for k in match) or tuple(match) not in nodes:
                    confirmed.append(f'invalid_component_path:s{i+1}')
                elif nodes[tuple(match)].children:
                    unresolved.append('match_to_nonleaf_component')
                elif graph.strokes[i].component_path != 'root'+''.join(f'.{v}' for v in match):
                    confirmed.append(f'database_component_match_mismatch:s{i+1}')
    except (ValueError, TypeError):
        unresolved.append('unparseable_decomposition')
    # Font stroke order is the sole source here; this does not establish linguistic correctness.
    return {'confirmed': sorted(set(confirmed)), 'unresolved': sorted(set(unresolved)),
            'normative_stroke_order': 'unverified: no independent stroke-order authority'}
