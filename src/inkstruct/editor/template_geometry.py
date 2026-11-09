"""Pure physical-coordinate edits, validated by the shared template contract."""

from dataclasses import replace

from ..document.template import Anchor, Region, TemplateRule


def element_at(template, face_name, key):
    kind, index = key
    face = getattr(template, face_name)
    return face.body if kind == "body" else getattr(face, kind)[index]


def edit_element(template, face_name, key, element, *, link_body_width=True):
    """One atomic edit, including an optional coordinated body-width change."""
    if element == element_at(template, face_name, key):
        return template
    face = getattr(template, face_name)
    kind, index = key
    if kind == "body":
        face = replace(face, body=element)
    else:
        items = list(getattr(face, kind))
        items[index] = element
        face = replace(face, **{kind: tuple(items)})
    changes = {face_name: face, "calibration": "unreviewed"}
    if kind == "body" and link_body_width:
        other = "continuation" if face_name == "first" else "first"
        other_face = getattr(template, other)
        changes[other] = replace(
            other_face, body=replace(other_face.body, width_mm=element.width_mm)
        )
    return replace(template, **changes)


def move_element(element, dx, dy, step=0):
    def snap(value):
        return round(value / step) * step if step else value

    if isinstance(element, TemplateRule):
        x, y = element.points[0]
        dx, dy = snap(x + dx) - x, snap(y + dy) - y
        return replace(element, points=tuple((a + dx, b + dy) for a, b in element.points))
    return replace(element, x_mm=snap(element.x_mm + dx), y_mm=snap(element.y_mm + dy))


def resize_region(region, corner, point, step=0):
    x, y = point
    if step:
        x, y = round(x / step) * step, round(y / step) * step
    left, top, right, bottom = region.bounds
    if "l" in corner:
        left = x
    else:
        right = x
    if "t" in corner:
        top = y
    else:
        bottom = y
    # Do not silently flip a box or produce a zero-area region.
    return replace(region, x_mm=left, y_mm=top, width_mm=right - left, height_mm=bottom - top)


def move_vertex(rule, index, point, step=0):
    x, y = point
    if step:
        x, y = round(x / step) * step, round(y / step) * step
    points = list(rule.points)
    points[index] = (x, y)
    return replace(rule, points=tuple(points))


def add_element(template, face_name, kind, start, end=None, step=0):
    face = getattr(template, face_name)
    names = {face.body.name, *(v.name for v in getattr(face, kind))}
    index = 1
    while f"{kind}-{index}" in names:
        index += 1
    name = f"{kind}-{index}"

    def snapped(point):
        return tuple(round(v / step) * step if step else v for v in point)

    x, y = snapped(start)
    if kind == "anchors":
        element = Anchor(name, x, y)
    else:
        a, b = snapped(end)
        if kind == "reserved":
            element = Region(name, min(x, a), min(y, b), abs(a - x), abs(b - y))
        elif kind == "rules":
            if (a, b) == (x, y):
                raise ValueError("框线起点和终点不能相同")
            element = TemplateRule(name, ((x, y), (a, b)))
        else:
            raise ValueError("Unknown drawing tool")
    items = getattr(face, kind)
    updated = replace(
        template,
        **{face_name: replace(face, **{kind: (*items, element)})},
        calibration="unreviewed",
    )
    return updated, (kind, len(items))


def element_items(template, face_name):
    face = getattr(template, face_name)
    return [(("body", None), face.body)] + [
        ((kind, index), item)
        for kind in ("reserved", "anchors", "rules")
        for index, item in enumerate(getattr(face, kind))
    ]


def element_bounds(item):
    if isinstance(item, Region):
        return item.bounds
    if isinstance(item, Anchor):
        return item.x_mm, item.y_mm, item.x_mm, item.y_mm
    xs, ys = zip(*item.points)
    return min(xs), min(ys), max(xs), max(ys)


def edit_elements(template, face_name, updates):
    """Validate the final arrangement once, never an intermediate overlapping state."""
    face = getattr(template, face_name)
    changes = {}
    for key, item in updates.items():
        if item == element_at(template, face_name, key):
            continue
        kind, index = key
        if kind == "body":
            changes["body"] = item
        else:
            if kind not in changes:
                changes[kind] = list(getattr(face, kind))
            changes[kind][index] = item
    if not changes:
        return template
    return replace(template, **{face_name: replace(face, **changes)}, calibration="unreviewed")


def move_selection(template, face_name, keys, dx, dy, step=0):
    items = {key: element_at(template, face_name, key) for key in keys}
    if not items:
        return template
    if step:
        left = min(element_bounds(item)[0] for item in items.values())
        top = min(element_bounds(item)[1] for item in items.values())
        dx = round((left + dx) / step) * step - left
        dy = round((top + dy) / step) * step - top
    return edit_elements(
        template, face_name, {key: move_element(item, dx, dy) for key, item in items.items()}
    )


def arrange_selection(template, face_name, keys, operation):
    """Align to the selection envelope or distribute equal clear gaps."""
    keys = tuple(dict.fromkeys(keys))
    distribution = operation in {"distribute-x", "distribute-y"}
    if len(keys) < (3 if distribution else 2):
        raise ValueError("对齐需至少 2 个元素，等距分布需至少 3 个元素")
    items = {key: element_at(template, face_name, key) for key in keys}
    bounds = {key: element_bounds(item) for key, item in items.items()}
    offsets = {}
    if distribution:
        axis = 0 if operation.endswith("x") else 1
        ordered = sorted(keys, key=lambda key: (bounds[key][axis], bounds[key][axis + 2]))
        start = bounds[ordered[0]][axis]
        end = bounds[ordered[-1]][axis + 2]
        lengths = {key: bounds[key][axis + 2] - bounds[key][axis] for key in keys}
        gap = (end - start - sum(lengths.values())) / (len(keys) - 1)
        if gap < -1e-9:
            raise ValueError("选区长度不足，无法形成不重叠的等距间隔")
        position = start
        for key in ordered:
            delta = position - bounds[key][axis]
            offsets[key] = (delta, 0) if axis == 0 else (0, delta)
            position += lengths[key] + max(gap, 0)
        # Leave endpoints exactly unchanged, avoiding float round-off at paper edges.
        offsets[ordered[0]] = offsets[ordered[-1]] = (0, 0)
    else:
        axes = {
            "left": (0, 0),
            "right": (0, 2),
            "center-x": (0, None),
            "top": (1, 1),
            "bottom": (1, 3),
            "center-y": (1, None),
        }
        if operation not in axes:
            raise ValueError("Unknown alignment operation")
        axis, edge = axes[operation]
        lo = min(b[axis] for b in bounds.values())
        hi = max(b[axis + 2] for b in bounds.values())
        target = (lo + hi) / 2 if edge is None else lo if edge == axis else hi
        for key, b in bounds.items():
            anchor = (b[axis] + b[axis + 2]) / 2 if edge is None else b[edge]
            delta = target - anchor
            offsets[key] = (delta, 0) if axis == 0 else (0, delta)
    return edit_elements(
        template, face_name, {key: move_element(item, *offsets[key]) for key, item in items.items()}
    )
