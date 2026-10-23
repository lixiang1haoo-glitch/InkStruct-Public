"""Purpose-built single-line delimiters, never stretched handwriting samples."""

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


def delimiter_paths(character, *, width, top, bottom, radius):
    """Return open M/L polylines inside an ink-inclusive horizontal frame."""
    if character == ".":
        return ()
    left, right = radius, width - radius
    middle = (top + bottom) / 2
    height = bottom - top
    if character in "|‖":
        xs = ((left + right) / 2,) if character == "|" else (left, right)
        return tuple(((x, top), (x, bottom)) for x in xs)
    if character in "()":
        points = tuple(
            (left + (right - left) * x, top + height * y)
            for x, y in (
                (1, 0),
                (0.55, 0.08),
                (0.2, 0.22),
                (0, 0.4),
                (0, 0.6),
                (0.2, 0.78),
                (0.55, 0.92),
                (1, 1),
            )
        )
    elif character in "[]":
        points = ((right, top), (left, top), (left, bottom), (right, bottom))
    elif character in "{}":
        points = tuple(
            (left + (right - left) * x, top + height * y)
            for x, y in (
                (1, 0),
                (0.55, 0.06),
                (0.5, 0.18),
                (0.5, 0.38),
                (0.35, 0.45),
                (0, 0.5),
                (0.35, 0.55),
                (0.5, 0.62),
                (0.5, 0.82),
                (0.55, 0.94),
                (1, 1),
            )
        )
    elif character in "⟨⟩":
        points = ((right, top), (left, middle), (right, bottom))
    else:
        raise ValueError(f"Unsupported construction delimiter: {character}")
    if character in {")", "]", "}", "⟩"}:
        points = tuple((width - x, y) for x, y in points)
    return (points,)
