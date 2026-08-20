import json
import tempfile
import unittest
from pathlib import Path

from inkstruct.structures import StructureRepository, build_database, graph_from_records


class StructureTests(unittest.TestCase):
    def test_component_tree_assigns_variant_role_and_strokes(self):
        medians = [[[100 + index * 80, 800], [140 + index * 80, 650]] for index in range(5)]
        graph = graph_from_records(
            {"character": "江", "medians": medians},
            {
                "character": "江",
                "decomposition": "⿰氵工",
                "radical": "氵",
                "matches": [[0], [0], [0], [1], [1]],
            },
            simplified_characters={"江"},
            source_version="fixture",
        )
        self.assertEqual(graph.components[0].layout, "⿰")
        left = next(component for component in graph.components if component.path == "root.0")
        right = next(component for component in graph.components if component.path == "root.1")
        self.assertEqual((left.glyph_variant, left.canonical, left.role), ("氵", "水", "left"))
        self.assertEqual(left.stroke_ids, ["s1", "s2", "s3"])
        self.assertEqual((right.glyph_variant, right.role), ("工", "right"))
        self.assertFalse(graph.component_warnings)

    def test_build_and_read_small_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graphics = root / "graphics.txt"
            dictionary = root / "dictionary.txt"
            database = root / "characters.sqlite3"
            graphics.write_text(
                json.dumps(
                    {
                        "character": "十",
                        "strokes": ["unused", "unused"],
                        "medians": [
                            [[200, 500], [800, 500]],
                            [[500, 800], [500, 200]],
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
            report = build_database(graphics, dictionary, database, source_version="fixture")
            self.assertEqual(report["accepted_count"], 1)
            repository = StructureRepository(database)
            graph = repository.get("十")
            self.assertEqual([stroke.order for stroke in graph.strokes], [1, 2])
            self.assertEqual(graph.source_version, "fixture")
            self.assertEqual(repository.characters(), ["十"])


if __name__ == "__main__":
    unittest.main()
