import json
import tempfile
import unittest
from pathlib import Path

from inkstruct.recommend import (
    plan_target_coverage_tiers,
    recommend_characters,
    save_recommendations,
    save_target_coverage_tiers,
)
from inkstruct.schemas import StyleProfile
from inkstruct.structures import StructureRepository, build_database


class RecommendTests(unittest.TestCase):
    def test_component_recommendation_writes_collector_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graphics = root / "graphics.txt"
            dictionary = root / "dictionary.txt"
            common = root / "common.txt"
            medians = [[[100 + index * 80, 800], [140 + index * 80, 650]] for index in range(5)]
            graphics.write_text(
                "\n".join(
                    json.dumps({"character": character, "medians": medians}, ensure_ascii=False)
                    for character in "江河"
                )
                + "\n",
                encoding="utf-8",
            )
            dictionary.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "character": "江",
                                "decomposition": "⿰氵工",
                                "matches": [[0], [0], [0], [1], [1]],
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "character": "河",
                                "decomposition": "⿰氵可",
                                "matches": [[0], [0], [0], [1], [1]],
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            common.write_text("江河\n", encoding="utf-8")
            database = root / "characters.sqlite3"
            build_database(
                graphics,
                dictionary,
                database,
                simplified_path=common,
                source_version="fixture",
            )
            result = recommend_characters(
                StructureRepository(database),
                count=2,
                common_characters_path=common,
                anchor_count=0,
            )
            self.assertEqual(result["schema_version"], "component_collection_recommendation_v2")
            self.assertTrue(result["frequency_weighted"])
            self.assertEqual(result["database_character_count"], 2)
            self.assertEqual(set(result["new_characters"]), {"江", "河"})
            self.assertTrue(any("氵" in item["components"] for item in result["recommendations"]))
            self.assertTrue(
                all("database_frequency_score" in item for item in result["recommendations"])
            )
            information_gain_a = recommend_characters(
                StructureRepository(database),
                count=2,
                common_characters_path=common,
                anchor_count=0,
                strategy="information-gain",
            )
            information_gain_b = recommend_characters(
                StructureRepository(database),
                count=2,
                common_characters_path=common,
                anchor_count=0,
                strategy="information-gain",
            )
            self.assertEqual(information_gain_a, information_gain_b)
            self.assertEqual(
                information_gain_a["schema_version"],
                "component_collection_recommendation_v3",
            )
            self.assertFalse(information_gain_a["frequency_weighted"])
            saved = save_recommendations(result, root / "recommendations.json")
            self.assertTrue(Path(saved["files"]["collector_csv"]).is_file())
            self.assertTrue(Path(saved["files"]["character_text"]).is_file())

            profile = StyleProfile(
                schema_version="style_profile_v4",
                profile_version="fixture",
                writer_id="fixture_writer",
                created_at="2026-08-21T00:00:00+00:00",
                source_index_sha256="0" * 64,
                sample_count=0,
                character_count=0,
                global_style={},
                prototypes={},
                coverage={},
            )
            tier_plan = plan_target_coverage_tiers(
                StructureRepository(database),
                profile,
                accepted_characters=set(),
                thresholds=(100.0,),
            )
            self.assertEqual(tier_plan["recommended_character_count"], 2)
            self.assertEqual(tier_plan["tiers"][0]["projected_score"], 100.0)
            self.assertEqual(
                [item["character"] for item in tier_plan["recommendations"]],
                [item["character"] for item in plan_target_coverage_tiers(
                    StructureRepository(database),
                    profile,
                    accepted_characters=set(),
                    thresholds=(100.0,),
                )["recommendations"]],
            )
            tier_saved = save_target_coverage_tiers(
                tier_plan, root / "target_coverage_tiers_report.json"
            )
            master_csv = Path(tier_saved["files"]["master_csv"])
            self.assertTrue(master_csv.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(len(tier_saved["files"]["incremental_collector_csvs"]), 1)


if __name__ == "__main__":
    unittest.main()
