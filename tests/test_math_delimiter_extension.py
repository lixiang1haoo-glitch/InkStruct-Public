"""Delimiter growth follows the math axis and preserves sampled turning features."""

from dataclasses import replace

import pytest
from test_math_sample_constructions import assets, measure, resolver

from inkstruct.document.editing import SourceSession
from inkstruct.math.delimiters import delimiter_frame, delimiter_paths
from inkstruct.math.handwritten import ink_bounds
from inkstruct.math.sample_constructions import delimiter_sample_paths
from inkstruct.math.style import MathStyle


@pytest.mark.parametrize("ascent,descent", [(3, .5), (16, 2), (4, 20)])
def test_delimiter_frame_uses_tex_axis_distance_and_shortfall(ascent, descent):
    axis, em, radius = 1.5, 6, .15
    top, bottom = delimiter_frame(
        ascent=ascent, descent=descent, axis=axis, em=em, radius=radius,
    )
    distance = max(ascent - axis, descent + axis)
    required = max(em, 1.802 * distance, 2 * distance - .5 * em)
    assert (top + bottom) / 2 == pytest.approx(-axis)
    assert bottom - top + 2 * radius == pytest.approx(required)


@pytest.mark.parametrize("content", [
    "1^2", "1_2", r"\frac{1^2}{3}", r"\frac{1}{\frac{2}{3}}",
])
@pytest.mark.parametrize("style", [
    MathStyle(delimiter_source="geometric", axis_em=.4),
    MathStyle.handwriting(axis_em=.4),
])
def test_asymmetric_contents_keep_delimiters_centred_on_math_axis(content, style):
    r = resolver()
    plain = measure(SourceSession("$" + content + "$"), r, style)
    box = measure(SourceSession(r"$\left\{" + content + r"\right\}$"), r, style)
    assert plain.ready and box.ready, (plain.diagnostics, box.diagnostics)
    if style.spacing_policy == "handwriting":
        _, high, _, low = ink_bounds(plain, .3)
        ascent, descent = max(0, -high), max(0, low)
    else:
        ascent, descent = plain.ascent, plain.descent
    expected = delimiter_frame(
        ascent=ascent, descent=descent, axis=box.axis, em=style.em_mm, radius=.15,
    )
    braces = [rule for rule in box.rules if "delimiter-" in rule.occurrence_id]
    assert len(braces) == 2
    for rule in braces:
        ys = [y for _, y in rule.points]
        assert (min(ys), max(ys)) == pytest.approx(expected)
        # Each brace has its leftmost/rightmost waist at the mathematical axis.
        cusp = min(rule.points, key=lambda p: p[0]) if "left" in rule.occurrence_id else max(
            rule.points, key=lambda p: p[0]
        )
        assert cusp[1] == pytest.approx(-box.axis)


@pytest.mark.parametrize("source", [
    r"\begin{cases}1^2&2\\3&4_5\end{cases}",
    r"\begin{Bmatrix}1&2\\3&4\\5&6\end{Bmatrix}",
    r"\left(\left[\frac{1}{2}\right]\right)",
])
def test_matrix_cases_and_nested_delimiter_frames_share_axis(source):
    box = measure(SourceSession("$" + source + "$"), resolver(), MathStyle.handwriting())
    assert box.ready, box.diagnostics
    for rule in box.rules:
        if "delimiter-" in rule.occurrence_id:
            ys = [y for _, y in rule.points]
            assert (min(ys) + max(ys)) / 2 == pytest.approx(-box.axis)


def test_sample_brace_preserves_cap_and_waist_height_when_connectors_grow():
    glyph = next(g for g in assets() if g.character == "{")
    points = tuple((abs(y - .5), y) for y in (0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1))
    glyph = replace(glyph, strokes=(points,))
    before = glyph.strokes
    small = delimiter_sample_paths(glyph, width=3, top=-10, bottom=10, em=6, radius=.15)[0]
    large = delimiter_sample_paths(glyph, width=3, top=-20, bottom=20, em=6, radius=.15)[0]
    assert glyph.strokes == before
    assert len(small) == len(large) == len(points)
    for old, new, (_, fraction) in zip(small, large, points, strict=True):
        assert old[0] == new[0]
        if fraction <= .2:
            assert old[1] + 10 == pytest.approx(new[1] + 20)
        elif .4 <= fraction <= .6:
            assert old[1] == pytest.approx(new[1])
        elif fraction >= .8:
            assert 10 - old[1] == pytest.approx(20 - new[1])
    assert min(small, key=lambda p: p[0])[1] == pytest.approx(0)
    assert min(large, key=lambda p: p[0])[1] == pytest.approx(0)


@pytest.mark.parametrize("reverse", [False, True])
def test_sparse_sample_segments_insert_every_extension_boundary_in_stroke_order(reverse):
    glyph = next(g for g in assets() if g.character == "{")
    points = ((0, 0), (1, 1))
    glyph = replace(glyph, strokes=(tuple(reversed(points)) if reverse else points,))
    paths = delimiter_sample_paths(glyph, width=3, top=0, bottom=30, em=6, radius=.15)
    assert len(paths) == 1 and len(paths[0]) == 6
    expected = [(0, 0), (.2, 1.2), (.4, 14.4), (.6, 15.6), (.8, 28.8), (1, 30)]
    expected = tuple((.15 + x * 2.7, y) for x, y in expected)
    if reverse:
        expected = tuple(reversed(expected))
    for actual, wanted in zip(paths[0], expected, strict=True):
        assert actual == pytest.approx(wanted)


@pytest.mark.parametrize("character", ["(", ")", "{", "}"])
def test_geometric_extension_keeps_caps_and_waist_fixed(character):
    small = delimiter_paths(character, width=3, top=-10, bottom=10, radius=.15)[0]
    large = delimiter_paths(character, width=3, top=-20, bottom=20, radius=.15)[0]
    assert len(small) == len(large)
    assert small[1][1] + 10 == pytest.approx(large[1][1] + 20)
    assert 10 - small[-2][1] == pytest.approx(20 - large[-2][1])
    if character in "{}":
        waist = min if character == "{" else max
        assert waist(small, key=lambda p: p[0])[1] == pytest.approx(0)
        assert waist(large, key=lambda p: p[0])[1] == pytest.approx(0)


@pytest.mark.parametrize("character", ["{", "}"])
@pytest.mark.parametrize("waist", [.4, .6])
def test_asymmetric_sample_brace_centres_its_recorded_waist_and_preserves_local_height(
    character, waist,
):
    glyph = next(g for g in assets() if g.character == character)
    points = (
        (.3, 0), (.18, .1), (.15, .2), (.12, waist - .1),
        (.05, waist - .05), (0, waist), (.05, waist + .05),
        (.12, waist + .1), (.15, .8), (.18, .9), (.3, 1),
    )
    if character == "}":
        points = tuple((-x, y) for x, y in points)
    glyph = replace(glyph, strokes=(points,))
    for height in (10, 40):
        path = delimiter_sample_paths(
            glyph, width=3, top=-height / 2, bottom=height / 2, em=6, radius=.15,
        )[0]
        tip = (min if character == "{" else max)(path, key=lambda p: p[0])
        assert tip[1] == pytest.approx(0)
        # The two adjacent points remain 0.05em above/below the recorded cusp.
        neighbours = sorted(y for x, y in path if abs(x - tip[0]) < .46)
        assert neighbours == pytest.approx([-.3, 0, .3])


@pytest.mark.parametrize("character", ["|", "\u2016"])
def test_vertical_delimiter_samples_do_not_magnify_horizontal_capture_jitter(character):
    glyph = next(g for g in assets() if g.character == "|")
    glyph = replace(glyph, character=character, strokes=(((0, 0), (.01, .3), (0, 1)),))
    path = delimiter_sample_paths(
        glyph, width=6, top=0, bottom=30, em=6, radius=.15,
    )[0]
    assert max(x for x, _ in path) - min(x for x, _ in path) == pytest.approx(.06)
