"""Compare full, measurement-only, prefix-only and converged builds after edits."""

import argparse
import json
import math
import statistics
import threading
import time
from hashlib import sha256
from pathlib import Path

from inkstruct.document.package import load_package
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.editor.mixed import build_markdown


def timed(inputs, cache=None):
    start = time.perf_counter()
    result = build_markdown(**inputs, cache=cache)
    return (time.perf_counter() - start) * 1000, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--edit-position", choices=["head", "middle", "tail"], default="tail")
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 3:
        parser.error("Choose a new output and at least three observations")
    records = []
    for path in args.projects:
        original_hash = sha256(path.read_bytes()).hexdigest()
        p = load_package(path)
        inputs = {
            "session": p.session,
            "revision": 1,
            "resolver": p.resolver,
            "run": "",
            "symbols": "",
            "page": p.page,
            "style": p.style,
            "flow": p.flow,
            "cancelled": threading.Event(),
        }
        measured, prefix, resumed = MarkdownBuildCache(), MarkdownBuildCache(), MarkdownBuildCache()
        measured.continuation.enabled = False
        prefix.continuation.suffix_enabled = False
        timed(inputs, measured)
        timed(inputs, prefix)
        cold_ms, first = timed(inputs, resumed)
        inputs["resolver"] = first["resolver"]
        digits = [i for i, c in enumerate(p.session.source) if c in "0123456789"]
        target = {"head": 0, "middle": len(p.session.source) / 2, "tail": len(p.session.source)}[
            args.edit_position
        ]
        position = min(digits, key=lambda i: abs(i - target))
        observations = []
        for index in range(args.repeats):
            digit = str((int(p.session.source[position]) + 1) % 10)
            p.session.apply(position, position + 1, digit)
            inputs["revision"] = index + 2
            before = resumed.continuation.statistics()
            full_ms, full = timed(inputs)
            measured_ms, measurement_only = timed(inputs, measured)
            prefix_ms, prefix_only = timed(inputs, prefix)
            resumed_ms, actual = timed(inputs, resumed)
            after = resumed.continuation.statistics()
            assert (
                full["snapshot"]
                == measurement_only["snapshot"]
                == prefix_only["snapshot"]
                == actual["snapshot"]
            )
            assert full["resolver"].selection_records() == actual["resolver"].selection_records()
            assert after["reused_blocks"] > before["reused_blocks"]
            if args.edit_position != "tail":
                assert after["reused_suffix_blocks"] > before["reused_suffix_blocks"]
            assert (
                resumed.layouts.statistics()["hits"]
                == measured.layouts.statistics()["hits"]
                == prefix.layouts.statistics()["hits"]
                == 0
            )
            inputs["resolver"] = actual["resolver"]
            observations.append(
                {
                    "full_ms": full_ms,
                    "measurement_only_ms": measured_ms,
                    "prefix_only_ms": prefix_ms,
                    "resumed_ms": resumed_ms,
                    "reused_blocks": after["reused_blocks"] - before["reused_blocks"],
                    "placed_blocks": after["placed_blocks"] - before["placed_blocks"],
                    "reused_pages": after["reused_pages"] - before["reused_pages"],
                    "reused_prefix_blocks": after["reused_prefix_blocks"]
                    - before["reused_prefix_blocks"],
                    "reused_suffix_blocks": after["reused_suffix_blocks"]
                    - before["reused_suffix_blocks"],
                }
            )
        assert sha256(path.read_bytes()).hexdigest() == original_hash
        summary = {}
        for key in ["full_ms", "measurement_only_ms", "prefix_only_ms", "resumed_ms"]:
            values = sorted(v[key] for v in observations)
            summary[key] = {
                "p50": statistics.median(values),
                "p95_nearest_rank": values[math.ceil(0.95 * len(values)) - 1],
            }
        record = {
            "project": str(path),
            "sha256": original_hash,
            "pages": len(first["snapshot"].pages),
            "edit_scalar_offset": position,
            "edit_position": args.edit_position,
            "cold_cached_ms": cold_ms,
            "samples": observations,
            "summary": summary,
            "cache": resumed.statistics(),
        }
        records.append(record)
        print(json.dumps(record), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "scope": "Paired actual same-length digit edits, loaded native projects. Full worker versus measurement reuse alone versus prefix-only placement versus prefix and converged suffix. Source/geometry/diagnostic/selection parity, no full-layout hits. Includes parse, measurement checks, line breaking, checkpoint storage and pagination; excludes GUI frames, routing and writes. No source-offset rebasing, footnote or template continuation.",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
