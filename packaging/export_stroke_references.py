from __future__ import annotations

import argparse
import json
from pathlib import Path

from inkstruct.stroke_reference import write_reference_bundle
from inkstruct.structures import StructureRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    repository = StructureRepository(args.database)
    references = {
        graph.character: [stroke.median for stroke in graph.strokes]
        for graph in repository.iter_graphs()
    }
    write_reference_bundle(args.output, references, source=repository.metadata())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "character_count": len(references),
                "stroke_count": sum(len(strokes) for strokes in references.values()),
                "bytes": args.output.stat().st_size,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
