from __future__ import annotations

import argparse
import json
from pathlib import Path

from inkstruct.alignment import align_sample
from inkstruct.evaluate import _comparison_sheet, evaluate_writer
from inkstruct.generate import generate_run
from inkstruct.samples import iter_index
from inkstruct.structures import DEFAULT_DATABASE, StructureRepository

MODES = ("off", "stroke", "layout", "full", "adaptive")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a fixed writer-heldout ablation of the component style layer."
    )
    parser.add_argument("--writer", required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/evaluation_component_layer")
    )
    parser.add_argument("--heldout-ratio", type=float, default=0.2)
    parser.add_argument("--component-strength", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    structures = StructureRepository(args.database)
    results: dict[str, dict] = {}
    for mode in MODES:
        results[mode] = evaluate_writer(
            args.writer,
            args.index,
            structures,
            output_root=root / mode,
            heldout_ratio=args.heldout_ratio,
            component_conditioning=mode,
            component_strength=args.component_strength,
        )

    legacy = results["off"]
    adaptive = results["adaptive"]
    legacy_by_character = {item["character"]: item for item in legacy["character_metrics"]}
    adaptive_by_character = {item["character"]: item for item in adaptive["character_metrics"]}
    characters = sorted(set(legacy_by_character) & set(adaptive_by_character), key=ord)
    profile_path = root / "adaptive" / args.writer / "profiles" / args.writer / "profile.json"
    _, old_run = generate_run(
        args.writer,
        characters,
        structures,
        profile_path,
        output_root=root / "comparison_runs" / "off",
        run_id="heldout",
        png=True,
        component_conditioning="off",
    )
    _, adaptive_run = generate_run(
        args.writer,
        characters,
        structures,
        profile_path,
        output_root=root / "comparison_runs" / "adaptive",
        run_id="heldout",
        png=True,
        component_conditioning="adaptive",
        component_strength=args.component_strength,
    )

    samples = list(iter_index(args.index))
    sample_by_character = {}
    for sample in samples:
        sample_by_character.setdefault(sample.character, sample)
    user_strokes = {}
    character_rows = []
    active_characters = []
    for character in characters:
        trajectory = json.loads(
            (adaptive_run / "trajectories" / f"U+{ord(character):04X}.json").read_text(
                encoding="utf-8"
            )
        )
        sources = [stroke.get("style_source", "global") for stroke in trajectory["strokes"]]
        active = any("component" in source or "layout" in source for source in sources)
        if active:
            active_characters.append(character)
        old_distance = legacy_by_character[character]["generated_distance"]
        adaptive_distance = adaptive_by_character[character]["generated_distance"]
        character_rows.append(
            {
                "character": character,
                "legacy_distance": old_distance,
                "adaptive_distance": adaptive_distance,
                "adaptive_vs_legacy_improvement": 1.0 - adaptive_distance / max(old_distance, 1e-9),
                "component_active": active,
                "style_sources": sources,
            }
        )
        aligned = align_sample(sample_by_character[character], structures.get(character))
        user_strokes[character] = aligned.normalized_strokes

    comparison_characters = [
        row["character"]
        for row in sorted(
            (row for row in character_rows if row["component_active"]),
            key=lambda row: abs(row["adaptive_vs_legacy_improvement"]),
            reverse=True,
        )[:12]
    ]
    preview = root / "comparison.png"
    _comparison_sheet(
        preview,
        comparison_characters,
        user_strokes,
        old_run,
        adaptive_run,
        old_label="LEGACY STROKE",
        updated_label="COMPONENT ADAPTIVE",
    )

    mode_metrics = {}
    for mode, value in results.items():
        mode_metrics[mode] = {
            "generated_distance": value["generated_distance"],
            "improvement_vs_skeleton": value["relative_improvement"],
            "improvement_vs_legacy": 1.0
            - value["generated_distance"] / max(legacy["generated_distance"], 1e-9),
        }
    report = {
        "schema_version": "component_layer_ab_v1",
        "writer_id": args.writer,
        "source_index": str(args.index.resolve()),
        "source_character_count": adaptive["source_character_count"],
        "training_character_count": adaptive["training_character_count"],
        "heldout_character_count": adaptive["heldout_character_count"],
        "evaluated_character_count": adaptive["evaluated_character_count"],
        "component_active_character_count": len(active_characters),
        "component_strength": args.component_strength,
        "component_stroke_min_source_characters": 3,
        "component_geometry_min_source_characters": 1,
        "component_layout_prototype_count": adaptive["component_layout_prototype_count"],
        "component_stroke_prototype_count": adaptive["component_stroke_prototype_count"],
        "component_relation_prototype_count": adaptive["component_relation_prototype_count"],
        "component_trajectory_prototype_count": adaptive.get(
            "component_trajectory_prototype_count", 0
        ),
        "character_component_trajectory_prototype_count": adaptive.get(
            "character_component_trajectory_prototype_count", 0
        ),
        "mode_metrics": mode_metrics,
        "comparison_preview": str(preview),
        "character_metrics": character_rows,
        "skipped": adaptive["skipped"],
    }
    (root / "component_ab_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown = [
        "# Component style layer A/B",
        "",
        f"- Writer: `{args.writer}`",
        f"- Source characters: {adaptive['source_character_count']}",
        (
            f"- Held out/evaluated: {adaptive['heldout_character_count']} / "
            f"{adaptive['evaluated_character_count']}"
        ),
        f"- Component-active held-out characters: {len(active_characters)}",
        (
            f"- Component layouts/strokes in training profile: "
            f"{adaptive['component_layout_prototype_count']} / "
            f"{adaptive['component_stroke_prototype_count']}"
        ),
        (
            f"- Joint component relation prototypes: "
            f"{adaptive['component_relation_prototype_count']}"
        ),
        "",
        "| mode | distance | vs skeleton | vs legacy |",
        "|---|---:|---:|---:|",
    ]
    for mode in MODES:
        value = mode_metrics[mode]
        markdown.append(
            f"| {mode} | {value['generated_distance']:.6f} | "
            f"{value['improvement_vs_skeleton']:.2%} | "
            f"{value['improvement_vs_legacy']:.2%} |"
        )
    markdown.extend(
        [
            "",
            (
                "`adaptive` is the production default. `full`, `stroke`, and `layout` "
                "are diagnostic ablations and may over-deform sparse component contexts."
            ),
            "",
            f"Comparison preview: `{preview}`",
        ]
    )
    (root / "component_ab_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
