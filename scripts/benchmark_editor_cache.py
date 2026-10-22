"""Compare loaded-project full worker rebuilds and content-cache hits in one process."""

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output file")
    if args.repeats < 3:
        parser.error("At least three paired observations required")
    records = []
    for path in args.projects:
        digest_before = sha256(path.read_bytes()).hexdigest()
        p = load_package(path)
        kw = {
            "session": p.session,
            "resolver": p.resolver,
            "run": "",
            "symbols": "",
            "page": p.page,
            "style": p.style,
            "flow": p.flow,
            "cancelled": threading.Event(),
            "revision": 1,
        }
        cache = MarkdownBuildCache()
        first = build_markdown(**kw, cache=cache)
        assert cache.layouts.statistics()["entries"] == 1
        observations = []
        for index in range(args.repeats):
            kw["revision"] = index + 2
            start = time.perf_counter()
            fresh = build_markdown(**kw)
            full_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            hit = build_markdown(**kw, cache=cache)
            hit_ms = (time.perf_counter() - start) * 1000
            assert hit["snapshot"] == fresh["snapshot"] and hit["document"] == fresh["document"]
            assert hit["snapshot"].pages is first["snapshot"].pages
            assert hit["resolver"].selection_records() == fresh["resolver"].selection_records()
            observations.append({"full_worker_ms": full_ms, "cache_hit_worker_ms": hit_ms})
        assert cache.layouts.statistics()["hits"] == args.repeats
        assert sha256(path.read_bytes()).hexdigest() == digest_before

        def percentile(key, observations=observations):
            values = [v[key] for v in observations]
            return {
                "p50": statistics.median(values),
                "p95_nearest_rank": sorted(values)[math.ceil(0.95 * len(values)) - 1],
            }

        record = {
            "project": str(path),
            "sha256": digest_before,
            "pages": len(first["snapshot"].pages),
            "samples": observations,
            "full_worker_ms": percentile("full_worker_ms"),
            "cache_hit_worker_ms": percentile("cache_hit_worker_ms"),
            "cache": cache.statistics(),
        }
        records.append(record)
        print(
            json.dumps(
                {k: record[k] for k in ["pages", "full_worker_ms", "cache_hit_worker_ms"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "scope": "Five paired full rebuild/cache-hit calls in one process with already loaded embedded resources, excluding GUI dispatch/paint and debounce; exact request revision, geometry and selection parity asserted. Not a new-contents incremental-layout measurement.",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
