"""Path simplification in document coordinates for screen drawing."""

from ..document.cancellation import check_cancel

TOLERANCE_DEVICE_PX = 0.1


def tolerance_squared(profile, spec):
    width, height, dpr = spec
    # Use the larger axis scale so rounding the logical page size is safe.
    # Tiles translate this same full-page transform by a physical pixel offset.
    pixels_per_mm = dpr * max(width / profile.width_mm, height / profile.height_mm)
    return (TOLERANCE_DEVICE_PX / pixels_per_mm) ** 2


def simplify_stroke(points, tolerance_sq, *, cancelled=None):
    """Iterative Ramer–Douglas–Peucker on a single physical pen stroke."""
    if len(points) <= 2:
        return points
    last = len(points) - 1
    retained = {0, last}
    pending = [(0, last)]
    while pending:
        check_cancel(cancelled)
        start, end = pending.pop()
        ax, ay = points[start]
        bx, by = points[end]
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        furthest, split = tolerance_sq, None
        for i in range(start + 1, end):
            if i % 256 == 0:
                check_cancel(cancelled)
            x, y = points[i]
            ex, ey = x - ax, y - ay
            ratio = (ex * dx + ey * dy) / length_sq if length_sq else 0
            ratio = 0 if ratio < 0 else 1 if ratio > 1 else ratio
            rx, ry = ex - ratio * dx, ey - ratio * dy
            distance_sq = rx * rx + ry * ry
            if distance_sq > furthest:
                furthest, split = distance_sq, i
        if split is not None:
            retained.add(split)
            if split - start > 1:
                pending.append((start, split))
            if end - split > 1:
                pending.append((split, end))
    if len(retained) == len(points):
        return points
    return tuple(points[i] for i in sorted(retained))
