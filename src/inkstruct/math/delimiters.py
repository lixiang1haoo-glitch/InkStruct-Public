"""Axis-centred extensible delimiters built from stable caps and connectors."""

from __future__ import annotations


def node_delimiters(node):
    """The same characters drive layout and resource inspection."""
    attrs = dict(node.attributes)
    if node.kind == "Delimited":
        return attrs["left"], attrs["right"]
    if node.kind in {"EquationTag", "EquationReference"}:
        return ("(", ")") if attrs.get("parentheses") == "true" else (".", ".")
    if node.kind == "Matrix":
        return {
            "matrix": (".", "."),
            "smallmatrix": (".", "."),
            "pmatrix": ("(", ")"),
            "bmatrix": ("[", "]"),
            "Bmatrix": ("{", "}"),
            "vmatrix": ("|", "|"),
            "Vmatrix": ("‖", "‖"),
            "cases": ("{", "."),
        }[attrs["environment"]]
    return ".", "."


def delimiter_frame(*, ascent, descent, axis, em, radius):
    """TeX left/right sizing, with a one-em minimum and an ink-inclusive frame.

    TeX's delimiterfactor=901 and delimitershortfall=5pt (0.5em at 10pt)
    determine total height from the greater distance to the mathematical axis.
    The pen centreline is inset so its visible envelope has that total height.
    """
    distance = max(0, ascent - axis, descent + axis)
    height = max(em, 1.802 * distance, 2 * distance - .5 * em, 4 * radius)
    return -axis - height / 2 + radius, -axis + height / 2 - radius


def delimiter_stretch_breaks(character, waist_fraction=.5):
    if character in "{}":
        cap = min(.2, .5 * waist_fraction, .5 * (1 - waist_fraction))
        waist = min(.1, .25 * waist_fraction, .25 * (1 - waist_fraction))
        return cap, waist_fraction - waist, waist_fraction + waist, 1 - cap
    return (.25, .75) if character in "()[]" else ()


def delimiter_stretch_y(character, fraction, *, height, natural_height, waist_fraction=.5):
    """Keep end caps and a brace's measured waist fixed; grow connector bands."""
    natural = min(height, natural_height)
    breaks = delimiter_stretch_breaks(character, waist_fraction)
    if character in "{}":
        cap = breaks[0]
        waist = (breaks[2] - breaks[1]) / 2
        source = (0, *breaks, 1)
        target = (
            0, cap * natural, height / 2 - waist * natural,
            height / 2 + waist * natural, height - cap * natural, height,
        )
    elif character in "()[]":
        source = (0, *breaks, 1)
        target = (0, .25 * natural, height - .25 * natural, height)
    else:
        return fraction * height
    for a, b, low, high in zip(source, source[1:], target, target[1:]):
        if fraction <= b:
            return low + (fraction - a) * (high - low) / (b - a)
    return height


def delimiter_paths(character, *, width, top, bottom, radius):
    """Return open M/L polylines inside an ink-inclusive horizontal frame."""
    if character == ".":
        return ()
    left, right = radius, width - radius
    middle = (top + bottom) / 2
    height = bottom - top
    if character in "|\u2016":
        xs = ((left + right) / 2,) if character == "|" else (left, right)
        return tuple(((x, top), (x, bottom)) for x in xs)

    def shape(template):
        breaks = delimiter_stretch_breaks(character)
        points = []
        for i, (x, y) in enumerate(template):
            if i:
                a, b = template[i - 1], (x, y)
                for cut in breaks:
                    if a[1] < cut < b[1]:
                        t = (cut - a[1]) / (b[1] - a[1])
                        points.append((a[0] + t * (b[0] - a[0]), cut))
            points.append((x, y))
        return tuple(
            (
                left + (right - left) * x,
                top + delimiter_stretch_y(
                    character, y, height=height, natural_height=3 * (right - left),
                ),
            )
            for x, y in points
        )

    if character in "()":
        points = shape((
            (1, 0), (.55, .08), (.2, .22), (0, .4),
            (0, .6), (.2, .78), (.55, .92), (1, 1),
        ))
    elif character in "[]":
        points = ((right, top), (left, top), (left, bottom), (right, bottom))
    elif character in "{}":
        points = shape((
            (1, 0), (.55, .06), (.5, .18), (.5, .38), (.35, .45),
            (0, .5), (.35, .55), (.5, .62), (.5, .82), (.55, .94), (1, 1),
        ))
    elif character in "\u27e8\u27e9":
        points = ((right, top), (left, middle), (right, bottom))
    else:
        raise ValueError(f"Unsupported construction delimiter: {character}")
    if character in {")", "]", "}", "\u27e9"}:
        points = tuple((width - x, y) for x, y in points)
    return (points,)
