from __future__ import annotations

import json
from pathlib import Path

from inkstruct.experiment import (
    grouped_character_folds,
    score_blind_pack,
    select_reference_characters,
)
from inkstruct.structures import StructureRepository, build_database


def _repository(root: Path) -> StructureRepository:
    graphics = root / "graphics.txt"
    dictionary = root / "dictionary.txt"
    graphics.write_text(
        "\n".join(
            json.dumps({"character": character, "strokes": [], "medians": medians})
            for character, medians in {
                "一": [[[0, 512], [1024, 512]]],
                "二": [[[0, 300], [1024, 300]], [[0, 700], [1024, 700]]],
                "三": [
                    [[0, 200], [1024, 200]],
                    [[0, 512], [1024, 512]],
                    [[0, 800], [1024, 800]],
                ],
                "十": [[[0, 512], [1024, 512]], [[512, 0], [512, 1024]]],
                "土": [[[0, 300], [1024, 300]], [[512, 0], [512, 1024]], [[0, 800], [1024, 800]]],
            }.items()
        )
        + "\n",
        encoding="utf-8",
    )
    dictionary.write_text(
        "\n".join(json.dumps({"character": value, "decomposition": value}) for value in "一二三十土")
        + "\n",
        encoding="utf-8",
    )
    database = root / "characters.sqlite3"
    build_database(graphics, dictionary, database, source_version="test")
    return StructureRepository(database)


def test_grouped_folds_never_split_duplicate_characters(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    rows = []
    for index, character in enumerate("一一二三十土"):
        rows.append(
            {
                "schema_version": "handwriting_single_v1",
                "sample_id": str(index),
                "writer_id": "writer",
                "character": character,
                "codepoint": f"U+{ord(character):04X}",
                "canvas_width": 100,
                "canvas_height": 100,
                "strokes": [],
                "source_path": "source",
                "source_sha256": str(index),
                "capture": {},
            }
        )
    index_path = tmp_path / "index.jsonl"
    index_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    folds = grouped_character_folds(index_path, repository, folds=5, seed=1001)
    flattened = [character for fold in folds for character in fold]
    assert sorted(flattened) == sorted(set("一二三十土"))
    assert len(flattened) == len(set(flattened))


def test_information_gain_selection_is_deterministic(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    candidates = list("一二三十土")
    left = select_reference_characters(
        candidates, repository, count=3, strategy="information-gain", seed=1001
    )
    right = select_reference_characters(
        candidates, repository, count=3, strategy="information-gain", seed=1001
    )
    assert left == right
    assert len(set(left)) == 3


def test_blind_score_requires_three_ratings_per_item(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "blind_key.json").write_text(
        json.dumps([{"item_id": "item_001", "left": "A", "right": "B"}]),
        encoding="utf-8",
    )
    ratings = pack / "ratings.csv"
    ratings.write_text(
        "rater_id,item_id,style_choice,overall_choice,notes\n"
        "r1,item_001,R,R,\n"
        "r2,item_001,R,L,\n"
        "r3,item_001,R,R,\n",
        encoding="utf-8",
    )
    result = score_blind_pack(pack, [ratings], seed=1001)
    assert result["rater_count"] == 3
    assert result["metrics"]["style"]["formal_item_count"] == 1
    assert result["metrics"]["style"]["method_b_preference"] == 1.0
