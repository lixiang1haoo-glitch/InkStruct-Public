import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from inkstruct.fonts.exchange_codec import EXTENSIONS, LEGACY_FEATURES, convert, digest, encode, verify


FONT = "00000000-0000-4000-8000-000000000001"
ONE = "00000000-0000-4000-8000-000000000011"
TWO = "00000000-0000-4000-8000-000000000012"
THREE = "00000000-0000-4000-8000-000000000013"


def write_legacy(path, *, corrupt=False, out_of_range=False, enabled_alternate=False):
    records, metrics, provenance, raw = [], {}, {}, {}
    for cid, enabled, review in ((ONE, True, "unreviewed"), (TWO, enabled_alternate, "unreviewed"),
                                 (THREE, True, "rejected")):
        member = f"glyphs/{cid}.json"
        records.append({"candidate_id": cid, "character": "A", "file": member,
                        "enabled": enabled, "letter_style": "upright",
                        "priority": 2 if enabled_alternate and cid == ONE else 0})
        metrics[cid] = {"baseline": 0.88, "ascent": 0.88, "descent": 0.12, "advance": 0.7}
        provenance[cid] = {"source_kind": "recorded", "review_status": review,
                           "capture_guides": {"math_axis_em": 0.6}}
        raw[member] = encode({
            "character": "A", "coordinate_space": "em-y-down-baseline-0.88",
            "schema_version": "inkfont_trajectory_v1",
            "strokes": [
                {"order": 1, "stroke_ref": "stroke-1",
                 "dynamic_origin": {"pressure": "measured", "time": "measured", "pen_state": "measured"},
                 "points": [{"x": 0.0005, "y": -9.2 if out_of_range else 0.8795,
                             "t_ms": 50, "pressure": 0, "pen_state": "down"},
                            {"x": 0.2, "y": 0.7, "t_ms": 60, "pen_state": "up"}]},
                {"order": 2, "stroke_ref": "stroke-2",
                 "dynamic_origin": {"pressure": "inherited", "time": "measured",
                                    "pen_state": "absent"},
                 "points": [{"x": -0.1, "y": 0.82, "t_ms": 150, "pressure": 0.5}]},
            ],
        })
    records.sort(key=lambda record: (record["priority"], record["candidate_id"]))
    raw["index.json"] = encode({"selection_policy": "style-priority-uniform-v1",
                                 "candidates": records})
    raw["metrics.json"], raw["provenance.json"] = encode(metrics), encode(provenance)
    manifest = {"format": "inkstruct_font", "format_version": "1.0",
                "font_id": FONT, "name": "转档测试", "required_features": LEGACY_FEATURES,
                "members": {name: {"bytes": len(data), "sha256": digest(data)}
                            for name, data in raw.items()}}
    manifest["content_hash"] = digest(encode(manifest, sort_keys=True))
    if corrupt:
        member = f"glyphs/{ONE}.json"
        raw[member] = raw[member].replace(b"0.0005", b"0.0006", 1)
    with ZipFile(path, "w", ZIP_DEFLATED) as out:
        out.writestr("manifest.json", encode(manifest))
        for name, data in raw.items():
            out.writestr(name, data)


class ConverterTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.old = self.folder / "old.inkfont"
        self.out = self.folder / "exchange.inkfont"

    def test_core_quantization_and_eligibility(self):
        write_legacy(self.old)
        source = self.old.read_bytes()
        report = convert(self.old, self.out)
        self.assertEqual(self.old.read_bytes(), source)
        self.assertEqual(report["skipped"], {"disabled": 1, "rejected": 1})
        self.assertEqual(report["omitted_extensions"], list(EXTENSIONS))
        self.assertEqual(verify(self.out)["points"], 3)
        with ZipFile(self.out) as z:
            self.assertEqual(json.loads(z.read("index.json")), {"A": [ONE]})
            self.assertEqual(json.loads(z.read(f"glyphs/{ONE}.json"))["strokes"],
                             [[[0.001, -0.001], [0.2, -0.18]], [[-0.1, -0.06]]])
        self.assertLess(report["max_quantization_error_at_20mm"], 0.0142)

    def test_extensions_preserve_null_zero_timing_and_axis(self):
        write_legacy(self.old)
        first = convert(self.old, self.out, full_precision=True, extensions=tuple(EXTENSIONS))
        bare = self.folder / "bare.inkfont"
        second = convert(self.old, bare, full_precision=True)
        self.assertEqual(first["core_sha256"], second["core_sha256"])
        with ZipFile(self.out) as z:
            points = json.loads(z.read(f"glyphs/{ONE}.json"))["strokes"]
            self.assertEqual(points[0][0], [0.0005, -0.0005])
            ext = {kind: json.loads(z.read(name))["entries"][ONE]
                   for kind, name in EXTENSIONS.items()}
            self.assertEqual(ext["pressure"]["values"], [[0, None], [0.5]])
            self.assertEqual(ext["timing"]["t_ms"], [[0, 10], [100]])
            self.assertEqual(ext["timing"]["pen_state"], [["down", "up"], [None]])
            self.assertEqual(ext["math"]["math_axis_em"], -0.6)
            self.assertEqual(ext["provenance"]["letter_style"], "upright")

    def test_corruption_is_rejected_and_never_publishes_output(self):
        write_legacy(self.old, corrupt=True)
        with self.assertRaisesRegex(ValueError, "成员字节校验失败"):
            convert(self.old, self.out)
        self.assertFalse(self.out.exists())

    def test_legacy_priority_does_not_rank_exchange_candidates(self):
        write_legacy(self.old, enabled_alternate=True)
        with ZipFile(self.old) as z:
            legacy_ids = [r["candidate_id"] for r in json.loads(z.read("index.json"))["candidates"]]
            self.assertLess(legacy_ids.index(TWO), legacy_ids.index(ONE))
        convert(self.old, self.out, extensions=("provenance",))
        with ZipFile(self.out) as z:
            self.assertEqual(json.loads(z.read("index.json"))["A"], [ONE, TWO])
            entries = json.loads(z.read(EXTENSIONS["provenance"]))["entries"]
            for source in entries.values():
                self.assertEqual(source["letter_style"], "upright")
                self.assertNotIn("priority", source)

    def test_out_of_range_is_reported_without_clipping(self):
        write_legacy(self.old, out_of_range=True)
        with self.assertRaisesRegex(ValueError, "U\\+0041.*±10 em"):
            convert(self.old, self.out)
        self.assertFalse(self.out.exists())

    def test_target_cannot_be_overwritten(self):
        write_legacy(self.old)
        convert(self.old, self.out)
        initial = self.out.read_bytes()
        with self.assertRaises(FileExistsError):
            convert(self.old, self.out)
        self.assertEqual(self.out.read_bytes(), initial)


if __name__ == "__main__":
    unittest.main()
