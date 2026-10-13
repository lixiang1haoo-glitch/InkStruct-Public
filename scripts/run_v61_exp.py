"""v6.1 exp A/B/C/D/E regression; immutable private output and frozen sources."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_v6_exp import sha, write

from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import stroke_metrics
from inkstruct.v61_contacts import contact_report
from inkstruct.v61_exp import PARAMETERS, V61ExpGenerator, curves

WRITERS = ("scx", "mjb", "wsq", "user_001")
ARMS = ("A", "B", "C", "D", "E")


def dict_curves(g):
    return [[(p["x"], p["y"]) for p in s["points"]] for s in g["strokes"]]


def check_integrity(engine, ctx, glyph, plan):
    used = set()
    source_points = 0
    for p in plan.values():
        for i, s, xy in zip(p.indices, engine.source(p), engine.placed(p), strict=True):
            assert curves(glyph)[i] == xy
            assert [q.pressure for q in glyph.strokes[i].points] == s.pressure
            np.testing.assert_array_equal(
                np.diff([q.t_ms for q in glyph.strokes[i].points]), np.diff(s.t_ms)
            )
            used.add(i)
            source_points += len(xy)
    for i, s in enumerate(glyph.strokes):
        if i not in used:
            assert curves(glyph)[i] == ctx.graph.strokes[i].median
    return {
        "source_strokes": len(used),
        "source_points": source_points,
        "reference_strokes": len(ctx.graph.strokes) - len(used),
        "full_source_geometry_pressure_time_exact": True,
    }


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    prior = Path("artifacts/v6_integrated_20261013/run_v2")
    archives = Path("artifacts/architecture_review_20261011/run_v1")
    protocol = json.loads((prior / "protocol.json").read_text())
    for name, digest in protocol["inputs"].items():
        assert sha(Path(name)) == digest
    db = Path("artifacts/full_library_20261010/inputs/characters.sqlite3")
    base = StructureRepository(db)
    target = CorrectedStructureRepository(
        base,
        Path("third_party/makemeahanzi/graphics.txt"),
        Path("third_party/makemeahanzi/dictionary.txt"),
        Path("configs/structure_overrides/unclipped_reference_v1.json"),
    )
    inputs = [
        prior / "protocol.json",
        *sorted(prior.glob("*/glyphs/*.json")),
        *sorted(prior.glob("*/records.json")),
        *sorted(archives.glob("*/source_archive.json")),
        *sorted(prior.glob("*/evaluation.json")),
    ]
    code = [
        Path(__file__),
        Path("src/inkstruct/v61_exp.py"),
        Path("src/inkstruct/v61_contacts.py"),
        Path("src/inkstruct/v6_integrated_exp.py"),
        Path("src/inkstruct/fast_placement.py"),
    ]
    frozen = {"inputs": {str(p): sha(p) for p in inputs}, "code": {str(p): sha(p) for p in code}}
    write(
        root / "protocol.json",
        {
            "name": "v6.1 exp",
            "baseline_commit": "901b2f3",
            **frozen,
            "parameters": PARAMETERS,
            "arms": {
                "A": "frozen v4",
                "B": "frozen v6 integrated, actually regenerated",
                "C": "candidate ranking only; B candidate pool and per-candidate transform fixed",
                "D": "B donor identities fixed; bounded whole-component translations only",
                "E": "C donors fixed; same layout method as D",
            },
            "development": "contact diagnosis on 而相儒荡叵 and old failure cases; parameters fixed from brush-scale bounds; "
            "no optimization against target originals; all 92 cases are previously observed regression",
            "constraints": "no new pools, archive, structure corrections, anisotropy, smoothing, new models or randomness; "
            "whole-glyph source reuse out of scope; missing instances remain explicit reference fallback",
            "selection_prior": "within fixed same-author/context pool, one vote per source character for terminal feature distance; "
            "no averaging output shapes; reference-separated cross-component clearance is a soft ranking cue",
            "layout": "one pass in fixed component order, bounded translation; not global optimum; "
            "no new brush/strict-crossing pairs vs B and no lost B contacts also supported by reference",
            "evaluation": "target originals opened only after all four profiles outputs freeze; previous 38 groups/40 captures; "
            "arc integration step .003, output vertices never resampled; no new blind holdout",
        },
    )
    all_records = {}
    for writer in WRITERS:
        out = root / writer
        (out / "glyphs").mkdir(parents=True)
        profile = load_profile(archives / writer / "source_archive.json")
        old_records = json.loads((prior / writer / "records.json").read_text())
        held = {r["character"] for r in old_records}
        assert not held & {s.character for s in profile.source_trajectories.values()}
        engine = V61ExpGenerator(profile, base, target)
        rows = []
        for oldrow in old_records:
            c = oldrow["character"]
            ctx = engine.prepare(c)
            saved = json.loads((prior / writer / "glyphs" / f"{ord(c):04X}.json").read_text())
            assert json.loads(json.dumps(asdict(ctx.baseline))) == saved["F"], "B drift"
            selected, slog = engine.select(ctx)
            layout_b, dlog = engine.layout(ctx, ctx.baseline_plan)
            layout_c, elog = engine.layout(ctx, selected)
            specs = {
                "C": (selected, slog, []),
                "D": (layout_b, [], dlog),
                "E": (layout_c, slog, elog),
            }
            glyphs = {"A": saved["A"], "B": saved["F"]}
            meta = {}
            intact = {}
            for label, (plan, sl, ll) in specs.items():
                glyph, m = engine.finish(ctx, plan, selection_log=sl, layout_log=ll)
                intact[label] = check_integrity(engine, ctx, glyph, plan)
                glyphs[label] = asdict(glyph)
                meta[label] = m
            contacts = {
                k: contact_report(dict_curves(g), [s.median for s in ctx.graph.strokes])
                for k, g in glyphs.items()
            }
            coverage = []
            for part in ctx.baseline_meta["components"]:
                cid = part["component_id"]
                pool = ctx.pools.get(cid, [])
                other_context = sum(
                    len(entries)
                    for key, entries in engine.v6.index.by_key.items()
                    if key.split("|")[0] == part["canonical"]
                )
                root_captures = sum(
                    s.character == part["canonical"] for s in profile.source_trajectories.values()
                )
                coverage.append(
                    {
                        "canonical": part["canonical"],
                        "component_id": cid,
                        "target_ids": part["target_stroke_ids"],
                        "eligible_pool": len(pool),
                        "same_canonical_index_entries_before_context_filter": other_context,
                        "same_canonical_whole_character_captures": root_captures,
                        "fallback_reason": part.get("fallback_reason"),
                        "baseline_donor": ctx.baseline_plan[cid].candidate
                        if cid in ctx.baseline_plan
                        else None,
                    }
                )
            row = {
                "character": c,
                "coverage": coverage,
                "baseline_meta": ctx.baseline_meta,
                "arms": meta,
                "integrity": intact,
                "contacts": contacts,
                "changed_vs_B": {
                    k: dict_curves(g) != dict_curves(glyphs["B"]) for k, g in glyphs.items()
                },
                "reference": [s.median for s in ctx.graph.strokes],
            }
            rows.append(row)
            write(out / "glyphs" / f"{ord(c):04X}.json", glyphs)
            print(
                writer,
                c,
                "CDE",
                *[int(row["changed_vs_B"][k]) for k in ("C", "D", "E")],
                flush=True,
            )
        all_records[writer] = rows
        write(out / "records.json", rows)
    summaries = {}
    # Evaluation phase starts only after the full generation corpus is fixed.
    for writer, rows in all_records.items():
        out = root / writer
        truth = json.loads((prior / writer / "evaluation.json").read_text())
        evaluated = []
        grouped = defaultdict(lambda: defaultdict(list))
        for item in truth:
            glyphs = json.loads((out / "glyphs" / f"{ord(item['character']):04X}.json").read_text())
            metrics = {
                k: [
                    stroke_metrics(x, y)
                    for x, y in zip(dict_curves(g), item["original"], strict=True)
                ]
                for k, g in glyphs.items()
            }
            evaluated.append(
                {
                    "character": item["character"],
                    "sample_id": item["sample_id"],
                    "original": item["original"],
                    "metrics": metrics,
                }
            )
            for k, ss in metrics.items():
                grouped[item["character"]][k].append(
                    {
                        f: float(np.mean([s[f] for s in ss]))
                        for f in (
                            "mean_distance",
                            "terminal_angle_deg",
                            "absolute_length_error",
                            "max_distance",
                        )
                    }
                )
        perchar = {
            c: {k: {f: float(np.mean([s[f] for s in ss])) for f in ss[0]} for k, ss in v.items()}
            for c, v in grouped.items()
        }
        summary = {
            "glyphs": len(rows),
            "evaluated_characters": len(grouped),
            "samples": len(evaluated),
            "macro": {
                k: {
                    f: float(np.mean([v[k][f] for v in perchar.values()]))
                    for f in next(iter(perchar.values()))[k]
                }
                for k in ARMS
            },
            "per_character": perchar,
            "changed_glyphs": {k: sum(r["changed_vs_B"][k] for r in rows) for k in ("C", "D", "E")},
            "source_strokes": {
                k: sum(r["arms"][k]["source_strokes"] for r in rows) for k in ("C", "D", "E")
            },
            "reference_strokes": {
                k: sum(r["arms"][k]["reference_strokes"] for r in rows) for k in ("C", "D", "E")
            },
            "brush_contacts": {
                k: sum(r["contacts"][k]["brush_contacts"] for r in rows) for k in ARMS
            },
            "extra_brush_contacts_vs_reference": {
                k: sum(r["contacts"][k]["new_brush_contacts_vs_reference"] for r in rows)
                for k in ARMS
            },
            "safety_failures": {
                k: sum(bool(any(r["arms"][k]["checks"].values())) for r in rows)
                for k in ("C", "D", "E")
            },
        }
        write(out / "evaluation.json", evaluated)
        write(out / "summary.json", summary)
        summaries[writer] = summary
    write(root / "summary.json", summaries)
    for group in ("inputs", "code"):
        assert frozen[group] == {p: sha(Path(p)) for p in frozen[group]}
    write(
        root / "verification.json",
        {
            "input_code_hashes_unchanged": True,
            "B_regenerated_exact": 92,
            "full_source_integrity_checked": True,
            "production_default_edited": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
