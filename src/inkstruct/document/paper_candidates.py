"""Detect rectangular writing areas in a bounded raster of a printed page."""

from io import BytesIO
from uuid import uuid4

import numpy as np
from PIL import Image, ImageFilter

from .flow_template import PaperGrid, TextFrame
from .template import Region


def horizontal(mask, width, *, close):
    def window(source, dilate):
        pad = width // 2
        padded = np.pad(source, ((0, 0), (pad, width - pad)), mode="edge")
        sums = padded.cumsum(axis=1, dtype=np.int32)
        counts = sums[:, width:] - sums[:, :-width]
        return counts > 0 if dilate else counts == width

    return window(window(mask, close), not close)


def segments(mask):
    """Eight-connected components from horizontal runs; count only ink pixels."""
    parent = []
    runs = []
    previous = []

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    if np.count_nonzero(edges == 1) > 150_000:
        return []  # A densely textured image cannot supply reliable paper regions.
    for y, row in enumerate(edges):
        current = []
        j = 0
        for left, right in zip(
            np.flatnonzero(row == 1).tolist(), np.flatnonzero(row == -1).tolist()
        ):
            label = len(parent)
            parent.append(label)
            while j < len(previous) and previous[j][1] < left:
                j += 1
            k = j
            while k < len(previous) and previous[k][0] <= right:
                parent[root(previous[k][2])] = label
                k += 1
            current.append((left, right, label))
            runs.append((left, right, y, label))
        previous = current
    bounds = {}
    for left, right, y, label in runs:
        key = root(label)
        b = bounds.setdefault(key, [left, y, right, y, 0])
        b[0] = min(b[0], left)
        b[2] = max(b[2], right)
        b[3] = y
        b[4] += right - left
    return [(l, t, r - l, b - t + 1, count) for l, t, r, b, count in bounds.values()]


def groups(items, key, tolerance):
    result = []
    for item in sorted(items, key=key):
        if not result or abs(key(item) - key(result[-1][0])) > tolerance:
            result.append([])
        result[-1].append(item)
    return result


def cell_runs(cells):
    if len(cells) < 5:
        return []
    cells = sorted(cells)
    runs = []
    for c in cells:
        if (
            not runs
            or abs(c[0] - (runs[-1][-1][0] + runs[-1][-1][2])) > max(5, c[2] * 0.18)
            or abs(c[2] - runs[-1][-1][2]) > max(4, 0.2 * c[2])
        ):
            runs.append([])
        runs[-1].append(c)
    return [r for r in runs if len(r) >= 5]


def detect(image):
    image = image.convert("RGBA")
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    background = Image.new("RGBA", image.size, "white")
    background.alpha_composite(image)
    rgb = np.asarray(background.convert("RGB"))
    h, w = rgb.shape[:2]
    dark = rgb.min(axis=2).astype(np.uint8)
    ink = dark.astype(np.int16) + 9 <= np.asarray(
        Image.fromarray(dark).filter(ImageFilter.GaussianBlur(6.5))
    )
    closed = np.asarray(
        Image.fromarray(ink.astype(np.uint8))
        .filter(ImageFilter.MaxFilter(3))
        .filter(ImageFilter.MinFilter(3))
    )
    holes = segments(closed == 0)
    cells = [
        (x, y, a, b)
        for x, y, a, b, n in holes
        if min(a, b) >= 6
        and a < w * 0.10
        and b < h * 0.12
        and 0.44 < a / b < 2
        and n >= a * b * 0.87
    ]
    runs = [run for row in groups(cells, lambda c: c[1], 3) for run in cell_runs(row)]
    grids = []
    for run in sorted(runs, key=lambda r: r[0][1]):
        x, y, a, b = run[0]
        compatible = [
            g
            for g in grids
            if len(g[-1]) == len(run)
            and abs(g[-1][0][0] - x) < max(4, a * 0.15)
            and 0.75 * b <= y - g[-1][0][1] <= 2.1 * b
            and abs(g[-1][0][3] - b) < max(3, b * 0.2)
        ]
        if compatible:
            compatible[-1].append(run)
        else:
            grids.append([run])
    regions = []
    for g in grids:
        if len(g) < 4:
            continue
        cells = [c for line in g for c in line]
        box = [
            min(c[0] for c in cells),
            min(c[1] for c in cells),
            max(c[0] + c[2] for c in cells),
            max(c[1] + c[3] for c in cells),
        ]
        regions.append(dict(kind="grid", box=box, rows=len(g), cols=len(g[0]), cells=g))

    def covered(x, y):
        return any(
            l - 4 <= x <= r + 4 and t - 4 <= y <= b + 4
            for item in regions
            for l, t, r, b in [item["box"]]
        )

    joined = horizontal(ink, max(3, w // 130), close=True)
    horiz = horizontal(joined, max(25, w // 10), close=False)
    # Long rules with similar endpoints and regular gaps. Vertical dividers veto data tables.
    lines = [
        (x, y + b // 2, a)
        for x, y, a, b, n in segments(horiz)
        if a > w * 0.19 and b < h * 0.012 and not covered(x + a / 2, y)
    ]
    by_extent = []
    for line in sorted(lines, key=lambda c: c[1]):
        x, y, a = line
        bucket = next(
            (k for k in by_extent if abs(k[0][0] - x) < 0.025 * w and abs(k[0][2] - a) < 0.045 * w),
            None,
        )
        if bucket is None:
            by_extent.append([line])
        else:
            bucket.append(line)
    for bucket in by_extent:
        # Walk repeated spacing, including separately boxed groups on a mixed form.
        i = 0
        while i + 3 < len(bucket):
            pitch = bucket[i + 1][1] - bucket[i][1]
            if not 0.008 * h < pitch < 0.10 * h:
                i += 1
                continue
            end = i + 2
            while end < len(bucket) and abs(bucket[end][1] - bucket[end - 1][1] - pitch) <= max(
                2, 0.13 * pitch
            ):
                end += 1
            if end - i < 4:
                i += 1
                continue
            sub = bucket[i:end]
            i = end
            x = int(np.median([p[0] for p in sub]))
            a = int(np.median([p[2] for p in sub]))
            first_index = end - len(sub)
            if first_index and sub[0][1] - bucket[first_index - 1][1] < pitch * 0.35:
                sub = sub[1:]  # Top double rule marks the upper edge of the first writing band.
            elif len(sub) > 4:
                header = ink[sub[0][1] + 3 : sub[1][1] - 3, x + 8 : x + a - 8]
                if header.size and np.count_nonzero(header) / header.size > 0.012:
                    sub = sub[2:]  # Leave the printed title and its bottom border out.
            while sub:
                y = sub[0][1]
                above = ink[max(0, int(y - pitch) + 4) : y - 4, x + 12 : x + a - 12]
                if above.size and np.mean(above > 0) < 0.025:
                    break
                sub = sub[1:]
            if len(sub) < 3:
                continue
            y1, y2 = sub[0][1], sub[-1][1]
            mid = ink[y1 + 2 : y2 - 1, x + int(0.03 * a) : x + int(0.97 * a)]
            if mid.size and np.max((mid > 0).mean(axis=0)) > 0.65:
                continue
            regions.append(
                dict(
                    kind="lined",
                    box=[x, max(0, round(y1 - pitch * 0.83)), x + a, y2],
                    baselines=[p[1] for p in sub],
                    rows=len(sub),
                )
            )
    for x, y, a, b, n in holes:
        if (
            a < w * 0.35
            or b < h * 0.14
            or n < a * b * 0.89
            or x < 2
            or y < 2
            or x + a > w - 2
            or y + b > h - 2
        ):
            continue
        if any(
            max(0, min(x + a, r) - max(x, l)) * max(0, min(y + b, bt) - max(y, t)) > 0.12 * a * b
            for reg in regions
            for l, t, r, bt in [reg["box"]]
        ):
            continue
        # Trim the printed header inside an otherwise blank rectangular area.
        inset = max(4, round(0.008 * w))
        left = x + inset
        right = x + a - inset
        ys = np.flatnonzero(
            (ink[y + inset : y + int(b * 0.18), left:right] > 0).mean(axis=1) > 0.012
        )
        top = y + inset + (int(ys[-1]) + inset if ys.size else 0)
        regions.append(dict(kind="free", box=[left, top, right, y + b - inset]))
    return image.size, sorted(regions, key=lambda r: (r["box"][1], r["box"][0]))


def body_candidates(background, width_mm, height_mm):
    with Image.open(BytesIO(background.png_bytes())) as image:
        (w, h), regions = detect(image)
    sx, sy = width_mm / w, height_mm / h
    frames = []
    for i, candidate in enumerate(regions, 1):
        l, t, r, b = candidate["box"]
        rect = Region("body", l * sx, t * sy, (r - l) * sx, (b - t) * sy)
        grid = None
        kind = candidate["kind"]
        if kind == "lined":
            lines = candidate["baselines"]
            grid = PaperGrid((lines[0] - t) * sy, (lines[-1] - t) * sy, len(lines))
        elif kind == "grid":
            cells = candidate["cells"]
            # Keep the baseline inside the printed cell, independent of the gap to the next row.
            centers = [float(np.median([c[1] + c[3] / 2 for c in row])) for row in cells]
            grid = PaperGrid(
                (centers[0] - t) * sy, (centers[-1] - t) * sy, len(cells), len(cells[0])
            )
        label = {"lined": "横线正文", "free": "自由正文", "grid": "方格正文"}[kind]
        frames.append(TextFrame("body-" + uuid4().hex[:12], label, rect, order=i, paper_grid=grid))
    return tuple(frames)
