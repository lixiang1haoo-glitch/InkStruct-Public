"""Propose a centerline for explicitly reviewed tiny-median source defects.

Only simple, elongated outlines with single-interval cross sections qualify.
This never edits upstream graphics or automatically repairs ordinary short pens.
"""
from __future__ import annotations

import re
from itertools import pairwise

import numpy as np

from .geometry import path_length

OUTLINE_VERSION = 'single_strip_outline_median_v1'


def flatten_outline(path, subdivisions=24):
    tokens = re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', path)
    result, cursor, start = [], None, None
    i = 0
    while i < len(tokens):
        command = tokens[i]
        i += 1
        if command == 'Z':
            if start is None:
                raise ValueError('outline closed without a start')
            result.append(start)
            continue
        if command not in ('M', 'L', 'Q', 'C'):
            raise ValueError('unsupported outline command; explicit review required')
        count = {'M': 2, 'L': 2, 'Q': 4, 'C': 6}[command]
        raw = np.asarray([float(t) for t in tokens[i:i + count]]).reshape(-1, 2)
        i += count
        if command == 'M':
            if start is not None:
                raise ValueError('multiple contours are not a simple stroke')
            cursor = start = raw[0]
            result.append(cursor)
        elif command == 'L':
            cursor = raw[0]
            result.append(cursor)
        else:
            if cursor is None:
                raise ValueError('curve without start')
            t = np.linspace(0, 1, subdivisions + 1)[1:, None]
            if command == 'Q':
                segment = (1 - t) ** 2 * cursor + 2 * (1 - t) * t * raw[0] + t ** 2 * raw[1]
            else:
                segment = (1 - t) ** 3 * cursor + 3 * (1 - t) ** 2 * t * raw[0] + 3 * (1 - t) * t ** 2 * raw[1] + t ** 3 * raw[2]
            result.extend(segment)
            cursor = raw[-1]
    values = np.asarray(result)
    if len(values) < 4 or not np.isfinite(values).all():
        raise ValueError('invalid closed outline')
    if not np.allclose(values[0], values[-1]):
        raise ValueError('outline is not closed')
    return values


def propose_strip_median(path, original_median, *, count=40):
    polygon = flatten_outline(path)
    # Use equally spaced boundary samples so the SVG's command segmentation
    # cannot bias the principal direction.
    from .geometry import resample
    boundary = np.asarray(resample(polygon.tolist(), 512))
    center = boundary.mean(axis=0)
    values, vectors = np.linalg.eigh(np.cov((boundary - center).T))
    if values[-1] < 4 * max(values[0], 1e-12):
        raise ValueError('outline is not sufficiently elongated')
    direction = vectors[:, -1]
    normal = np.array([-direction[1], direction[0]])
    basis = np.column_stack([direction, normal])
    local = (polygon - center) @ basis
    extent = float(np.ptp(local[:, 0]))
    old_length = path_length(original_median)
    if extent <= 1e-8 or old_length / extent >= .05:
        raise ValueError('median is not a reviewed near-empty centerline')
    cuts = np.linspace(local[:, 0].min() + extent * .02,
                       local[:, 0].max() - extent * .02, count)
    medians, widths = [], []
    for u in cuts:
        intersections = []
        for a, b in pairwise(local):
            if (a[0] <= u < b[0]) or (b[0] <= u < a[0]):
                intersections.append(float(a[1] + (u - a[0]) / (b[0] - a[0]) * (b[1] - a[1])))
        intersections = sorted(intersections)
        if len(intersections) != 2:
            raise ValueError('outline is not a single strip at every cross section')
        medians.append([u, sum(intersections) / 2])
        widths.append(intersections[1] - intersections[0])
    curve = np.asarray(medians) @ basis.T + center
    # The old tiny median identifies the terminal region only. It does not
    # justify keeping its bogus start as the repaired stroke's start.
    endpoint = np.asarray(original_median[-1])
    if np.linalg.norm(curve[0] - endpoint) < np.linalg.norm(curve[-1] - endpoint):
        curve = curve[::-1]
    repaired = [tuple(map(float, p)) for p in curve]
    return repaired, {'version': OUTLINE_VERSION, 'old_length': old_length,
                      'proposed_length': path_length(repaired), 'outline_extent': extent,
                      'single_interval_sections': len(cuts), 'median_section_width': float(np.median(widths)),
                      'interpretation': 'outline-derived source estimate, not captured handwriting'}


def apply_reviewed_override(original_graph, graphics, dictionary, config):
    """Apply an explicitly versioned, hash-matched proposal to a copied graph."""
    import copy
    import hashlib
    import json

    from .structures import graph_from_records

    if config['algorithm'] != OUTLINE_VERSION:
        raise ValueError('unsupported outline repair version')
    if original_graph.character != config['character'] or graphics['character'] != config['character']:
        raise ValueError('override character mismatch')
    if original_graph.source_version != config['source_version']:
        raise ValueError('override source version mismatch')
    index = next(i for i, s in enumerate(original_graph.strokes) if s.stroke_id == config['stroke_id'])
    outline_hash = hashlib.sha256(graphics['strokes'][index].encode()).hexdigest()
    median_hash = hashlib.sha256(json.dumps(graphics['medians'][index], separators=(',', ':')).encode()).hexdigest()
    if outline_hash != config['outline_sha256'] or median_hash != config['median_sha256']:
        raise ValueError('override source hashes changed')
    curve, report = propose_strip_median(graphics['strokes'][index], graphics['medians'][index],
                                         count=config['cross_sections'])
    updated = copy.deepcopy(graphics)
    updated['medians'][index] = [list(p) for p in curve]
    identity = hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    graph = graph_from_records(updated, dictionary,
        simplified_characters={original_graph.character} if original_graph.locale == 'zh-Hans' else set(),
        source_version=original_graph.source_version + '+median-override-' + identity[:12])
    report.update({'override_sha256': identity, 'source_outline_sha256': outline_hash,
                   'source_median_sha256': median_hash})
    return graph, report
