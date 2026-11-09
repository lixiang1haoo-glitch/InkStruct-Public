from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .evaluate import compare_profile_update, evaluate_run, evaluate_writer
from .generate import generate_run
from .profile import build_profile, load_profile
from .quality import audit_samples_for_rerecord
from .recommend import (
    accepted_profile_characters,
    plan_target_coverage_tiers,
    recommend_characters,
    save_recommendations,
    save_target_coverage_tiers,
)
from .samples import import_samples, iter_index, merge_indexes, replace_index_samples
from .structures import (
    CHARACTER_PACKAGES,
    DEFAULT_DATABASE,
    StructureRepository,
    build_database,
    export_character_packages,
    package_characters,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _source_version(source_dir: Path) -> str:
    try:
        resolved = str(source_dir.resolve()).replace("\\", "/")
        return subprocess.check_output(
            [
                "git",
                "-c",
                f"safe.directory={resolved}",
                "-C",
                str(source_dir),
                "rev-parse",
                "HEAD",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _emit(value: dict) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inkstruct", description="InkStruct structure-prior handwriting generator"
    )
    parser.add_argument("--version", action="version", version="InkStruct 0.2.0")
    groups = parser.add_subparsers(dest="group", required=True)

    from .document.cli import add_document_parser
    add_document_parser(groups)

    structures = groups.add_parser(
        "structures", help="build and inspect the character graph database"
    )
    structures_commands = structures.add_subparsers(dest="command", required=True)
    structure_build = structures_commands.add_parser("build")
    source_default = PROJECT_ROOT / "third_party" / "makemeahanzi"
    structure_build.add_argument("--graphics", type=_path, default=source_default / "graphics.txt")
    structure_build.add_argument(
        "--dictionary", type=_path, default=source_default / "dictionary.txt"
    )
    structure_build.add_argument("--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE)
    structure_build.add_argument(
        "--simplified",
        type=_path,
        default=PROJECT_ROOT / "data" / "CASIA_CHINESE" / "character_dict.pkl",
    )
    structure_info = structures_commands.add_parser("info")
    structure_info.add_argument("--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE)
    structure_packages = structures_commands.add_parser(
        "export-packages", help="export GB2312 and non-GB2312 character manifests"
    )
    structure_packages.add_argument(
        "--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE
    )
    structure_packages.add_argument("--output-dir", type=_path, required=True)

    samples = groups.add_parser("samples", help="import and validate raw online samples")
    sample_commands = samples.add_subparsers(dest="command", required=True)
    sample_import = sample_commands.add_parser("import")
    sample_import.add_argument("source", type=_path)
    sample_import.add_argument("--writer", required=True)
    sample_import.add_argument(
        "--destination", type=_path, default=PROJECT_ROOT / "artifacts" / "samples"
    )
    sample_merge = sample_commands.add_parser("merge")
    sample_merge.add_argument("indexes", nargs="+", type=_path)
    sample_merge.add_argument("--writer", required=True)
    sample_merge.add_argument(
        "--destination", type=_path, default=PROJECT_ROOT / "artifacts" / "samples_merged"
    )
    sample_audit = sample_commands.add_parser("audit")
    sample_audit.add_argument("--writer", required=True)
    sample_audit.add_argument("--index", type=_path)
    sample_audit.add_argument("--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE)
    sample_audit.add_argument("--confidence-threshold", type=float, default=0.5)
    sample_audit.add_argument("--output", type=_path)
    sample_replace = sample_commands.add_parser("replace")
    sample_replace.add_argument("index", type=_path)
    sample_replace.add_argument("replacement_index", type=_path)
    sample_replace.add_argument("--writer", required=True)
    sample_replace.add_argument("--audit-report", type=_path, required=True)
    sample_replace.add_argument(
        "--destination", type=_path, default=PROJECT_ROOT / "artifacts" / "samples_revised"
    )

    profile = groups.add_parser("profile", help="build cached user style profiles")
    profile_commands = profile.add_subparsers(dest="command", required=True)
    profile_build = profile_commands.add_parser("build")
    profile_build.add_argument("--writer", required=True)
    profile_build.add_argument("--index", type=_path)
    profile_build.add_argument("--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE)
    profile_build.add_argument("--destination", type=_path, default=PROJECT_ROOT / "profiles")
    profile_build.add_argument("--style-checkpoint", type=_path)
    profile_build.add_argument(
        "--retain-source-trajectories", action="store_true",
        help="retain lossless normalized captures for diagnostics; generation stays unchanged",
    )

    collect = groups.add_parser("collect", help="active sample selection")
    collect_commands = collect.add_subparsers(dest="command", required=True)
    recommend = collect_commands.add_parser("recommend")
    recommend.add_argument("--writer", required=True)
    recommend.add_argument("--count", type=int, default=10)
    recommend.add_argument("--anchors", type=int, default=20)
    recommend.add_argument("--target-repeats", type=int, default=3)
    recommend.add_argument("--index", type=_path)
    recommend.add_argument("--profile", type=_path)
    recommend.add_argument("--common-characters", type=_path)
    recommend.add_argument("--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE)
    recommend.add_argument("--output", type=_path)
    recommend.add_argument(
        "--strategy",
        choices=("coverage", "information-gain"),
        default="coverage",
    )
    coverage_tiers = collect_commands.add_parser(
        "coverage-tiers", help="plan five nested target-coverage collection tiers"
    )
    coverage_tiers.add_argument("--writer", required=True)
    coverage_tiers.add_argument("--index", type=_path, required=True)
    coverage_tiers.add_argument("--profile", type=_path)
    coverage_target = coverage_tiers.add_mutually_exclusive_group()
    coverage_target.add_argument("--target-characters", type=_path)
    coverage_target.add_argument("--target-package", choices=CHARACTER_PACKAGES)
    coverage_tiers.add_argument(
        "--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE
    )
    coverage_tiers.add_argument("--output", type=_path)

    generate = groups.add_parser("generate", help="generate topology-preserving trajectories")
    generate.add_argument("--writer", required=True)
    target = generate.add_mutually_exclusive_group(required=True)
    target.add_argument("--text")
    target.add_argument("--all-supported", action="store_true")
    generate.add_argument("--profile", type=_path)
    generate.add_argument("--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE)
    generate.add_argument("--output-root", type=_path, default=PROJECT_ROOT / "outputs")
    generate.add_argument("--run-id")
    generate.add_argument("--no-png", action="store_true")
    generate.add_argument("--checkpoint", type=_path)
    generate.add_argument(
        "--confidence-threshold",
        type=float,
        help="override the writer-disjoint calibrated checkpoint threshold",
    )
    generate.add_argument("--no-component-conditioning", action="store_true")
    generate.add_argument(
        "--component-mode",
        choices=("off", "stroke", "layout", "full", "adaptive"),
        default="adaptive",
    )
    generate.add_argument("--component-strength", type=float, default=1.0)
    generate.add_argument("--trajectory-mode", choices=("legacy", "source-raw", "source-simplified"),
                          default="legacy", help="opt-in complete-source component generation")
    generate.add_argument("--source-profile", type=_path, help="separate retained-source profile for the same writer")
    generate.add_argument("--reviewed-geometry", action="store_true", help="opt-in hash-locked source and reviewed crossing repairs")
    generate.add_argument("--source-observed", action="store_true", help="explicitly prioritize captured whole glyphs; reconstruction, not held-out inference")
    generate.add_argument("--source-nested-views", action="store_true", help="enable validated nested component views")
    generate.add_argument("--source-characters", type=_path, help="UTF-8 training characters; exclude all other donor characters")

    evaluate = groups.add_parser("evaluate", help="validate a generated run")
    evaluation_target = evaluate.add_mutually_exclusive_group(required=True)
    evaluation_target.add_argument("--run", type=_path)
    evaluation_target.add_argument("--writer")
    evaluate.add_argument("--database", type=_path, default=PROJECT_ROOT / DEFAULT_DATABASE)
    evaluate.add_argument("--index", type=_path)
    evaluate.add_argument("--heldout-ratio", type=float, default=0.2)
    evaluate.add_argument("--checkpoint", type=_path)
    evaluate.add_argument("--style-checkpoint", type=_path)
    evaluate.add_argument("--model-confidence-threshold", type=float)
    evaluate.add_argument("--update-index", type=_path)
    evaluate.add_argument("--reference-profile", type=_path)
    evaluate.add_argument("--heldout-count", type=int, default=12)
    evaluate.add_argument("--no-component-conditioning", action="store_true")
    evaluate.add_argument(
        "--component-mode",
        choices=("off", "stroke", "layout", "full", "adaptive"),
        default="adaptive",
    )
    evaluate.add_argument("--component-strength", type=float, default=1.0)
    evaluate.add_argument(
        "--output-root", type=_path, default=PROJECT_ROOT / "artifacts" / "evaluation"
    )

    groups.add_parser(
        "train", help="train or smoke-test the hierarchical residual model", add_help=False
    )
    groups.add_parser(
        "experiment",
        help="run reproducible budget, ablation, and blind studies",
        add_help=False,
    )

    groups.add_parser("collector", help="launch the standalone trajectory collector")
    groups.add_parser("generator", help="launch the standalone style generator")
    groups.add_parser("desktop", help="deprecated alias for the standalone style generator")
    from .v63_cli import add_v63_commands
    add_v63_commands(groups)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, forwarded = parser.parse_known_args(argv)
    if forwarded and args.group not in {"train", "experiment", "collector", "generator", "desktop"}:
        parser.error("unrecognized arguments: " + " ".join(forwarded))
    if args.group == "document":
        from .document.cli import run_document_command
        code, report = run_document_command(args)
        _emit(report)
        return code
    if args.group == "v63":
        from .v63_cli import run_v63_command
        try:
            result = run_v63_command(args)
        except (OSError, ValueError, KeyError) as error:
            parser.exit(2, f"v6.3: {error}\n")
        if isinstance(result, int):
            return result
        _emit(result)
        return 0
    if args.group == "structures" and args.command == "build":
        report = build_database(
            args.graphics,
            args.dictionary,
            args.database,
            simplified_path=args.simplified,
            source_version=_source_version(args.graphics.parent),
        )
        _emit(report)
        return 0
    if args.group == "structures" and args.command == "info":
        repository = StructureRepository(args.database)
        _emit({**repository.metadata(), "character_count": repository.count()})
        return 0
    if args.group == "structures" and args.command == "export-packages":
        result = export_character_packages(
            StructureRepository(args.database), args.output_dir
        )
        report_path = args.output_dir / "character_packages_report.json"
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _emit({**result, "report": str(report_path)})
        return 0
    if args.group == "samples" and args.command == "import":
        _emit(import_samples(args.source, args.writer, args.destination))
        return 0
    if args.group == "samples" and args.command == "merge":
        _emit(merge_indexes(args.indexes, args.writer, args.destination))
        return 0
    if args.group == "samples" and args.command == "audit":
        index = args.index or PROJECT_ROOT / "artifacts" / "samples" / args.writer / "index.jsonl"
        output = (
            args.output
            or PROJECT_ROOT / "artifacts" / "collection" / args.writer / "rerecord_current.csv"
        )
        _emit(
            audit_samples_for_rerecord(
                index,
                StructureRepository(args.database),
                writer_id=args.writer,
                output_csv=output,
                confidence_threshold=args.confidence_threshold,
            )
        )
        return 0
    if args.group == "samples" and args.command == "replace":
        audit = json.loads(Path(args.audit_report).read_text(encoding="utf-8"))
        superseded_ids = {
            sample_id
            for row in audit.get("rows", [])
            for sample_id in str(row.get("source_sample_ids", "")).split()
        }
        _emit(
            replace_index_samples(
                args.index,
                args.replacement_index,
                args.writer,
                superseded_ids,
                args.destination,
            )
        )
        return 0
    if args.group == "profile" and args.command == "build":
        index = args.index or PROJECT_ROOT / "artifacts" / "samples" / args.writer / "index.jsonl"
        profile, path = build_profile(
            args.writer,
            index,
            StructureRepository(args.database),
            args.destination,
            args.style_checkpoint,
            retain_source_trajectories=args.retain_source_trajectories,
        )
        _emit(
            {
                "profile": str(path),
                "profile_version": profile.profile_version,
                "sample_count": profile.sample_count,
                "character_count": profile.character_count,
                "prototype_count": len(profile.prototypes),
                "component_layout_count": len(profile.component_layouts),
                "character_layout_count": len(profile.character_layouts),
                "component_stroke_count": len(profile.component_strokes),
                "component_relation_count": len(profile.component_relations),
                "component_trajectory_count": len(profile.component_trajectories),
                "character_component_trajectory_count": len(
                    profile.character_component_trajectories
                ),
                "excluded_count": len(profile.excluded_samples),
                "factorized_style": profile.factorized_style is not None,
            }
        )
        return 0
    if args.group == "collect" and args.command == "recommend":
        index = args.index or PROJECT_ROOT / "artifacts" / "samples" / args.writer / "index.jsonl"
        profile = args.profile or PROJECT_ROOT / "profiles" / args.writer / "profile.json"
        result = recommend_characters(
            StructureRepository(args.database),
            count=args.count,
            index_path=index,
            profile_path=profile,
            anchor_count=args.anchors,
            target_repeats=args.target_repeats,
            strategy=args.strategy,
            **(
                {"common_characters_path": args.common_characters} if args.common_characters else {}
            ),
        )
        output = (
            args.output
            or PROJECT_ROOT / "artifacts" / "collection" / args.writer / "recommendations.json"
        )
        result = save_recommendations(result, output)
        _emit({**result, "output": str(output.resolve())})
        return 0
    if args.group == "collect" and args.command == "coverage-tiers":
        profile_path = args.profile or PROJECT_ROOT / "profiles" / args.writer / "profile.json"
        profile = load_profile(profile_path)
        samples = list(iter_index(args.index))
        repository = StructureRepository(args.database)
        target_characters = None
        if args.target_characters:
            target_characters = list(
                dict.fromkeys(
                    character
                    for character in args.target_characters.read_text(encoding="utf-8")
                    if not character.isspace()
                )
            )
        elif args.target_package:
            target_characters = package_characters(repository, args.target_package)
        result = plan_target_coverage_tiers(
            repository,
            profile,
            accepted_characters=accepted_profile_characters(args.index, profile),
            sampled_characters={sample.character for sample in samples},
            target_characters=target_characters,
            candidate_characters=(
                set(target_characters) if args.target_package else None
            ),
        )
        result["target_package"] = args.target_package
        output = (
            args.output
            or PROJECT_ROOT
            / "artifacts"
            / "collection"
            / args.writer
            / (args.target_package or "all_supported")
            / "target_coverage_tiers_report.json"
        )
        result = save_target_coverage_tiers(result, output)
        _emit({**result, "recommendations": [], "output": str(output.resolve())})
        return 0
    if args.group == "generate":
        repository = StructureRepository(args.database)
        characters = repository.characters() if args.all_supported else list(args.text)
        profile = args.profile or PROJECT_ROOT / "profiles" / args.writer / "profile.json"
        result, run_dir = generate_run(
            args.writer,
            characters,
            repository,
            profile,
            output_root=args.output_root,
            run_id=args.run_id,
            png=not args.no_png,
            checkpoint=args.checkpoint,
            confidence_threshold=args.confidence_threshold,
            component_conditioning=(
                "off" if args.no_component_conditioning else args.component_mode
            ),
            component_strength=args.component_strength,
            trajectory_mode=args.trajectory_mode,
            source_profile_path=args.source_profile,
            source_nested_views=args.source_nested_views,
            source_observed=args.source_observed,
            reviewed_geometry=args.reviewed_geometry,
            source_characters_path=args.source_characters,
        )
        _emit({**result, "run_directory": str(run_dir)})
        return 0 if not result["failed_count"] else 2
    if args.group == "evaluate":
        repository = StructureRepository(args.database)
        if args.run:
            result = evaluate_run(args.run, repository)
        else:
            index = (
                args.index or PROJECT_ROOT / "artifacts" / "samples" / args.writer / "index.jsonl"
            )
            if args.update_index or args.reference_profile:
                if not args.update_index or not args.reference_profile:
                    parser.error("--update-index and --reference-profile must be used together")
                result = compare_profile_update(
                    args.writer,
                    index,
                    args.update_index,
                    args.reference_profile,
                    repository,
                    output_root=args.output_root,
                    heldout_count=args.heldout_count,
                )
            else:
                result = evaluate_writer(
                    args.writer,
                    index,
                    repository,
                    output_root=args.output_root,
                    heldout_ratio=args.heldout_ratio,
                    checkpoint=args.checkpoint,
                    style_checkpoint=args.style_checkpoint,
                    confidence_threshold=args.model_confidence_threshold,
                    component_conditioning=(
                        "off" if args.no_component_conditioning else args.component_mode
                    ),
                    component_strength=args.component_strength,
                )
        _emit(result)
        failures = result.get("structural_failure_count", 0)
        return 0 if not failures else 2
    if args.group == "train":
        from .train import main as train_main

        return train_main(forwarded)
    if args.group == "experiment":
        from .experiment import main as experiment_main

        return experiment_main(forwarded)
    if args.group == "collector":
        from .collector import main as collector_main

        return collector_main(forwarded)
    if args.group in {"generator", "desktop"}:
        from .generator_app import main as generator_main

        return generator_main(forwarded)
    raise AssertionError("unhandled command")


if __name__ == "__main__":
    sys.exit(main())
