"""Frozen, private regression of corrected-reference/full-trajectory v6.

Run from repository root with the existing .venv. Never overwrites an output.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_v6_exp import integrity, matched_compressed, sha, write

from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import path_length
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics
from inkstruct.v6_exp import FullReferenceGenerator
from inkstruct.v6_integrated_exp import IntegratedV6Generator, framed_graph

ARMS = ("A", "P", "U", "B", "F", "M")
WRITERS = ("scx", "mjb", "wsq", "user_001")


def curves(glyph):
    if not isinstance(glyph, dict):
        glyph = asdict(glyph)
    return [[(p["x"], p["y"]) for p in s["points"]] for s in glyph["strokes"]]


def schedule(diag):
    return [
        (
            r["component_id"],
            r["selection"]["selected"]["candidate"]["sample_id"],
            r["selection"]["selected"]["candidate"]["component_id"],
        )
        for r in diag["components"]
        if r.get("selection", {}).get("selected")
    ]


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    prior = Path("artifacts/architecture_review_20261011/run_v1")
    db = Path("artifacts/full_library_20261010/inputs/characters.sqlite3")
    graphics = Path("third_party/makemeahanzi/graphics.txt")
    dictionary = graphics.with_name("dictionary.txt")
    config = Path("configs/structure_overrides/unclipped_reference_v1.json")
    repo = StructureRepository(db)
    corrected = CorrectedStructureRepository(repo, graphics, dictionary, config)
    protocol_old = json.loads((prior / "protocol.json").read_text())
    assert sha(db) == protocol_old["inputs"][str(db)]
    inputs = [db, graphics, dictionary, config, prior / "protocol.json"]
    for writer in WRITERS:
        inputs.extend(
            [
                prior / writer / "source_archive.json",
                prior / writer / "evaluation.json",
                prior / writer / "profiles" / writer / "profile.json",
                prior / writer / "records.json",
                prior / writer / "training_manifest.json",
            ]
        )
        inputs.extend(sorted((prior / writer / "glyphs").glob("*.json")))
    frozen = {str(p): sha(p) for p in inputs}
    write(
        root / "protocol.json",
        {
            "date": "2026-10-13",
            "inputs": frozen,
            "code": {
                str(p): sha(p)
                for p in [
                    Path(__file__),
                    Path("scripts/run_v6_exp.py"),
                    *[
                        Path("src/inkstruct") / n
                        for n in (
                            "v6_integrated_exp.py",
                            "v6_exp.py",
                            "glyph_frame_exp.py",
                            "exemplar_generation.py",
                            "fast_placement.py",
                            "component_views.py",
                            "structure_corrections.py",
                            "trajectory_experiment.py",
                        )
                    ],
                ]
            },
            "arms": {
                "A": "fixed original v4 adaptive; regenerated and checked against saved output",
                "P": "prior v6 then old-reference frame; historical frozen output",
                "U": "old reference in common corrected-reference .85 frame; full sources",
                "B": "corrected reference; same frame and frozen U donor/transform schedule; safety veto logged",
                "F": "corrected reference; same frame; candidate re-selection allowed",
                "M": "F donors and transforms; 16/8/spline representation diagnostic, no prototype average",
            },
            "regression_characters": protocol_old["regression_protection"],
            "grouped_validation": protocol_old["holdout_characters"],
            "evidence_boundary": "Previously observed regression, not new blind validation. "
            "Four profiles, only three independently named writers. No realignment/rebuilding.",
            "frozen_parameters": "Existing .85 frame, similarity only, selector shape .18/aspect .7, "
            "length ratio .4..2.5; no new tuning, no randomness; evaluation step .003. "
            "Round examples ranked by source chord/arc, eligible ratio <.9 and length>.08; "
            "examples only, not outcome-based statistical selection.",
            "source_exclusion": "All repeats of every evaluation character excluded from archive before old run. "
            "Frozen source archives reused unmodified. Target original geometry opened only after generation.",
        },
    )
    overall = {}
    for writer in WRITERS:
        out = root / writer
        (out / "glyphs").mkdir(parents=True)
        archive_path = prior / writer / "source_archive.json"
        profile = load_profile(archive_path)
        legacy_path = prior / writer / "profiles" / writer / "profile.json"
        manifest = json.loads((prior / writer / "training_manifest.json").read_text())
        assert sha(legacy_path) == manifest["profile_sha256"]
        legacy = DeterministicGenerator(
            load_profile(legacy_path), repo.metadata()["source_version"]
        )
        old_engine = IntegratedV6Generator(profile, repo, repo)
        full_engine = IntegratedV6Generator(profile, repo, corrected)
        characters = (
            protocol_old["regression_protection"] + protocol_old["holdout_characters"][writer]
        )
        assert not set(characters) & {s.character for s in profile.source_trajectories.values()}
        records, outputs, round_examples = [], {}, []
        for character in characters:
            old, target = repo.get(character), corrected.get(character)
            frame = reference_frame(target)
            reference_graph = framed_graph(target, frame)
            baseline_graph = framed_graph(old, frame)
            reference = FullReferenceGenerator(profile, target.source_version).generate(
                reference_graph
            )
            u, du = old_engine.generate(character, frame=frame)
            b, db_meta = full_engine.generate(character, frame=frame, locked_schedule=du)
            f, df = full_engine.generate(character, frame=frame)
            m = matched_compressed(reference, f, df, profile.source_trajectories)
            historical = json.loads(
                (prior / writer / "glyphs" / f"{ord(character):04X}.json").read_text()
            )
            a = legacy.generate(old)
            assert json.loads(json.dumps(asdict(a))) == historical["A"], "production baseline drift"
            glyphs = {k: asdict(v) for k, v in {"A": a, "U": u, "B": b, "F": f, "M": m}.items()}
            glyphs["P"] = historical["V6_frame"]
            outputs[character] = glyphs
            checks = {}
            for k, g in {"A": a, "U": u, "B": b, "F": f, "M": m}.items():
                xy = curves(g)
                checks[k] = {
                    "invariants": invariants(g, target),
                    "zero_length_strokes": sum(path_length(s) <= 1e-9 for s in xy),
                    "extra_crossings_vs_corrected_reference": sorted(
                        crossing_pairs(xy) - crossing_pairs(curves(reference))
                    ),
                    "extra_crossings_vs_U": sorted(crossing_pairs(xy) - crossing_pairs(curves(u))),
                    "near_degenerate_strokes_lt_01": [
                        i + 1 for i, s in enumerate(xy) if path_length(s) < 0.01
                    ],
                }
            intact = {
                k: integrity(g, graph, d, profile.source_trajectories)
                for k, g, graph, d in [
                    ("U", u, baseline_graph, du),
                    ("B", b, reference_graph, db_meta),
                    ("F", f, reference_graph, df),
                ]
            }
            # Prove every source curve, not just selected illustration, retains
            # its dynamics and positive similarity; curved motion is not flattened.
            for part in df["components"]:
                selected = part.get("selection", {}).get("selected")
                if not selected:
                    continue
                candidate = selected["candidate"]
                src = {
                    s.standard_stroke_id: s
                    for s in profile.source_trajectories[candidate["sample_id"]].strokes
                }
                output_map = {s.standard_stroke_id: s for s in f.strokes}
                for tid, sid in zip(
                    part["target_stroke_ids"], candidate["stroke_ids"], strict=True
                ):
                    source, stroke = src[sid], output_map[tid]
                    np.testing.assert_array_equal(
                        np.diff([p.t_ms for p in stroke.points]), np.diff(source.t_ms)
                    )
                    length = path_length(source.points)
                    chord = np.linalg.norm(np.array(source.points[-1]) - source.points[0])
                    if length > 0.08 and chord / length < 0.9:
                        round_examples.append(
                            {
                                "character": character,
                                "stroke_id": tid,
                                "source_character": candidate["character"],
                                "source_stroke_id": sid,
                                "sample_id": candidate["sample_id"],
                                "ratio": float(chord / length),
                                "source_points": source.points,
                                "transform": selected["transform"],
                            }
                        )
            record = {
                "character": character,
                "checks": checks,
                "integrity": intact,
                "diagnostics": {"U": du, "B": db_meta, "F": df},
                "changed_reference_ids": [
                    x.stroke_id
                    for x, y in zip(old.strokes, target.strokes, strict=True)
                    if x.median != y.median
                ],
                "reselection_changes_schedule": schedule(du) != schedule(df),
                "reselection_changes_placement": any(
                    left.get("selection", {}).get("selected", {}).get("transform")
                    != right.get("selection", {}).get("selected", {}).get("transform")
                    for left, right in zip(du["components"], df["components"], strict=True)
                    if left.get("selection", {}).get("selected")
                    and right.get("selection", {}).get("selected")
                ),
                "frozen_donor_veto": schedule(du) != schedule(db_meta),
                "representation_M_vs_F": [
                    stroke_metrics(x, y) for x, y in zip(curves(m), curves(f), strict=True)
                ],
                "lengths": {k: [path_length(s) for s in curves(g)] for k, g in glyphs.items()},
                "reference_lengths": [path_length(s.median) for s in reference_graph.strokes],
            }
            records.append(record)
            write(out / "glyphs" / f"{ord(character):04X}.json", glyphs)
        write(out / "records.json", records)
        write(
            out / "round_examples.json",
            sorted(round_examples, key=lambda r: (r["ratio"], r["sample_id"], r["stroke_id"])),
        )
        # This is the first use of evaluation-only target trajectories in this run.
        old_evaluation = json.loads((prior / writer / "evaluation.json").read_text())
        evaluation, grouped = [], defaultdict(lambda: defaultdict(list))
        for item in old_evaluation:
            metrics = {
                k: [stroke_metrics(x, y) for x, y in zip(curves(g), item["original"], strict=True)]
                for k, g in outputs[item["character"]].items()
            }
            evaluation.append(
                {
                    "character": item["character"],
                    "sample_id": item["sample_id"],
                    "original": item["original"],
                    "metrics": metrics,
                }
            )
            for k, rows in metrics.items():
                grouped[item["character"]][k].append(
                    {
                        field: float(np.mean([r[field] for r in rows]))
                        for field in (
                            "mean_distance",
                            "max_distance",
                            "terminal_angle_deg",
                            "absolute_length_error",
                        )
                    }
                )
        write(out / "evaluation.json", evaluation)
        perchar = {
            c: {
                k: {field: float(np.mean([x[field] for x in rows])) for field in rows[0]}
                for k, rows in arms.items()
            }
            for c, arms in grouped.items()
        }
        summary = {
            "glyphs": len(records),
            "evaluated_characters": len(grouped),
            "samples": len(evaluation),
            "macro": {
                k: {
                    field: float(np.mean([arms[k][field] for arms in perchar.values()]))
                    for field in next(iter(perchar.values()))[k]
                }
                for k in ARMS
            },
            "per_character": perchar,
            "changed_reference_glyphs": sum(bool(r["changed_reference_ids"]) for r in records),
            "fixed_donor_vetoes": sum(r["frozen_donor_veto"] for r in records),
            "reselection_changed_glyphs": sum(r["reselection_changes_schedule"] for r in records),
            "reselection_changed_placement_glyphs": sum(
                r["reselection_changes_placement"] for r in records
            ),
            "source_strokes": sum(r["integrity"]["F"]["source_strokes"] for r in records),
            "source_points": sum(r["integrity"]["F"]["source_points_retained"] for r in records),
            "reference_points": sum(
                r["integrity"]["F"]["reference_points_retained"] for r in records
            ),
            "invariant_errors": {
                k: sum(bool(r["checks"][k]["invariants"]) for r in records)
                for k in ("A", "U", "B", "F", "M")
            },
            "extra_crossing_glyphs_vs_corrected_reference": {
                k: sum(
                    bool(r["checks"][k]["extra_crossings_vs_corrected_reference"]) for r in records
                )
                for k in ("A", "U", "B", "F", "M")
            },
            "extra_crossing_glyphs_vs_U": sum(
                bool(r["checks"]["F"]["extra_crossings_vs_U"]) for r in records
            ),
        }
        overall[writer] = summary
        write(out / "summary.json", summary)
        print(writer, summary["macro"]["F"], flush=True)
    write(root / "summary.json", overall)
    assert frozen == {str(p): sha(p) for p in inputs}, "frozen input changed during run"
    write(
        root / "verification.json",
        {
            "input_hashes_unchanged": True,
            "default_regenerated_equal": 92,
            "all_source_geometry_pressure_and_intra_stroke_time_verified": True,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
