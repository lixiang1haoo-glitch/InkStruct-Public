from inkstruct.alignment import align_sample, standard_order_indices
from inkstruct.schemas import (
    CharacterGraph,
    RawPoint,
    RawSample,
    RawStroke,
    StandardStroke,
    StrokeSignature,
)


def _two_horizontal_graph() -> CharacterGraph:
    signature = StrokeSignature("→", 0, 0.0, "wide", False)
    strokes = [
        StandardStroke(
            "stroke-1", 1, [(0.2, 0.3), (0.8, 0.3)], (0.2, 0.3, 0.8, 0.3), "root", signature
        ),
        StandardStroke(
            "stroke-2", 2, [(0.2, 0.7), (0.8, 0.7)], (0.2, 0.7, 0.8, 0.7), "root", signature
        ),
    ]
    return CharacterGraph(
        "character_graph_v1",
        "二",
        "U+4E8C",
        "zh-Hans",
        "二",
        None,
        [],
        [],
        strokes,
        [],
        "fixture",
        "fixture",
        1.0,
    )


def _sample(y_values: tuple[float, float]) -> RawSample:
    strokes = []
    for index, y_value in enumerate(y_values):
        start = index * 20
        strokes.append(
            RawStroke(
                index,
                [
                    RawPoint(200, y_value, 0.5, start),
                    RawPoint(800, y_value, 0.5, start + 10),
                ],
            )
        )
    return RawSample(
        "handwriting_single_v1",
        "sample",
        "writer",
        "二",
        "U+4E8C",
        1000,
        1000,
        strokes,
        "fixture.json",
        "fixture",
    )


def test_ambiguous_order_is_not_silently_reassigned():
    aligned = align_sample(_sample((549, 451)), _two_horizontal_graph())
    assert aligned.stroke_order_status == "ambiguous"
    assert aligned.stroke_permutation == [1, 2]
    assert aligned.order_confidence < 0.30
    assert aligned.confidence <= 0.25
    assert any("ambiguous captured stroke order" in warning for warning in aligned.warnings)
    assert standard_order_indices(aligned, 2) is None


def test_standard_order_indices_uses_corrected_mapping():
    aligned = align_sample(_sample((700, 300)), _two_horizontal_graph())
    assert aligned.stroke_order_status == "corrected"
    assert aligned.stroke_permutation == [2, 1]
    assert standard_order_indices(aligned, 2) == [1, 0]
