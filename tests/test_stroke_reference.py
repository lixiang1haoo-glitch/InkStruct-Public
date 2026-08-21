from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inkstruct.stroke_reference import (
    highlighted_stroke_index,
    load_reference_bundle,
    write_reference_bundle,
)


class StrokeReferenceTests(unittest.TestCase):
    def test_highlight_moves_from_active_to_next_on_pen_release(self):
        self.assertEqual(
            highlighted_stroke_index(0, pen_down=False, expected_stroke_count=3),
            0,
        )
        self.assertEqual(
            highlighted_stroke_index(1, pen_down=True, expected_stroke_count=3),
            0,
        )
        self.assertEqual(
            highlighted_stroke_index(1, pen_down=False, expected_stroke_count=3),
            1,
        )
        self.assertEqual(
            highlighted_stroke_index(2, pen_down=True, expected_stroke_count=3),
            1,
        )

    def test_highlight_stops_after_expected_strokes(self):
        self.assertIsNone(highlighted_stroke_index(3, pen_down=False, expected_stroke_count=3))
        self.assertIsNone(highlighted_stroke_index(4, pen_down=True, expected_stroke_count=3))
        self.assertIsNone(highlighted_stroke_index(0, pen_down=False, expected_stroke_count=0))

    def test_compressed_reference_bundle_round_trip(self):
        references = {
            "十": [
                [(0.1, 0.5), (0.9, 0.5)],
                [(0.5, 0.1), (0.5, 0.9)],
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "references.json.gz"
            write_reference_bundle(path, references, source={"version": "test"})
            loaded = load_reference_bundle(path)
        self.assertEqual(list(loaded), ["十"])
        self.assertEqual(len(loaded["十"]), 2)
        for expected_stroke, actual_stroke in zip(references["十"], loaded["十"]):
            for expected_point, actual_point in zip(expected_stroke, actual_stroke):
                self.assertAlmostEqual(expected_point[0], actual_point[0], delta=1 / 1024)
                self.assertAlmostEqual(expected_point[1], actual_point[1], delta=1 / 1024)


if __name__ == "__main__":
    unittest.main()
