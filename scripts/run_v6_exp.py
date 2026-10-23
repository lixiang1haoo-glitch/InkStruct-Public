"""Frozen v6 exp experiment: four development glyphs and a preselected protection set."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from report_review_repairs import curves, render_grid

from inkstruct.alignment import align_sample
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import cubic_bspline, path_length, resample
from inkstruct.profile import build_profile, load_profile
from inkstruct.samples import iter_index
from inkstruct.schemas import StyleProfile
from inkstruct.source_trajectory import TRAJECTORY_SCHEMA, source_trajectory
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import (
    SharedTransform,
    assemble,
    crossing_pairs,
    decode_component,
    invariants,
    stroke_metrics,
)
from inkstruct.v6_exp import POLICY, FullReferenceGenerator, V6ExpGenerator

DEV = "而相儒荡"


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(index, repo, excluded):
    """No prototype builder: serialize only complete, unambiguous source captures."""
    identity = hashlib.sha256(
        (sha(index) + "".join(sorted(excluded)) + repo.content_sha256()).encode()
    ).hexdigest()[:16]
    result = StyleProfile(
        "style_profile_v4",
        identity,
        "user_001",
        "2026-10-11",
        sha(index),
        0,
        0,
        {},
        {},
        {},
        trajectory_schema=TRAJECTORY_SCHEMA,
        build_identity={
            "structure_sha256": repo.content_sha256(),
            "excluded_characters": sorted(excluded),
            "policy": "complete_sources_only_no_prototypes_v1",
        },
    )
    rejected = []
    for sample in iter_index(index):
        if sample.character in excluded:
            rejected.append(
                {
                    "sample_id": sample.sample_id,
                    "character": sample.character,
                    "reason": "evaluation character group excluded before alignment/archive",
                }
            )
            continue
        try:
            graph = repo.get(sample.character)
            aligned = align_sample(sample, graph)
            source, reason = source_trajectory(sample, aligned, graph)
        except (KeyError, ValueError) as error:
            source, reason = None, str(error)
        if source is None:
            rejected.append(
                {"sample_id": sample.sample_id, "character": sample.character, "reason": reason}
            )
            continue
        if sample.writer_id != result.writer_id:
            raise ValueError("writer mismatch")
        if source.sample_id in result.source_trajectories:
            raise ValueError("duplicate sample ID")
        result.source_trajectories[source.sample_id] = source
    result.sample_count = len(result.source_trajectories)
    result.character_count = len({s.character for s in result.source_trajectories.values()})
    return result, rejected


def matched_compressed(reference, raw, report, sources):
    """Diagnostic only: freeze V6 donors/transforms, then apply legacy representation.

    Never feeds selection or V6 delivery. This isolates representation, not the
    additional effect of averaging multiple prototypes in A.
    """
    replacements = {}
    for i, stroke in enumerate(reference.strokes):
        xy = [(p.x, p.y) for p in stroke.points]
        controls = resample(xy, 8)
        count = max(24, min(128, round(path_length(controls) * 120)))
        p = resample(cubic_bspline(controls, max(64, count * 2), clip=False), count)
        replacements[i] = {
            "points": p,
            "pressure": [0.5] * len(p),
            "time": np.linspace(0, stroke.points[-1].t_ms - stroke.points[0].t_ms, len(p)).tolist(),
        }
    ids = {s.standard_stroke_id: i for i, s in enumerate(raw.strokes)}
    for part in report["components"]:
        selected = part.get("selection", {}).get("selected")
        if not selected:
            continue
        candidate = selected["candidate"]
        mapping = {s.standard_stroke_id: s for s in sources[candidate["sample_id"]].strokes}
        src = [mapping[k] for k in candidate["stroke_ids"]]
        decoded, _, _ = decode_component(src, SharedTransform(**selected["transform"]), "M")
        replacements.update(
            {ids[k]: v for k, v in zip(part["target_stroke_ids"], decoded, strict=True)}
        )
    return assemble(reference, replacements, "v6_matched_compressed_DIAGNOSTIC_ONLY")


def integrity(glyph, graph, diag, sources):
    output = {s.standard_stroke_id: s for s in glyph.strokes}
    known = set()
    maximum = 0.0
    points = 0
    for part in diag["components"]:
        selected = part.get("selection", {}).get("selected")
        if not selected:
            continue
        candidate = selected["candidate"]
        assert candidate["character"] != graph.character
        source = {s.standard_stroke_id: s for s in sources[candidate["sample_id"]].strokes}
        transform = SharedTransform(**selected["transform"])
        assert transform.sx == transform.sy
        for target_id, source_id in zip(
            part["target_stroke_ids"], candidate["stroke_ids"], strict=True
        ):
            a, b = output[target_id], source[source_id]
            expected = np.asarray(transform.apply(b.points))
            actual = np.array([(p.x, p.y) for p in a.points])
            assert actual.shape == expected.shape
            maximum = max(maximum, float(np.abs(actual - expected).max()))
            assert maximum < 1e-12
            assert [p.pressure for p in a.points] == b.pressure
            known.add(target_id)
            points += len(b.points)
    ref_points = 0
    for s in graph.strokes:
        if s.stroke_id in known:
            continue
        xy = [(p.x, p.y) for p in output[s.stroke_id].points]
        assert xy == [tuple(p) for p in s.median]
        ref_points += len(xy)
    return {
        "source_strokes": len(known),
        "reference_strokes": len(graph.strokes) - len(known),
        "source_points_retained": points,
        "reference_points_retained": ref_points,
        "max_transform_error": maximum,
        "zero_length_strokes": sum(
            path_length([(p.x, p.y) for p in s.points]) <= 1e-9 for s in glyph.strokes
        ),
    }


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    inputs = Path("artifacts/full_library_20261010/inputs")
    prior = Path("artifacts/review_repairs_20261010/validation_v1")
    index = Path("artifacts/component_aspect_20261007/user001_snapshot/index.jsonl")
    project = json.loads((prior / "original_reviews.json").read_text())
    protection = json.loads((prior / "summary.json").read_text())["control_characters"]
    # Reuse the previously hash-selected cohort: these are regression controls, not new blind tests.
    cohort = list(DEV) + sorted(
        {r["character"] for r in project["reviews"]} | set(protection) - set(DEV)
    )
    cohort = list(dict.fromkeys(cohort))
    assert len(cohort) == 78
    repo = StructureRepository(inputs / "characters.sqlite3")
    paths = [
        inputs / "characters.sqlite3",
        inputs / "user_001.json",
        index,
        prior / "summary.json",
        prior / "original_reviews.json",
    ]
    input_hash = {str(p): sha(p) for p in paths}
    implementation = [
        Path(__file__),
        Path("src/inkstruct/v6_exp.py"),
        Path("src/inkstruct/exemplar_generation.py"),
        Path("src/inkstruct/exemplar_index.py"),
        Path("src/inkstruct/fast_placement.py"),
        Path("src/inkstruct/component_views.py"),
        Path("src/inkstruct/trajectory_experiment.py"),
    ]
    write(
        root / "protocol.json",
        {
            "policy": POLICY,
            "development": list(DEV),
            "regression_protection": cohort[4:],
            "excluded_from_source_archive": sorted(cohort),
            "grouping": "all repeated captures of a character in same excluded group",
            "source_frame": "complete raw points after one glyph isotropic normalization; no averages",
            "target_frame": "complete reference centerlines, identity glyph coordinates; no learned layout",
            "parameters": "inherited frozen exemplar gates: mapping mean>=.55, standard shape<=.18, log aspect<=.7, max 16 candidates; shared sx=sy>0; length ratio .4..2.5; no new strict crossing vs reference",
            "nested_views": "需/汤 only; inherited correspondence mean<=.08 and max<=.22; flat view separately recorded",
            "baseline_caveat": "A is frozen old full-profile v4, with different donors/layout/statistical representation; M fixes V6 donor/layout and varies compression/spline only",
            "input_sha256": input_hash,
            "implementation_sha256": {str(p): sha(p) for p in implementation},
        },
    )
    sources, rejected = archive(index, repo, set(cohort))
    write(root / "source_archive.json", asdict(sources))
    write(root / "source_exclusions.json", rejected)
    assert not any(s.character in cohort for s in sources.source_trajectories.values())
    # Separate comparator only. V6 never reads this averaged v4 profile.
    training_rows = [
        line
        for line in index.read_text().splitlines()
        if json.loads(line)["sample_id"] in sources.source_trajectories
    ]
    training_index = root / "training_only_index.jsonl"
    training_index.write_text("\n".join(training_rows) + "\n")
    train_profile, train_path = build_profile(
        "user_001", training_index, repo, profile_root=root / "comparison_profiles"
    )
    training_baseline = DeterministicGenerator(train_profile, repo.metadata()["source_version"])
    write(
        root / "training_baseline.json",
        {
            "profile_sha256": sha(train_path),
            "training_index_sha256": sha(training_index),
            "samples": train_profile.sample_count,
            "characters": train_profile.character_count,
            "usage": "A_train comparator only, not used by V6",
        },
    )
    old = load_profile(inputs / "user_001.json")
    baseline = DeterministicGenerator(old, repo.metadata()["source_version"])
    v6 = V6ExpGenerator(sources, repo)
    flat = V6ExpGenerator(sources, repo, expand_nested=False)
    ref = FullReferenceGenerator(sources, repo.metadata()["source_version"])
    (root / "run/trajectories").mkdir(parents=True)
    (root / "comparisons").mkdir()
    records = []
    figures = []
    all_glyphs = {}
    for c in cohort:
        graph = repo.get(c)
        a = baseline.generate(graph)
        r = ref.generate(graph)
        v, d = v6.generate(graph)
        # The raw trace path is verified against its selected raw source, not merely by point count.
        check = integrity(v, graph, d, sources.source_trajectories)
        assert not invariants(v, graph)
        saved = Path(project["run_path"]) / f"trajectories/U+{ord(c):04X}.json"
        assert asdict(a) == json.loads(saved.read_bytes())
        m = matched_compressed(r, v, d, sources.source_trajectories)
        cv, cr, ca = curves(asdict(v)), curves(asdict(r)), curves(asdict(a))
        assert not crossing_pairs(cv) - crossing_pairs(cr)
        row = {
            "character": c,
            "group": "development" if c in DEV else "regression_protection",
            "diagnostics": d,
            "integrity": check,
            "A_extra_crossings_vs_reference": sorted(crossing_pairs(ca) - crossing_pairs(cr)),
            "v6_extra_crossings_vs_A": sorted(crossing_pairs(cv) - crossing_pairs(ca)),
            "v6_extra_crossings_vs_reference": sorted(crossing_pairs(cv) - crossing_pairs(cr)),
            "M_invariant_errors": invariants(m, graph),
            "M_extra_crossings_vs_v6": sorted(
                crossing_pairs(curves(asdict(m))) - crossing_pairs(cv)
            ),
            "representation_metrics": [
                {
                    "id": s.standard_stroke_id,
                    **stroke_metrics(
                        [(p.x, p.y) for p in ms.points], [(p.x, p.y) for p in s.points]
                    ),
                }
                for ms, s in zip(m.strokes, v.strokes, strict=True)
            ],
        }
        value = {
            "character": c,
            "A": asdict(a),
            "R": asdict(r),
            "V6": asdict(v),
            "M": asdict(m),
            "A_train": asdict(training_baseline.generate(graph)),
        }
        if c in DEV:
            f, fd = flat.generate(graph)
            value["V6_flat"] = asdict(f)
            row["flat_diagnostics"] = fd
        write(root / f"run/trajectories/U+{ord(c):04X}.json", asdict(v))
        write(root / f"comparisons/{ord(c):04X}.json", value)
        records.append(row)
        all_glyphs[c] = value
        if c in DEV:
            figures.append(
                {"title": c, "curves": [curves(value[k]) for k in ["A", "R", "V6", "M"]]}
            )
        if len(records) % 10 == 0:
            print("v6 exp", len(records), "/", len(cohort), flush=True)
    render_grid(
        figures, ["v4 原输出", "完整参考 R", "v6 exp", "固定来源压缩 M"], root / "development.png"
    )
    protected = []
    for c in ["叵", *protection[:15]]:
        v = all_glyphs[c]
        protected.append({"title": c, "curves": [curves(v[k]) for k in ["A", "V6"]]})
    for page in range(2):
        render_grid(
            protected[page * 8 : (page + 1) * 8],
            ["v4 原输出", "v6 exp"],
            root / f"protection_{page}.png",
        )
    # Evaluation-only target captures are accessed after every generation decision is frozen.
    evaluated = []
    for sample in iter_index(index):
        if sample.character not in cohort:
            continue
        graph = repo.get(sample.character)
        try:
            source, _reason = source_trajectory(sample, align_sample(sample, graph), graph)
        except (KeyError, ValueError):
            continue
        if source is None:
            continue
        row = {
            "character": sample.character,
            "sample_id": sample.sample_id,
            "source_sha256": sample.source_sha256,
            "metrics": {},
        }
        for label in ["A", "A_train", "V6", "M"]:
            glyph = all_glyphs[sample.character][label]
            row["metrics"][label] = [
                {
                    "id": s.standard_stroke_id,
                    **stroke_metrics([(p["x"], p["y"]) for p in output["points"]], s.points),
                }
                for output, s in zip(glyph["strokes"], source.strokes, strict=True)
            ]
        evaluated.append(row)
    write(root / "evaluation_only.json", evaluated)
    write(root / "records.json", records)
    summary = {
        "policy": POLICY,
        "archive_samples": sources.sample_count,
        "archive_characters": sources.character_count,
        "excluded_evaluation_characters": len(cohort),
        "n": len(records),
        "development": list(DEV),
        "source_component_count": sum(
            r["diagnostics"]["accepted_component_count"] for r in records
        ),
        "glyphs_with_source": sum(r["integrity"]["source_strokes"] > 0 for r in records),
        "source_strokes": sum(r["integrity"]["source_strokes"] for r in records),
        "reference_strokes": sum(r["integrity"]["reference_strokes"] for r in records),
        "source_points": sum(r["integrity"]["source_points_retained"] for r in records),
        "reference_points": sum(r["integrity"]["reference_points_retained"] for r in records),
        "v6_invariant_failures": 0,
        "v6_new_crossings_vs_reference": 0,
        "glyphs_new_crossing_vs_A": sum(bool(r["v6_extra_crossings_vs_A"]) for r in records),
        "zero_length_strokes": sum(r["integrity"]["zero_length_strokes"] for r in records),
        "evaluation_only_samples": len(evaluated),
        "evaluation_only_characters": len({r["character"] for r in evaluated}),
        "development_details": {
            r["character"]: {
                "accepted": r["diagnostics"]["accepted_component_count"],
                "source_strokes": r["integrity"]["source_strokes"],
                "reference_strokes": r["integrity"]["reference_strokes"],
            }
            for r in records
            if r["character"] in DEV
        },
    }
    write(root / "summary.json", summary)
    write(
        root / "v6_exp.inkreview",
        {
            "schema_version": project["schema_version"],
            "source": " ".join(DEV) + "\n\n" + " ".join(c for c in cohort if c not in DEV),
            "run_path": str((root / "run").resolve()),
            "page": project["page"],
            "style": project["style"],
            "reviews": [],
        },
    )
    write(
        root / "run/manifest.json",
        {
            "policy": POLICY,
            "archive_sha256": sha(root / "source_archive.json"),
            "assets_sha256": {
                p.name: sha(p) for p in sorted((root / "run/trajectories").iterdir())
            },
        },
    )
    assert input_hash == {str(p): sha(p) for p in paths}
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args().output)
