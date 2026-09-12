"""Compare current and pre-fix trajectories on the bundled standard skeletons.

This deliberately uses identity global style; it is not a writer-quality study.
Run from the repository root with the local package installed or PYTHONPATH=src.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import types
from dataclasses import asdict
from pathlib import Path

from inkstruct.generate import DeterministicGenerator
from inkstruct.schemas import StyleProfile
from inkstruct.structures import graph_from_records

BASELINE = "c2c180d14701026599b1bf7095aeb490a9119efc"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=9574)
    parser.add_argument("--characters", default="", help="Optional diagnostic subset")
    parser.add_argument("--report", type=Path, default=Path("artifacts/boundary_regression.json"))
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    module = types.ModuleType("inkstruct._boundary_baseline")
    module.__package__ = "inkstruct"
    # Fixed trusted source from this repository's original commit, no downloads.
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:src/inkstruct/generate.py"], text=True, encoding="utf-8"
    )
    exec(compile(source, "baseline_generate.py", "exec"), module.__dict__)  # noqa: S102
    data = Path("third_party/makemeahanzi")
    dictionary = {
        row["character"]: row
        for row in map(json.loads, (data / "dictionary.txt").read_text(encoding="utf-8").splitlines())
    }
    profile = StyleProfile(
        "style_profile_v4", "baseline", "synthetic", "fixed", "none", 0, 0, {}, {}, {}
    )
    old = module.DeterministicGenerator(profile, "fixture", False)
    new = DeterministicGenerator(profile, "fixture", False)
    differences = []
    count = 0
    with (data / "graphics.txt").open(encoding="utf-8") as stream:
        for line in stream:
            if count >= args.limit:
                break
            graphics = json.loads(line)
            if args.characters and graphics["character"] not in args.characters:
                continue
            graph = graph_from_records(
                graphics, dictionary.get(graphics["character"]),
                simplified_characters=set(), source_version="fixture",
            )
            if asdict(old.generate(graph))["strokes"] != asdict(new.generate(graph))["strokes"]:
                differences.append(graph.character)
            count += 1
            if count % 2000 == 0:
                print(f"Checked {count} characters", flush=True)
    report = {
        "baseline": BASELINE,
        "checked_characters": count,
        "changed_characters": differences,
        "scope": "identity-style standard skeletons only, not writer profiles",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if differences or count == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
