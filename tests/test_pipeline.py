import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from inkstruct.alignment import align_sample
from inkstruct.collector import check_stroke_count
from inkstruct.generate import generate_run
from inkstruct.profile import build_profile
from inkstruct.quality import audit_samples_for_rerecord
from inkstruct.samples import import_samples, iter_index, merge_indexes, replace_index_samples
from inkstruct.structures import StructureRepository, build_database


def make_structure(root: Path) -> StructureRepository:
    root.mkdir(parents=True, exist_ok=True)
    graphics = root / "graphics.txt"
    dictionary = root / "dictionary.txt"
    graphics.write_text(
        json.dumps(
            {
                "character": "十",
                "strokes": ["unused", "unused"],
                "medians": [
                    [[180, 520], [840, 520]],
                    [[510, 850], [510, 180]],
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    dictionary.write_text(
        json.dumps(
            {
                "character": "十",
                "decomposition": "十",
                "radical": "十",
                "matches": [[], []],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    database = root / "characters.sqlite3"
    build_database(graphics, dictionary, database, source_version="fixture")
    return StructureRepository(database)


def make_sample(path: Path) -> None:
    value = {
        "schema_version": "handwriting_single_v1",
        "sample_id": "fixture-sample",
        "writer_id": "writer-1",
        "character": "十",
        "codepoint": "U+5341",
        "capture": {"canvas_width": 1000, "canvas_height": 400},
        "strokes": [
            {
                "stroke_index": 0,
                "points": [
                    {"x": 300, "y": 200, "pressure": 0.4, "t_ms": 0},
                    {"x": 700, "y": 190, "pressure": 0.6, "t_ms": 100},
                ],
            },
            {
                "stroke_index": 1,
                "points": [
                    {"x": 510, "y": 80, "pressure": 0.5, "t_ms": 150},
                    {"x": 500, "y": 330, "pressure": 0.7, "t_ms": 300},
                ],
            },
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class PipelineTests(unittest.TestCase):
    def test_replace_index_samples_requires_character_matched_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_path = root / "raw-original" / "original.json"
            replacement_path = root / "raw-replacement" / "replacement.json"
            make_sample(original_path)
            make_sample(replacement_path)
            replacement_value = json.loads(replacement_path.read_text(encoding="utf-8"))
            replacement_value["sample_id"] = "replacement-sample"
            replacement_path.write_text(
                json.dumps(replacement_value, ensure_ascii=False), encoding="utf-8"
            )
            original = import_samples(root / "raw-original", "writer-1", root / "original")
            replacement = import_samples(
                root / "raw-replacement", "writer-1", root / "replacement"
            )
            report = replace_index_samples(
                Path(original["index"]),
                Path(replacement["index"]),
                "writer-1",
                {"fixture-sample"},
                root / "revised",
            )
            revised = list(iter_index(Path(report["index"])))
            self.assertEqual([sample.sample_id for sample in revised], ["replacement-sample"])
            self.assertEqual(report["replaced_characters"], "十")

    def test_stroke_count_check_and_rerecord_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = make_structure(root / "structure")
            self.assertTrue(check_stroke_count(repository, "十", 2).matches)
            self.assertFalse(check_stroke_count(repository, "十", 1).matches)
            sample_path = root / "raw" / "sample.json"
            make_sample(sample_path)
            value = json.loads(sample_path.read_text(encoding="utf-8"))
            value["strokes"] = value["strokes"][:1]
            sample_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            imported = import_samples(root / "raw", "writer-1", root / "samples")
            report = audit_samples_for_rerecord(
                Path(imported["index"]),
                repository,
                writer_id="writer-1",
                output_csv=root / "rerecord.csv",
            )
            self.assertEqual(report["rerecord_characters"], "十")
            self.assertIn("stroke_count_mismatch", report["rows"][0]["issue"])

    def test_wrong_stroke_order_is_corrected_before_profile_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = make_structure(root / "structure")
            sample_path = root / "raw" / "sample.json"
            make_sample(sample_path)
            value = json.loads(sample_path.read_text(encoding="utf-8"))
            value["strokes"] = list(reversed(value["strokes"]))
            for stroke_index, stroke in enumerate(value["strokes"]):
                stroke["stroke_index"] = stroke_index
                first_time = stroke["points"][0]["t_ms"]
                for point in stroke["points"]:
                    point["t_ms"] = stroke_index * 200 + point["t_ms"] - first_time
            sample_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            imported = import_samples(root / "raw", "writer-1", root / "samples")
            index_path = Path(imported["index"])
            sample = next(iter_index(index_path))
            aligned = align_sample(sample, repository.get("十"))
            self.assertEqual(aligned.stroke_order_status, "corrected")
            self.assertEqual(aligned.stroke_permutation, [2, 1])
            self.assertEqual(
                [mapping.user_orders for mapping in aligned.mappings], [[2], [1]]
            )
            profile, _ = build_profile(
                "writer-1", index_path, repository, root / "profiles"
            )
            self.assertEqual(profile.coverage["corrected_stroke_order_sample_count"], 1)
            self.assertEqual(profile.excluded_samples, [])
            audit = audit_samples_for_rerecord(
                index_path,
                repository,
                writer_id="writer-1",
                output_csv=root / "audit.csv",
            )
            self.assertEqual(audit["corrected_stroke_order_sample_count"], 1)
            self.assertEqual(audit["corrected_stroke_orders"][0]["standard_to_user"], [2, 1])

    def test_merge_indexes_preserves_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = root / "raw-first" / "first.json"
            second_path = root / "raw-second" / "second.json"
            make_sample(first_path)
            make_sample(second_path)
            second_value = json.loads(second_path.read_text(encoding="utf-8"))
            second_value["sample_id"] = "fixture-sample-2"
            second_path.write_text(json.dumps(second_value, ensure_ascii=False), encoding="utf-8")
            first_report = import_samples(root / "raw-first", "writer-1", root / "first")
            second_report = import_samples(root / "raw-second", "writer-1", root / "second")
            first_digest = hashlib.sha256(Path(first_report["index"]).read_bytes()).hexdigest()
            second_digest = hashlib.sha256(Path(second_report["index"]).read_bytes()).hexdigest()
            report = merge_indexes(
                [Path(first_report["index"]), Path(second_report["index"])],
                "writer-1",
                root / "merged",
            )
            self.assertEqual(report["sample_count"], 2)
            self.assertEqual(report["unique_character_count"], 1)
            self.assertEqual(report["conflict_count"], 0)
            self.assertEqual(
                hashlib.sha256(Path(first_report["index"]).read_bytes()).hexdigest(), first_digest
            )
            self.assertEqual(
                hashlib.sha256(Path(second_report["index"]).read_bytes()).hexdigest(), second_digest
            )

    def test_import_profile_generate_preserves_topology_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw"
            sample_path = source / "U+5341" / "fixture.json"
            make_sample(sample_path)
            digest_before = hashlib.sha256(sample_path.read_bytes()).hexdigest()
            repository = make_structure(root / "structure")
            report = import_samples(source, "writer-1", root / "samples")
            self.assertEqual(report["accepted_count"], 1)
            sample = next(iter_index(root / "samples" / "writer-1" / "index.jsonl"))
            aligned = align_sample(sample, repository.get("十"))
            self.assertEqual([value.mapping_type for value in aligned.mappings], ["one_to_one"] * 2)
            profile, profile_path = build_profile(
                "writer-1",
                root / "samples" / "writer-1" / "index.jsonl",
                repository,
                root / "profiles",
            )
            self.assertEqual(profile.sample_count, 1)
            manifest, run_dir = generate_run(
                "writer-1",
                ["十"],
                repository,
                profile_path,
                output_root=root / "outputs",
                run_id="fixture",
                png=False,
            )
            self.assertEqual(manifest["failed_count"], 0)
            generated = json.loads(
                (run_dir / "trajectories" / "U+5341.json").read_text(encoding="utf-8")
            )
            self.assertEqual([stroke["order"] for stroke in generated["strokes"]], [1, 2])
            resumed_manifest, resumed_dir = generate_run(
                "writer-1",
                ["十"],
                repository,
                profile_path,
                output_root=root / "outputs",
                run_id="fixture",
                png=False,
            )
            self.assertEqual(resumed_dir, run_dir)
            self.assertEqual(resumed_manifest["completed_count"], 1)
            self.assertEqual(resumed_manifest["failed_count"], 0)
            self.assertEqual(resumed_manifest["profile_version"], profile.profile_version)
            cancelled_manifest, cancelled_dir = generate_run(
                "writer-1",
                ["十"],
                repository,
                profile_path,
                output_root=root / "outputs",
                run_id="cancelled",
                png=False,
                cancelled=lambda: True,
            )
            self.assertEqual(cancelled_manifest["status"], "cancelled")
            self.assertEqual(cancelled_manifest["completed_count"], 0)
            recovered_manifest, _ = generate_run(
                "writer-1",
                ["十"],
                repository,
                profile_path,
                output_root=root / "outputs",
                run_id=cancelled_dir.name,
                png=False,
            )
            self.assertEqual(recovered_manifest["status"], "completed")
            self.assertEqual(recovered_manifest["completed_count"], 1)
            self.assertEqual(hashlib.sha256(sample_path.read_bytes()).hexdigest(), digest_before)


if __name__ == "__main__":
    unittest.main()
