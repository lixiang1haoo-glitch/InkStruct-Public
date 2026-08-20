from __future__ import annotations

import argparse
import json
from pathlib import Path

from inkstruct.structures import StructureRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    repository = StructureRepository(args.database)
    counts = {
        character: len(repository.get(character).strokes)
        for character in repository.characters()
    }
    payload = {
        "schema_version": "inkstruct_stroke_counts_v1",
        "source": repository.metadata(),
        "character_count": len(counts),
        "counts": counts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output.resolve()), **payload | {"counts": None}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
