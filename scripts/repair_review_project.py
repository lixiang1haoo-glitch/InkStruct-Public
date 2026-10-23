#!/usr/bin/env python3
"""Opt-in candidate delivery, exact-baseline checks and fixed-policy regression.

Outputs must be a new ignored directory. Original review labels are retained in
an audit sidecar; changed assets deliberately start with no inherited verdict.
No production generator, profile or input trajectory is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import numpy as np

from inkstruct.control_repair import POLICY, ControlRepairGenerator
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import invariants


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def curve_stats(glyph):
    result = []
    for stroke in glyph.strokes:
        xy = np.array([(p.x, p.y) for p in stroke.points])
        chord = xy[-1] - xy[0]
        span = float(np.linalg.norm(chord))
        bow = np.abs((xy[:, 0] - xy[0, 0]) * chord[1] - (xy[:, 1] - xy[0, 1]) * chord[0])
        result.append(
            {
                "id": stroke.standard_stroke_id,
                "length": path_length(xy.tolist()),
                "max_chord_distance": float(bow.max() / max(span, 1e-9)),
                "chord_length": span,
            }
        )
    return result


def run(args):
    project = json.loads(args.project.read_bytes())
    old_run = Path(project["run_path"])
    chars = sorted(
        c
        for c in set(project["source"])
        if (old_run / f"trajectories/U+{ord(c):04X}.json").exists()
    )
    bad = {r["character"] for r in project["reviews"] if r["rating"] == "bad"}
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    trajectories = root / "run/trajectories"
    trajectories.mkdir(parents=True)
    (root / "comparisons").mkdir()
    inputs = [args.project, args.profile, args.db, *args.additional_profiles]
    hashes = {str(p.resolve()): digest(p) for p in inputs}
    code = [Path(__file__), Path("src/inkstruct/control_repair.py")]
    write(
        root / "protocol.json",
        {
            "policy": POLICY,
            "input_sha256": hashes,
            "code_sha256": {str(p): digest(p) for p in code},
            "parameters": {
                "straight_chord_arc_ratio": 0.97,
                "sparse_support": 4,
                "mode": "adaptive",
                "strength": 1.0,
                "randomness": "none",
            },
            "split": "14 marked glyphs = development/regression; remainder = fixed-policy protection, not quality-labelled holdout",
            "delivery_scope": "only old bad-rated assets; all others byte-identical",
            "cross_writer_scope": "same marked glyphs plus 64 hash-selected protection glyphs; no preference transfer",
        },
    )
    repo = StructureRepository(args.db)
    version = repo.metadata()["source_version"]
    summaries, rows, modified = [], [], []
    controls = sorted(
        set(chars) - {r["character"] for r in project["reviews"]},
        key=lambda c: hashlib.sha256(("review-repair-v1:" + c).encode()).hexdigest(),
    )[:64]
    for profile_path in [args.profile, *args.additional_profiles]:
        profile = load_profile(profile_path)
        primary = profile_path == args.profile
        engine = ControlRepairGenerator(profile, version)
        baseline = DeterministicGenerator(profile, version)
        selected = (
            chars
            if primary
            else sorted(set(controls) | {r["character"] for r in project["reviews"]})
        )
        start = len(rows)
        for c in selected:
            graph = repo.get(c)
            a = baseline.generate(graph)
            b = engine.generate(graph)
            diag = engine.last_diagnostics[c]
            errors = invariants(b, graph)
            if errors:
                raise ValueError((profile.writer_id, c, errors))
            changed = asdict(a) != asdict(b)
            row = {
                "writer": profile.writer_id,
                "character": c,
                "changed": changed,
                "diagnostics": diag,
                "A": curve_stats(a),
                "B": curve_stats(b),
            }
            rows.append(row)
            if primary:
                old = old_run / f"trajectories/U+{ord(c):04X}.json"
                if asdict(a) != json.loads(old.read_bytes()):
                    raise ValueError(f"Baseline mismatch: {c}")
                dest = trajectories / old.name
                if c in bad and changed:
                    write(dest, asdict(b))
                    modified.append(c)
                else:
                    shutil.copyfile(old, dest)
                    assert digest(old) == digest(dest)
                if c in {r["character"] for r in project["reviews"]} or c in controls:
                    write(
                        root / f"comparisons/{ord(c):04X}.json",
                        {"character": c, "A": asdict(a), "B": asdict(b), "diagnostics": diag},
                    )
            if len(rows) % 50 == 0:
                print(f"{profile.writer_id}: {len(rows) - start}/{len(selected)}", flush=True)
        subset = rows[start:]
        summaries.append(
            {
                "writer": profile.writer_id,
                "n": len(subset),
                "changed": sum(r["changed"] for r in subset),
                "fallback": sum(bool(r["diagnostics"]["fallback"]) for r in subset),
                "proposal_new_crossing": sum(
                    bool(r["diagnostics"]["new_crossings"]) for r in subset
                ),
                "proposal_new_degenerate": sum(
                    bool(r["diagnostics"]["new_degenerate_ids"]) for r in subset
                ),
                "proposal_invariant_failure": sum(
                    bool(r["diagnostics"]["invariant_errors"]) for r in subset
                ),
                "output_invariant_failure": 0,
            }
        )
    # Retain all historical labels separately. A changed asset is not automatically good.
    write(root / "original_reviews.json", project)
    project["run_path"] = str(trajectories.parent)
    project["reviews"] = [r for r in project["reviews"] if r["character"] not in modified]
    write(root / "修复候选.inkreview", project)
    write(root / "metrics.json", rows)
    write(
        root / "summary.json",
        {
            "cohorts": summaries,
            "delivery_changed": modified,
            "delivery_unchanged": len(chars) - len(modified),
            "primary_baseline_equal": len(chars),
            "original_labels_unchanged": True,
            "control_characters": controls,
            "not_fixed": sorted(bad - set(modified)),
            "caution": "changed is not visually accepted; no raw target originals for the 14 marked characters",
        },
    )
    write(
        root / "run/manifest.json",
        {
            "policy": POLICY,
            "profile": str(args.profile.resolve()),
            "source_run": str(old_run),
            "project_sha256": hashes[str(args.project.resolve())],
            "modified_characters": modified,
            "status": "opt-in candidates, re-review required",
            "assets_sha256": {p.name: digest(p) for p in sorted(trajectories.iterdir())},
        },
    )
    if hashes != {str(p.resolve()): digest(p) for p in inputs}:
        raise ValueError("Input files changed during experiment")
    print(json.dumps(summaries, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--additional-profiles", nargs="*", type=Path, default=[])
    run(parser.parse_args())
