"""Measure parser-phase cancellation of the real editor worker, without GUI dispatch time."""

import argparse
import json
import threading
import time
from pathlib import Path

from inkstruct.document.package import load_package
from inkstruct.editor import mixed
from inkstruct.layout.inline import LayoutCancelled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.output.exists():
        parser.error("choose a new output file")
    project = load_package(args.project)
    original = mixed.parse_markdown
    samples = []
    try:
        for _ in range(args.repeats):
            event = threading.Event()
            stamps = {}

            def cancel(stamps=stamps, event=event):
                stamps["request"] = time.perf_counter()
                event.set()

            def parse(*a, **kw):
                timer = threading.Timer(0.005, cancel)
                timer.start()
                try:
                    return original(*a, **kw)
                finally:
                    timer.join()

            mixed.parse_markdown = parse
            start = time.perf_counter()
            cancelled = False
            try:
                mixed.build_markdown(
                    project.session,
                    0,
                    project.resolver,
                    "",
                    "",
                    project.page,
                    project.style,
                    project.flow,
                    event,
                )
            except LayoutCancelled:
                cancelled = True
            end = time.perf_counter()
            samples.append(
                {
                    "cancelled": cancelled,
                    "request_ms": (stamps["request"] - start) * 1000,
                    "ack_after_request_ms": (end - stamps["request"]) * 1000,
                }
            )
    finally:
        mixed.parse_markdown = original
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "samples": samples,
                "scope": "Actual build_markdown, embedded resources; timer requested 5 ms after parse entry; measured actual event-set to exception, not GUI signal dispatch. Small documents may complete before request.",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
