import unittest

from inkstruct.geometry import cubic_bspline, resample, stroke_signature


class GeometryTests(unittest.TestCase):
    def test_resample_preserves_endpoints(self):
        sampled = resample([(0.0, 0.0), (1.0, 0.0)], 5)
        self.assertEqual(sampled[0], (0.0, 0.0))
        self.assertEqual(sampled[-1], (1.0, 0.0))
        self.assertEqual(len(sampled), 5)

    def test_signature_records_direction_and_aspect(self):
        signature = stroke_signature([(0.0, 0.5), (1.0, 0.5)])
        self.assertEqual(signature.directions, "→")
        self.assertEqual(signature.aspect, "wide")

    def test_bspline_is_finite_and_bounded(self):
        points = cubic_bspline([(0.1, 0.2), (0.3, 0.1), (0.7, 0.9), (0.9, 0.8)], 24)
        self.assertEqual(len(points), 24)
        self.assertTrue(all(0 <= x <= 1 and 0 <= y <= 1 for x, y in points))


if __name__ == "__main__":
    unittest.main()
