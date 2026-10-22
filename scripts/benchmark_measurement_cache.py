"""Compare real tail edits with and without independent measurement reuse."""

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
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 3:
        parser.error("Choose a new output file and at least three observations")
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
        cache = MarkdownBuildCache()
        cache.continuation.enabled = False  # Isolate measurement reuse from prefix pagination.
        cold_ms, first = timed(inputs, cache)
        inputs["resolver"] = first["resolver"]
        position = max(i for i, c in enumerate(p.session.source) if c in "0123456789")
        observations = []
        for index in range(args.repeats):
            # Same-length actual source transaction creates a new scalar identity.
            digit = str((int(p.session.source[position]) + 1) % 10)
            p.session.apply(position, position + 1, digit)
            inputs["revision"] = index + 2
            before = cache.measurements.statistics()
            full_ms, full = timed(inputs)
            reuse_ms, reused = timed(inputs, cache)
            after = cache.measurements.statistics()
            assert cache.layouts.statistics()["hits"] == 0
            assert full["snapshot"] == reused["snapshot"]
            assert full["resolver"].selection_records() == reused["resolver"].selection_records()
            assert after["hits"] > before["hits"]
            inputs["resolver"] = reused["resolver"]
            observations.append(
                {
                    "full_worker_ms": full_ms,
                    "measured_worker_ms": reuse_ms,
                    "measurement_hits": after["hits"] - before["hits"],
                    "measurement_misses": after["misses"] - before["misses"],
                }
            )
        assert sha256(path.read_bytes()).hexdigest() == original_hash
        summary = {}
        for key in ["full_worker_ms", "measured_worker_ms"]:
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
            "cold_cached_worker_ms": cold_ms,
            "samples": observations,
            "summary": summary,
            "cache": cache.statistics(),
        }
        records.append(record)
        print(
            json.dumps(
                {k: record[k] for k in ["pages", "cold_cached_worker_ms", "summary", "cache"]}
            ),
            flush=True,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "scope": "Same-process paired full worker builds after real same-length tail edits on loaded native projects. Exact snapshot and selection parity; zero full-layout hits. Parsing, measurement dependency checks, line breaking and pagination included. No GUI dispatch, visible frames, routing or writes included. Not block/page incremental resume. Inputs remain unchanged on disk.",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
