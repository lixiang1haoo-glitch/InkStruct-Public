from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .alignment import align_sample
from .evaluate import evaluate_writer
from .recommend import FEATURE_WEIGHTS, _feature_kind, _graph_features
from .samples import iter_index, sha256_file
from .structures import StructureRepository

DEFAULT_BUDGETS: tuple[int | str, ...] = (8, 16, 24, 32, 48, 64, 96, 128, 192, "all_train")
DEFAULT_STRATEGIES = ("random", "coverage", "information-gain")


def _stable_hash(value: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _load_config(path: Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    value = json.loads(config_path.read_text(encoding="utf-8"))
    value["_config_path"] = str(config_path)
    return value


def _git_metadata(root: Path) -> dict[str, Any]:
    safe = str(root.resolve()).replace("\\", "/")

    def git(*arguments: str) -> str:
        try:
            return subprocess.check_output(
                ["git", "-c", f"safe.directory={safe}", "-C", str(root), *arguments],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    status = git("status", "--porcelain")
    return {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "dirty": status not in {"", "unknown"},
        "status_sha256": hashlib.sha256(status.encode()).hexdigest() if status else None,
    }


def experiment_metadata(
    config: dict[str, Any], structures: StructureRepository, *, allow_dirty: bool
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    git = _git_metadata(root)
    if git["dirty"] and not allow_dirty:
        raise RuntimeError("formal experiments require a clean Git worktree; set allow_dirty for smoke runs")
    config_payload = {key: value for key, value in config.items() if not key.startswith("_")}
    index_path = Path(config["index"]).resolve()
    try:
        import torch

        torch_version = torch.__version__
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        torch_version, gpu = None, None
    return {
        "git": git,
        "config_sha256": hashlib.sha256(
            json.dumps(config_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "config_path": config.get("_config_path"),
        "index_sha256": sha256_file(index_path),
        "structure_version": structures.metadata().get("source_version"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "torch": torch_version,
        "gpu": gpu,
    }


def grouped_character_folds(
    index_path: Path,
    structures: StructureRepository,
    *,
    folds: int = 5,
    seed: int = 1001,
) -> list[list[str]]:
    if folds < 2:
        raise ValueError("at least two folds are required")
    characters = sorted({sample.character for sample in iter_index(index_path)}, key=ord)
    buckets: dict[tuple[str, int], list[str]] = {}
    for character in characters:
        graph = structures.get(character)
        root = next((item for item in graph.components if item.parent_id is None), None)
        layout = root.layout if root and root.layout else "single"
        stroke_bin = min(4, len(graph.strokes) // 4)
        buckets.setdefault((layout, stroke_bin), []).append(character)
    result: list[list[str]] = [[] for _ in range(folds)]
    offset = 0
    for key in sorted(buckets):
        values = sorted(buckets[key], key=lambda value: (_stable_hash(value, seed), ord(value)))
        for index, character in enumerate(values):
            result[(offset + index) % folds].append(character)
        offset = (offset + len(values)) % folds
    return [sorted(values, key=ord) for values in result]


def _selection_features(character: str, structures: StructureRepository) -> Counter[str]:
    return _graph_features(structures.get(character))


def select_reference_characters(
    candidates: list[str],
    structures: StructureRepository,
    *,
    count: int,
    strategy: str,
    seed: int,
) -> list[str]:
    count = min(max(1, count), len(candidates))
    if strategy == "random":
        values = list(candidates)
        random.Random(seed).shuffle(values)
        return values[:count]
    if strategy not in {"coverage", "information-gain"}:
        raise ValueError(f"unknown reference selection strategy: {strategy}")
    features = {character: _selection_features(character, structures) for character in candidates}
    coverage: Counter[str] = Counter()
    remaining = set(candidates)
    selected: list[str] = []
    while remaining and len(selected) < count:
        scored = []
        for character in remaining:
            graph = structures.get(character)
            value = 0.0
            for feature, instances in features[character].items():
                weight = FEATURE_WEIGHTS[_feature_kind(feature)]
                if strategy == "coverage":
                    value += weight * instances / (1.0 + coverage[feature])
                else:
                    before = 1.0 / math.sqrt(1.0 + coverage[feature])
                    after = 1.0 / math.sqrt(1.0 + coverage[feature] + instances)
                    value += weight * (before - after)
            effort = 1.0 + 0.03 * len(graph.strokes)
            scored.append((value / effort, -_stable_hash(character, seed), character))
        _, _, chosen = max(scored)
        selected.append(chosen)
        coverage.update(features[chosen])
        remaining.remove(chosen)
    return selected


def _write_index(path: Path, samples: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(asdict(sample), ensure_ascii=False, separators=(",", ":")) + "\n"
            for sample in samples
        ),
        encoding="utf-8",
    )


def _bootstrap_ci(values: list[float], *, seed: int, samples: int = 2000) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    generator = np.random.default_rng(seed)
    data = np.asarray(values, dtype=np.float64)
    indexes = generator.integers(0, len(data), size=(samples, len(data)))
    means = data[indexes].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _aggregate_runs(runs: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    metrics = {
        "distance": [float(run["generated_distance"]) for run in runs],
        "dtw": [float(run["extended_metrics"]["dtw"]) for run in runs],
        "sdf": [float(run["extended_metrics"]["sdf_distance"]) for run in runs],
        "style_similarity": [float(run["extended_metrics"]["style_similarity"]) for run in runs],
        "render_iou": [float(run["extended_metrics"]["render_iou"]) for run in runs],
    }
    baseline = {
        "dtw": [float(run["baseline_extended_metrics"]["dtw"]) for run in runs],
        "sdf": [float(run["baseline_extended_metrics"]["sdf_distance"]) for run in runs],
        "style_similarity": [
            float(run["baseline_extended_metrics"]["style_similarity"]) for run in runs
        ],
    }
    return {
        "run_count": len(runs),
        "metrics": {
            key: {
                "mean": float(np.mean(values)),
                "ci95": list(_bootstrap_ci(values, seed=seed + index)),
            }
            for index, (key, values) in enumerate(metrics.items())
        },
        "skeleton": {key: float(np.mean(values)) for key, values in baseline.items()},
        "structural_pass": all(run.get("evaluated_character_count", 0) > 0 for run in runs),
        "input_skipped_count": sum(int(run.get("skipped_character_count", 0)) for run in runs),
    }


def _normalized_gain(current: float, skeleton: float, full: float, *, higher: bool) -> float:
    denominator = (full - skeleton) if higher else (skeleton - full)
    numerator = (current - skeleton) if higher else (skeleton - current)
    return numerator / denominator if denominator > 1e-9 else 1.0


def find_sweet_spot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 2:
        return {"budget": None, "status": "insufficient_budget_rows"}
    full = rows[-1]
    for index, row in enumerate(rows[:-1]):
        gains = {
            "dtw": _normalized_gain(
                row["metrics"]["dtw"]["mean"], row["skeleton"]["dtw"], full["metrics"]["dtw"]["mean"], higher=False
            ),
            "sdf": _normalized_gain(
                row["metrics"]["sdf"]["mean"], row["skeleton"]["sdf"], full["metrics"]["sdf"]["mean"], higher=False
            ),
            "style_similarity": _normalized_gain(
                row["metrics"]["style_similarity"]["mean"],
                row["skeleton"]["style_similarity"],
                full["metrics"]["style_similarity"]["mean"],
                higher=True,
            ),
        }
        next_dtw = rows[index + 1]["metrics"]["dtw"]["mean"]
        current_dtw = row["metrics"]["dtw"]["mean"]
        marginal = (current_dtw - next_dtw) / max(current_dtw, 1e-9)
        conservative_lower = min(gains.values()) - 1.96 * np.std(list(gains.values())) / math.sqrt(3)
        if min(gains.values()) >= 0.95 and conservative_lower >= 0.90 and marginal < 0.02:
            return {
                "budget": row["budget"],
                "status": "found",
                "normalized_gains": gains,
                "next_budget_dtw_improvement": marginal,
            }
    return {"budget": None, "status": "not_found"}


def run_budget_sweep(config: dict[str, Any], *, allow_dirty: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    structures = StructureRepository(Path(config["database"]))
    metadata = experiment_metadata(config, structures, allow_dirty=allow_dirty)
    writer = str(config["writer_id"])
    index_path = Path(config["index"]).resolve()
    output_root = Path(config["output_root"]).resolve()
    samples = list(iter_index(index_path))
    samples_by_character: dict[str, list[Any]] = {}
    for sample in samples:
        samples_by_character.setdefault(sample.character, []).append(sample)
    folds = grouped_character_folds(
        index_path, structures, folds=int(config.get("folds", 5)), seed=int(config.get("seed", 1001))
    )
    fold_indices = [int(value) for value in config.get("fold_indices", range(len(folds)))]
    budgets = config.get("budgets", list(DEFAULT_BUDGETS))
    strategies = config.get("strategies", list(DEFAULT_STRATEGIES))
    random_seeds = config.get("random_seeds", [1001, 2002, 3003, 4004, 5005])
    runs: list[dict[str, Any]] = []
    for fold_index in fold_indices:
        heldout_list = folds[fold_index]
        heldout = set(heldout_list)
        candidates = sorted(set(samples_by_character) - heldout, key=ord)
        for strategy in strategies:
            seeds = random_seeds if strategy == "random" else [int(config.get("seed", 1001))]
            for selection_seed in seeds:
                for raw_budget in budgets:
                    budget = len(candidates) if raw_budget == "all_train" else min(int(raw_budget), len(candidates))
                    selected = select_reference_characters(
                        candidates,
                        structures,
                        count=budget,
                        strategy=strategy,
                        seed=selection_seed + fold_index,
                    )
                    selected_set = set(selected)
                    combined = [
                        sample
                        for sample in samples
                        if sample.character in selected_set or sample.character in heldout
                    ]
                    run_root = output_root / f"fold_{fold_index}" / strategy / str(selection_seed) / str(raw_budget)
                    run_index = run_root / "index.jsonl"
                    _write_index(run_index, combined)
                    result = evaluate_writer(
                        writer,
                        run_index,
                        structures,
                        output_root=run_root,
                        checkpoint=(
                            Path(config["checkpoint"])
                            if config.get("checkpoint")
                            else None
                        ),
                        component_conditioning=config.get("component_mode", "adaptive"),
                        component_strength=float(config.get("component_strength", 1.0)),
                        heldout_characters=heldout,
                        style_checkpoint=(
                            Path(config["style_checkpoint"])
                            if config.get("style_checkpoint")
                            else None
                        ),
                        confidence_threshold=config.get("confidence_threshold"),
                    )
                    runs.append(
                        {
                            "fold": fold_index,
                            "strategy": strategy,
                            "selection_seed": selection_seed,
                            "budget": raw_budget,
                            "selected_characters": "".join(selected),
                            "result": result,
                        }
                    )
    summary: dict[str, list[dict[str, Any]]] = {}
    for strategy in strategies:
        strategy_rows = []
        for budget_index, budget in enumerate(budgets):
            values = [
                run["result"]
                for run in runs
                if run["strategy"] == strategy and run["budget"] == budget
            ]
            aggregate = _aggregate_runs(values, seed=int(config.get("seed", 1001)) + budget_index)
            strategy_rows.append({"budget": budget, **aggregate})
        summary[strategy] = strategy_rows
    sweet_strategy = str(config.get("sweet_spot_strategy", "information-gain"))
    report = {
        "schema_version": "experiment_report_v1",
        "experiment": "budget_sweep",
        "metadata": metadata,
        "folds": folds,
        "evaluated_fold_indices": fold_indices,
        "budgets": budgets,
        "strategies": strategies,
        "summary": summary,
        "sweet_spot_strategy": sweet_strategy,
        "sweet_spot": find_sweet_spot(summary[sweet_strategy]),
        "duration_seconds": time.perf_counter() - started,
        "runs": runs,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "budget_sweep_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def run_ablation(config: dict[str, Any], *, allow_dirty: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    structures = StructureRepository(Path(config["database"]))
    metadata = experiment_metadata(config, structures, allow_dirty=allow_dirty)
    index_path = Path(config["index"]).resolve()
    folds = grouped_character_folds(index_path, structures, folds=5, seed=int(config.get("seed", 1001)))
    heldout = set(folds[0])
    results = {}
    summaries = {}
    root = Path(config["output_root"]).resolve()
    for variant in config["variants"]:
        if not variant.get("enabled", True):
            continue
        checkpoint = Path(variant["checkpoint"]) if variant.get("checkpoint") else None
        result = evaluate_writer(
            config["writer_id"],
            index_path,
            structures,
            output_root=root / variant["name"],
            checkpoint=checkpoint,
            component_conditioning=variant.get("component_mode", "adaptive"),
            heldout_characters=heldout,
            style_checkpoint=(
                Path(config["style_checkpoint"]) if config.get("style_checkpoint") else None
            ),
            confidence_threshold=variant.get("confidence_threshold"),
        )
        if variant.get("generation") == "skeleton":
            result = _as_skeleton_result(result)
        results[variant["name"]] = result
        summaries[variant["name"]] = _stratified_character_summary(
            result,
            structures,
            training_characters={
                sample.character
                for sample in iter_index(index_path)
                if sample.character not in heldout
            },
            seed=int(config.get("seed", 1001)),
        )
    report = {
        "schema_version": "experiment_report_v1",
        "experiment": "ablation",
        "metadata": metadata,
        "heldout_characters": "".join(sorted(heldout, key=ord)),
        "results": results,
        "summaries": summaries,
        "duration_seconds": time.perf_counter() - started,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "ablation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _as_skeleton_result(result: dict[str, Any]) -> dict[str, Any]:
    value = {**result}
    value["generated_distance"] = value["baseline_distance"]
    value["relative_improvement"] = 0.0
    value["extended_metrics"] = {**value["baseline_extended_metrics"]}
    value["character_metrics"] = [
        {
            **row,
            "generated_distance": row["baseline_distance"],
            "improvement": 0.0,
            **{
                key.removeprefix("baseline_"): metric
                for key, metric in row.items()
                if key.startswith("baseline_")
            },
        }
        for row in result["character_metrics"]
    ]
    value["generation"] = "skeleton"
    return value


def _stratified_character_summary(
    result: dict[str, Any],
    structures: StructureRepository,
    *,
    training_characters: set[str],
    seed: int,
) -> dict[str, Any]:
    training_features: Counter[str] = Counter()
    for character in training_characters:
        training_features.update(_graph_features(structures.get(character)))
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "stroke_count": {},
        "layout": {},
        "component_coverage": {},
    }
    rows = result.get("character_metrics", [])
    for row in rows:
        graph = structures.get(row["character"])
        root = next((item for item in graph.components if item.parent_id is None), None)
        layout = root.layout if root and root.layout else "single"
        stroke_group = "1-4" if len(graph.strokes) <= 4 else "5-8" if len(graph.strokes) <= 8 else "9+"
        features = [
            feature
            for feature in _graph_features(graph)
            if _feature_kind(feature).startswith("component-")
        ]
        coverage = (
            sum(training_features[feature] > 0 for feature in features) / len(features)
            if features
            else 1.0
        )
        coverage_group = "low" if coverage < 0.34 else "medium" if coverage < 0.67 else "high"
        for dimension, group in (
            ("stroke_count", stroke_group),
            ("layout", layout),
            ("component_coverage", coverage_group),
        ):
            groups[dimension].setdefault(group, []).append(row)

    def summarize(values: list[dict[str, Any]], offset: int) -> dict[str, Any]:
        metrics = {}
        for metric in ("generated_distance", "dtw", "sdf_distance", "style_similarity"):
            observed = [float(row[metric]) for row in values if metric in row]
            low, high = _bootstrap_ci(observed, seed=seed + offset)
            metrics[metric] = {
                "mean": float(np.mean(observed)) if observed else 0.0,
                "ci95": [low, high],
            }
        return {"count": len(values), "metrics": metrics}

    return {
        "overall": summarize(rows, 0),
        "strata": {
            dimension: {
                name: summarize(values, index + 1)
                for index, (name, values) in enumerate(sorted(dimension_groups.items()))
            }
            for dimension, dimension_groups in groups.items()
        },
        "failed_characters": result.get("skipped", []),
    }


def _trajectory_strokes(path: Path) -> list[list[tuple[float, float]]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return [[(float(point["x"]), float(point["y"])) for point in stroke["points"]] for stroke in value["strokes"]]


def _stratified_blind_characters(
    available: list[str], structures: StructureRepository, *, count: int, seed: int
) -> list[str]:
    generator = random.Random(seed)
    buckets: dict[tuple[str, int], list[str]] = {}
    for character in available:
        graph = structures.get(character)
        root = next((item for item in graph.components if item.parent_id is None), None)
        layout = root.layout if root and root.layout else "single"
        buckets.setdefault((layout, min(3, len(graph.strokes) // 4)), []).append(character)
    for values in buckets.values():
        generator.shuffle(values)
    selected: list[str] = []
    keys = sorted(buckets)
    while len(selected) < min(count, len(available)):
        progressed = False
        for key in keys:
            if buckets[key]:
                selected.append(buckets[key].pop())
                progressed = True
                if len(selected) >= min(count, len(available)):
                    break
        if not progressed:
            break
    return selected


def run_blind_pack(config: dict[str, Any]) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    seed = int(config.get("seed", 1001))
    generator = random.Random(seed)
    run_a, run_b = Path(config["run_a"]), Path(config["run_b"])
    samples = list(iter_index(Path(config["index"])))
    sample_by_character = {}
    for sample in samples:
        sample_by_character.setdefault(sample.character, sample)
    available = sorted(
        character
        for character in sample_by_character
        if (run_a / "trajectories" / f"U+{ord(character):04X}.json").is_file()
        and (run_b / "trajectories" / f"U+{ord(character):04X}.json").is_file()
    )
    output = Path(config["output_root"]).resolve()
    items = output / "items"
    items.mkdir(parents=True, exist_ok=True)
    structures = StructureRepository(Path(config["database"]))
    characters = _stratified_blind_characters(
        available,
        structures,
        count=int(config.get("count", 60)),
        seed=seed,
    )
    key = []
    rating_rows = ["rater_id,item_id,style_choice,overall_choice,notes\n"]
    for index, character in enumerate(characters, 1):
        aligned = align_sample(sample_by_character[character], structures.get(character))
        options = [
            _trajectory_strokes(run_a / "trajectories" / f"U+{ord(character):04X}.json"),
            _trajectory_strokes(run_b / "trajectories" / f"U+{ord(character):04X}.json"),
        ]
        order = [0, 1]
        generator.shuffle(order)
        panels = [aligned.normalized_strokes, options[order[0]], options[order[1]]]
        image = Image.new("RGB", (768, 292), "white")
        draw = ImageDraw.Draw(image)
        for column, (label, strokes) in enumerate(zip(("STYLE REFERENCE", "OPTION L", "OPTION R"), panels)):
            left = column * 256
            draw.text((left + 8, 8), label, fill="#111827")
            for stroke in strokes:
                points = [(left + 16 + x * 224, 52 + y * 224) for x, y in stroke]
                if len(points) >= 2:
                    draw.line(points, fill="#111827", width=3, joint="curve")
        item_id = f"item_{index:03d}"
        image.save(items / f"{item_id}.png")
        key.append({"item_id": item_id, "character": character, "left": "A" if order[0] == 0 else "B", "right": "A" if order[1] == 0 else "B"})
        rating_rows.append(f",{item_id},,,\n")
    (output / "blind_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "ratings.csv").write_text("".join(rating_rows), encoding="utf-8-sig")
    manifest = {
        "schema_version": "blind_pack_v1",
        "seed": seed,
        "count": len(key),
        "stratified": True,
        "items": str(items),
        "key": "blind_key.json",
        "ratings": "ratings.csv",
        "method_a": config.get("method_a", "v4"),
        "method_b": config.get("method_b", "v5"),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def score_blind_pack(pack: Path, rating_files: list[Path], *, seed: int = 1001) -> dict[str, Any]:
    pack = Path(pack).resolve()
    key = {
        row["item_id"]: row
        for row in json.loads((pack / "blind_key.json").read_text(encoding="utf-8"))
    }
    observations: dict[str, dict[str, dict[str, float]]] = {
        "style": {item_id: {} for item_id in key},
        "overall": {item_id: {} for item_id in key},
    }
    raters = set()
    for path in rating_files:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                item_id = row.get("item_id", "")
                rater = row.get("rater_id", "").strip()
                if item_id not in key or not rater:
                    continue
                raters.add(rater)
                for metric, column in (("style", "style_choice"), ("overall", "overall_choice")):
                    choice = row.get(column, "").strip().upper()
                    if choice == "TIE":
                        observations[metric][item_id][rater] = 0.5
                    elif choice in {"L", "R"}:
                        observations[metric][item_id][rater] = (
                            1.0 if key[item_id]["left" if choice == "L" else "right"] == "B" else 0.0
                        )
    metrics = {}
    for offset, (metric, items) in enumerate(observations.items()):
        exploratory = [value for values in items.values() for value in values.values()]
        formal = [
            value
            for values in items.values()
            if len(values) >= 3
            for value in values.values()
        ]
        low, high = _bootstrap_ci(formal, seed=seed + offset)
        preference = float(np.mean(formal)) if formal else None
        exploratory_preference = float(np.mean(exploratory)) if exploratory else None
        metrics[metric] = {
            "exploratory_method_b_preference": exploratory_preference,
            "exploratory_item_count": sum(bool(values) for values in items.values()),
            "exploratory_rating_count": len(exploratory),
            "exploratory_choice_counts": {
                "method_a": sum(value == 0.0 for value in exploratory),
                "tie": sum(value == 0.5 for value in exploratory),
                "method_b": sum(value == 1.0 for value in exploratory),
            },
            "method_b_preference": preference,
            "ci95": [low, high] if formal else None,
            "formal_item_count": sum(len(values) >= 3 for values in items.values()),
            "rating_count": len(formal),
            "production_gate_passed": bool(
                preference is not None and preference >= 0.60 and low > 0.50
            ),
            "ideal_70_percent_reached": bool(preference is not None and preference >= 0.70),
        }
    report = {
        "schema_version": "blind_rating_report_v1",
        "rater_count": len(raters),
        "minimum_ratings_per_item": 3,
        "status": (
            "formal"
            if all(value["formal_item_count"] > 0 for value in metrics.values())
            else "exploratory_insufficient_independent_raters"
        ),
        "production_decision": (
            "eligible"
            if all(value["production_gate_passed"] for value in metrics.values())
            else "insufficient_independent_raters"
            if any(value["formal_item_count"] == 0 for value in metrics.values())
            else "keep_v4"
        ),
        "metrics": metrics,
    }
    (pack / "rating_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inkstruct experiment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("budget-sweep", "ablate", "blind-pack"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        if name != "blind-pack":
            command.add_argument("--allow-dirty", action="store_true")
    blind_score = subparsers.add_parser("blind-score")
    blind_score.add_argument("--pack", type=Path, required=True)
    blind_score.add_argument("--ratings", type=Path, nargs="+", required=True)
    blind_score.add_argument("--seed", type=int, default=1001)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "blind-score":
        result = score_blind_pack(args.pack, args.ratings, seed=args.seed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    config = _load_config(args.config)
    if args.command == "budget-sweep":
        result = run_budget_sweep(config, allow_dirty=args.allow_dirty)
    elif args.command == "ablate":
        result = run_ablation(config, allow_dirty=args.allow_dirty)
    else:
        result = run_blind_pack(config)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    console_result = (
        result
        if args.command in {"blind-pack"}
        else {
            "schema_version": result.get("schema_version"),
            "experiment": result.get("experiment"),
            "duration_seconds": result.get("duration_seconds"),
            "sweet_spot": result.get("sweet_spot"),
            "output_root": config.get("output_root"),
        }
    )
    print(json.dumps(console_result, ensure_ascii=False, indent=2))
    return 0
