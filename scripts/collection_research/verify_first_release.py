"""Verify the issued task files and the character lists used in the first release."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "configs/collection/research_v1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def character_hash(characters: list[str]) -> str:
    return digest("".join(characters).encode("utf-8"))


def read_csv(path: Path, count: int) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    characters = [row["character"] for row in rows]
    if len(rows) != count or len(set(characters)) != count:
        raise ValueError(f"{path}: expected {count} distinct characters")
    if any(len(row["character"]) != 1 or row["repeats"] != "1" for row in rows):
        raise ValueError(f"{path}: expected one code point and one recording per row")
    return rows


def check_task(name: str, count: int, budget: int, target: list[str]) -> list[str]:
    directory = PLANS / name
    plan = json.loads((directory / "plan.json").read_bytes())
    path = directory / "characters.csv"
    chars = [row["character"] for row in read_csv(path, count)]
    valid = (
        plan["schema_version"] == "inkstruct_collection_plan_v1"
        and plan["purpose"] == "training"
        and plan["csv_path"] == path.name
        and plan["target_characters"] == plan["supported_characters"] == target
        and plan["unsupported_characters"] == []
        and plan["candidate_characters"] == chars
        and set(chars) <= set(target)
        and plan["member_hashes"] == {"target": character_hash(target), "candidate": character_hash(chars)}
        and plan["files"] == {path.name: digest(path.read_bytes())}
        and plan["cost"] == {"characters": count, "repeats_per_character": 1, "standard_strokes": budget}
    )
    if not valid:
        raise ValueError(f"{name}: task membership, identity or budget differs from the issued plan")
    return chars


def main() -> None:
    target_path = ROOT / "configs/character_sets/cn-tgh-2013.json"
    target = json.loads(target_path.read_bytes())["characters"][:3500]
    starter = check_task("starter32", 32, 285, target)
    addition = check_task("add68", 68, 676, target)
    total = check_task("total100", 100, 961, target)
    if starter + addition != total:
        raise ValueError("The starter and addition lists must concatenate to the total list")
    for filename, budget, outside_count in (
        ("historical400.csv", 4178, 159),
        ("primary400_candidates.csv", 3801, 0),
    ):
        rows = read_csv(PLANS / filename, 400)
        chars = [row["character"] for row in rows]
        if chars[:100] != total or len(set(chars) - set(target)) != outside_count:
            raise ValueError(f"{filename}: incorrect candidate scope or 100-character prefix")
        if sum(int(row["standard_strokes"]) for row in rows) != budget:
            raise ValueError(f"{filename}: incorrect stroke budget")
    print("Verified 3 recording tasks and 2 research lists against the 3,500-character target.")


if __name__ == "__main__":
    main()
