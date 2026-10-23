"""Staged, private A/B/C experiment: prepare -> develop -> evaluate.

No production generator switches are changed. Target handwriting is passed to
the scorer only after cross-character candidate selection and generation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from inkstruct.component_style import component_context_key
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import bbox, path_length, resample
from inkstruct.profile import build_profile, load_profile
from inkstruct.samples import iter_index, sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import (
    assemble,
    crossing_pairs,
    decode_component,
    invariants,
    shared_transform,
    stroke_metrics,
)

INDEX = Path("artifacts/samples/scx/index.jsonl")
SOURCE_PROFILE = Path("profiles/source_v1_20261007/scx/profile.json")
ORIGINAL_PROFILE = Path("profiles/scx/profile.json")
DATABASE = Path("artifacts/structures/characters.sqlite3")


def save(path, value):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite experimental artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def rank(value):
    return hashlib.sha256(("raw-transform-v1:" + value).encode()).hexdigest()


def initialize(output):
    protocol = json.loads(Path("configs/experiments/raw_transform_v1.json").read_text())
    characters = sorted({sample.character for sample in iter_index(INDEX)})
    protocol["split"] = {
        c: ("dev" if c in "岛尴" else
            "train" if int(rank(c)[:8], 16) % 10 < 6 else
            "dev" if int(rank(c)[:8], 16) % 10 < 8 else "test")
        for c in characters
    }
    for name, path in [("source_index_sha256", INDEX),
                       ("original_profile_sha256", ORIGINAL_PROFILE),
                       ("source_profile_sha256", SOURCE_PROFILE)]:
        protocol[name] = sha256_file(path)
    save(output / "protocol.json", protocol)


def curves(glyph):
    return [[(p.x, p.y) for p in s.points] for s in glyph.strokes]


def ordered_ids(graph, component):
    wanted = set(component.stroke_ids)
    return [s.stroke_id for s in graph.strokes if s.stroke_id in wanted]


def descriptor(graph, component):
    medians = {s.stroke_id: s.median for s in graph.strokes}
    points = [resample(medians[k], 16) for k in ordered_ids(graph, component)]
    box = bbox([p for s in points for p in s])
    span = max(box[2] - box[0], box[3] - box[1], 1e-9)
    center = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
    return (np.asarray(points) - center) / span


def key(graph, component):
    return component_context_key(graph, component) + f"|{len(component.stroke_ids)}"


def leaf_components(graph):
    return [c for c in graph.components if c.path != "root" and not c.children_ids
            and len(c.stroke_ids) >= 2 and c.confidence >= 0.8]


def select_candidate(target_graph, target_component, donor_pool, graphs):
    """No target capture/profile argument exists at this boundary."""
    target_descriptor = descriptor(target_graph, target_component)
    box = target_component.bbox
    target_aspect = max(box[2] - box[0], 1e-8) / max(box[3] - box[1], 1e-8)
    candidates = []
    for donor in donor_pool.get(key(target_graph, target_component), []):
        if donor["character"] == target_graph.character:
            raise AssertionError("target character leaked into donor pool")
        graph = graphs[donor["character"]]
        component = next(c for c in graph.components if c.component_id == donor["component_id"])
        shape = float(np.linalg.norm(descriptor(graph, component) - target_descriptor, axis=2).mean())
        box = component.bbox
        aspect = max(box[2] - box[0], 1e-8) / max(box[3] - box[1], 1e-8)
        aspect_error = abs(math.log(aspect / target_aspect))
        if shape > 0.18 or aspect_error > 0.7:
            continue
        score = shape + 0.1 * aspect_error + 0.03 * (1 - donor["confidence"])
        candidates.append({**donor, "score": score, "standard_shape_error": shape,
                           "standard_log_aspect_error": aspect_error})
    return sorted(candidates, key=lambda d: (d["score"], rank(d["sample_id"] + d["component_id"])))


def prepare(output):
    protocol = json.loads((output / "protocol.json").read_text())
    for name, path in [("source_index_sha256", INDEX), ("original_profile_sha256", ORIGINAL_PROFILE),
                       ("source_profile_sha256", SOURCE_PROFILE)]:
        if sha256_file(path) != protocol[name]:
            raise ValueError(f"changed input {path}")
    repository = StructureRepository(DATABASE)
    source = load_profile(SOURCE_PROFILE).source_trajectories
    by_character = defaultdict(list)
    for sample in source.values():
        by_character[sample.character].append(sample)
    samples = {c: min(v, key=lambda s: rank(s.sample_id)) for c, v in by_character.items()}
    graphs = {c: repository.get(c) for c in samples}
    train_path = output / "train_index.jsonl"
    with train_path.open("x", encoding="utf-8") as stream:
        for sample in iter_index(INDEX):
            if protocol["split"][sample.character] == "train":
                stream.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")
    train_profile, train_profile_path = build_profile("scx", train_path, repository,
                                                     output / "profiles_train")
    donors = defaultdict(list)
    for character, sample in samples.items():
        if protocol["split"][character] != "train":
            continue
        graph = graphs[character]
        strokes = {s.standard_stroke_id: s for s in sample.strokes}
        for component in leaf_components(graph):
            ids = ordered_ids(graph, component)
            confidence = float(np.mean([strokes[s].confidence for s in ids]))
            box = bbox([p for s in ids for p in strokes[s].points])
            if confidence < 0.55 or min(box[2] - box[0], box[3] - box[1]) < 1e-5:
                continue
            donors[key(graph, component)].append({
                "sample_id": sample.sample_id, "character": character,
                "component_id": component.component_id, "stroke_ids": ids,
                "source_sha256": sample.source_sha256, "confidence": confidence,
            })
    plan, rejected = [], []
    for split in ("dev", "test"):
        targets = sorted([c for c in samples if protocol["split"][c] == split], key=rank)
        same = ([c for c in "岛尴" if c in targets] if split == "dev" else [])
        same += [c for c in targets if c not in same]
        for c in same[:protocol["same_counts"][split]]:
            plan.append({"id": f"same-{split}-U+{ord(c):04X}", "task": "same", "split": split,
                         "character": c, "target_sample_id": samples[c].sample_id})
        available = defaultdict(list)
        for character in targets:
            slots = []
            for component in leaf_components(graphs[character]):
                candidates = select_candidate(graphs[character], component, donors, graphs)
                if candidates:
                    slots.append((component, candidates))
            if not slots:
                rejected.append({"character": character, "split": split,
                                 "reason": "no compatible training leaf-component exemplar"})
                continue
            # One component per target character. Prefer supported contexts;
            # round-robin contexts below avoids an all-亻 or all-口 experiment.
            component, candidates = max(slots, key=lambda pair: (len(pair[1]), pair[0].path))
            context = key(graphs[character], component)
            available[context].append({
                "id": f"cross-{split}-U+{ord(character):04X}", "task": "cross", "split": split,
                "character": character, "target_sample_id": samples[character].sample_id,
                "component_id": component.component_id,
                "target_stroke_ids": ordered_ids(graphs[character], component), "context": context,
                "candidate": candidates[0], "ranked_candidates": candidates,
            })
        groups = [available[k] for k in sorted(available)]
        picked = []
        while groups and len(picked) < protocol["cross_counts"][split]:
            for group in groups:
                if group and len(picked) < protocol["cross_counts"][split]:
                    picked.append(group.pop(0))
            groups = [g for g in groups if g]
        plan.extend(picked)
    save(output / "plan.json", {"protocol_sha256": sha256_file(output / "protocol.json"),
         "train_profile": str(train_profile_path), "train_profile_sha256": sha256_file(train_profile_path),
         "train_index_sha256": sha256_file(train_path), "train_profile_samples": train_profile.sample_count,
         "structure_sha256": sha256_file(DATABASE), "structure_content_sha256": repository.content_sha256(),
         "selection_thresholds": {"standard_shape_error": 0.18, "standard_log_aspect_error": 0.7},
         "created_at": datetime.now(UTC).isoformat(), "tasks": plan, "rejected": rejected})
    print(json.dumps({f"{task}_{split}": sum(t["task"] == task and t["split"] == split for t in plan)
                      for task in ("same", "cross") for split in ("dev", "test")}))


class Experiment:
    def __init__(self, output):
        self.output = output
        self.protocol = json.loads((output / "protocol.json").read_text())
        self.plan = json.loads((output / "plan.json").read_text())
        if sha256_file(output / "protocol.json") != self.plan["protocol_sha256"]:
            raise ValueError("protocol changed after preparation")
        for path, expected in [
            (INDEX, self.protocol["source_index_sha256"]),
            (SOURCE_PROFILE, self.protocol["source_profile_sha256"]),
            (ORIGINAL_PROFILE, self.protocol["original_profile_sha256"]),
            (Path(self.plan["train_profile"]), self.plan["train_profile_sha256"]),
            (DATABASE, self.plan["structure_sha256"]),
        ]:
            if sha256_file(path) != expected:
                raise ValueError(f"experiment input changed: {path}")
        self.repository = StructureRepository(DATABASE)
        self.sources = load_profile(SOURCE_PROFILE).source_trajectories
        version = self.repository.metadata()["source_version"]
        self.original = DeterministicGenerator(load_profile(ORIGINAL_PROFILE), version, "adaptive", 1.0)
        self.training = DeterministicGenerator(load_profile(Path(self.plan["train_profile"])),
                                               version, "adaptive", 1.0)

    def generate(self, task, epsilon, include_xy=True):
        graph = self.repository.get(task["character"])
        base = (self.original if task["task"] == "same" else self.training).generate(graph)
        base_curves = curves(base)
        if task["task"] == "same":
            source = self.sources[task["target_sample_id"]]
            donor_strokes = source.strokes
            indices = list(range(len(base.strokes)))
            donor = {"sample_id": source.sample_id, "character": source.character,
                     "source_sha256": source.source_sha256, "scope": "self reconstruction"}
        else:
            donor = task["candidate"]
            if self.protocol["split"][donor["character"]] != "train":
                raise AssertionError("held-out donor")
            source = self.sources[donor["sample_id"]]
            donor_map = {s.standard_stroke_id: s for s in source.strokes}
            donor_strokes = [donor_map[k] for k in donor["stroke_ids"]]
            indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in task["target_stroke_ids"]]
        target_box = bbox([p for i in indices for p in base_curves[i]])
        variants, provenance = {"A": base}, {}
        modes = ("similarity", "bounded_xy") if include_xy and task["task"] == "cross" else ("similarity",)
        for transform_mode in modes:
            transform = shared_transform([s.points for s in donor_strokes], target_box,
                                         transform_mode, self.protocol["anisotropy_ratio_cap"])
            suffix = "_xy" if transform_mode == "bounded_xy" else ""
            for representation in ("B", "C", "M"):
                decoded, retained, fallback = decode_component(donor_strokes, transform,
                                                                representation, epsilon)
                label = representation + suffix
                variants[label] = assemble(base, dict(zip(indices, decoded, strict=True)), label)
                provenance[label] = {"donor": donor, "transform": asdict(transform),
                                     "target_bbox": target_box, "source_indices": retained,
                                     "fallback_reason": fallback, "epsilon_output_units": epsilon}
        for label, glyph in variants.items():
            errors = invariants(glyph, graph)
            if errors:
                raise ValueError(f"{task['id']} {label}: {errors}")
        return graph, indices, variants, provenance

    def score(self, task, graph, indices, variants, provenance):
        # Cross-target capture is read only HERE, after candidate choice and
        # all transformations. It never determines a target box or candidate.
        reference = self.sources[task["target_sample_id"]]
        reference_map = {s.standard_stroke_id: s for s in reference.strokes}
        reference_curves = [reference_map[s.stroke_id].points for s in graph.strokes]
        if task["task"] == "same":
            reference_curves = curves(variants["B"])
        reference_crossings = crossing_pairs(reference_curves)
        base_crossings = crossing_pairs(curves(variants["A"]))
        scored = {}
        for label, glyph in variants.items():
            predicted = curves(glyph)
            per_stroke = []
            for i in indices:
                row = stroke_metrics(predicted[i], reference_curves[i])
                length = path_length(reference_curves[i])
                turns = graph.strokes[i].signature.turns
                categories = []
                if length < 0.08:
                    categories.append("short")
                if length >= 0.5 and turns >= 1:
                    categories.append("long_compound")
                if turns == 0:
                    categories.append("straight")
                if row["hook"]:
                    categories.append("terminal_hook")
                if turns >= 1 and not row["hook"]:
                    categories.append("bend_or_curve")
                row.update({"stroke_id": graph.strokes[i].stroke_id, "order": i + 1,
                            "categories": categories})
                per_stroke.append(row)
            intersections = crossing_pairs(predicted)
            primary_keys = ("mean_distance", "max_distance", "absolute_length_error",
                            "terminal_angle_deg", "endpoint_error", "hook_length_error")
            aggregate = {}
            for name in primary_keys:
                values = [r[name] for r in per_stroke if r[name] is not None]
                aggregate[name] = float(np.mean(values)) if values else None
            reference_length = sum(path_length(reference_curves[i]) for i in indices)
            aggregate.update({
                "length_ratio": sum(path_length(predicted[i]) for i in indices) / reference_length,
                "selected_points": sum(len(predicted[i]) for i in indices),
                "new_crossing_pairs_vs_reference": sorted(intersections - reference_crossings),
                "new_crossing_pairs_vs_A": sorted(intersections - base_crossings),
                "missing_crossing_pairs_vs_reference": sorted(reference_crossings - intersections),
                "invariant_errors": invariants(glyph, graph),
                "degenerate_stroke_ids": [graph.strokes[i].stroke_id for i in indices
                                          if path_length(predicted[i]) < 1e-4],
                "severely_shortened_stroke_ids": [graph.strokes[i].stroke_id for i in indices
                    if path_length(predicted[i]) < 0.1 * path_length(reference_curves[i])],
                "hook_count": sum(r["hook"] is not None for r in per_stroke),
            })
            # Matched-candidate fidelity: transform donor raw -> generated.
            b_label = "B_xy" if label.endswith("_xy") else "B"
            donor_reference = curves(variants[b_label])
            fidelity = [stroke_metrics(predicted[i], donor_reference[i]) for i in indices]
            aggregate["donor_fidelity_mean_distance"] = float(np.mean([r["mean_distance"] for r in fidelity]))
            # Component-wide evaluation alignment removes placement without
            # altering internal stroke proportions or the stored output.
            target_box = bbox([p for i in indices for p in reference_curves[i]])
            try:
                align = shared_transform([predicted[i] for i in indices], target_box)
                shape_rows = [stroke_metrics(align.apply(predicted[i]), reference_curves[i]) for i in indices]
                aggregate["component_shape_distance"] = float(np.mean([r["mean_distance"] for r in shape_rows]))
            except ValueError:
                aggregate["component_shape_distance"] = None
            scored[label] = {"aggregate": aggregate, "strokes": per_stroke}
        return {"task": task, "indices": indices, "provenance": provenance,
                "reference_source_sha256": reference.source_sha256,
                "reference": reference_curves,
                "variants": {label: asdict(glyph) for label, glyph in variants.items()},
                "scores": scored}

    def develop(self):
        tasks = [t for t in self.plan["tasks"] if t["split"] == "dev"]
        grid = []
        for epsilon in self.protocol["epsilon_grid"]:
            rows, fractions, fallbacks = [], [], 0
            for task in tasks:
                _, indices, variants, provenance = self.generate(task, epsilon, False)
                b, c = curves(variants["B"]), curves(variants["C"])
                rows.extend(stroke_metrics(c[i], b[i]) for i in indices)
                fractions.append(sum(len(c[i]) for i in indices) / sum(len(b[i]) for i in indices))
                fallbacks += provenance["C"]["fallback_reason"] is not None
            metrics = {name: float(np.percentile([r[name] for r in rows if r[name] is not None], 95))
                       for name in ("max_distance", "absolute_length_error", "terminal_angle_deg")}
            passed = (metrics["max_distance"] <= 0.004 + 1e-10
                      and metrics["absolute_length_error"] <= 0.02
                      and metrics["terminal_angle_deg"] <= 5)
            grid.append({"epsilon": epsilon, "p95": metrics, "passes": passed,
                         "mean_retained_fraction": float(np.mean(fractions)), "fallback_count": fallbacks})
            print("dev epsilon", epsilon, metrics, "passed", passed, flush=True)
        chosen = max([row["epsilon"] for row in grid if row["passes"]], default=0.0)
        save(self.output / "frozen_parameters.json", {"epsilon": chosen, "grid": grid,
             "plan_sha256": sha256_file(self.output / "plan.json"),
             "selection_data": "development only; no test targets scored",
             "code_sha256": sha256_file(Path("src/inkstruct/trajectory_experiment.py"))})
        print("frozen epsilon", chosen, flush=True)

    def evaluate(self):
        parameters = json.loads((self.output / "frozen_parameters.json").read_text())
        if parameters["plan_sha256"] != sha256_file(self.output / "plan.json"):
            raise ValueError("plan changed after development")
        if parameters["code_sha256"] != sha256_file(Path("src/inkstruct/trajectory_experiment.py")):
            raise ValueError("geometry changed after parameter freeze")
        records = []
        for count, task in enumerate(self.plan["tasks"], 1):
            graph, indices, variants, provenance = self.generate(task, parameters["epsilon"])
            result = self.score(task, graph, indices, variants, provenance)
            save(self.output / "cases" / f"{task['id']}.json", result)
            records.append({"task": task, "scores": result["scores"], "provenance": provenance})
            if count % 16 == 0:
                print(f"evaluated {count}/{len(self.plan['tasks'])}", flush=True)
        summaries = {}
        for task_name in ("same", "cross"):
            for split in ("dev", "test"):
                selected = [r for r in records if r["task"]["task"] == task_name and r["task"]["split"] == split]
                labels = list(selected[0]["scores"]) if selected else []
                results = {}
                for label in labels:
                    rows = [r["scores"][label]["aggregate"] for r in selected]
                    numeric = {}
                    for name in ("mean_distance", "max_distance", "absolute_length_error", "terminal_angle_deg",
                                 "hook_length_error", "endpoint_error", "component_shape_distance",
                                 "donor_fidelity_mean_distance", "selected_points"):
                        values = [r[name] for r in rows if r[name] is not None]
                        numeric[name] = {"mean": float(np.mean(values)), "median": float(np.median(values)),
                                         "p95": float(np.percentile(values, 95)), "n": len(values)} if values else None
                    results[label] = {"n": len(rows), "metrics": numeric,
                        "characters_with_new_crossings_vs_reference": sum(bool(r["new_crossing_pairs_vs_reference"]) for r in rows),
                        "characters_with_new_crossings_vs_A": sum(bool(r["new_crossing_pairs_vs_A"]) for r in rows),
                        "invariant_failures": sum(bool(r["invariant_errors"]) for r in rows),
                        "degenerate_characters": sum(bool(r["degenerate_stroke_ids"]) for r in rows),
                        "severely_shortened_characters": sum(bool(r["severely_shortened_stroke_ids"]) for r in rows),
                        "fallbacks": sum(bool(r["provenance"].get(label, {}).get("fallback_reason")) for r in selected)}
                    if label != "A":
                        delta = [r["scores"][label]["aggregate"]["mean_distance"]
                                 - r["scores"]["A"]["aggregate"]["mean_distance"] for r in selected]
                        results[label]["paired_vs_A"] = {"better": sum(d < -1e-9 for d in delta),
                            "worse": sum(d > 1e-9 for d in delta), "mean_delta": float(np.mean(delta))}
                summaries[f"{task_name}_{split}"] = results
        save(self.output / "results.json", {"parameters_sha256": sha256_file(self.output / "frozen_parameters.json"),
             "summaries": summaries, "records": records})
        with (self.output / "per_character.csv").open("x", encoding="utf-8-sig", newline="") as stream:
            names = ["task", "split", "character", "path", "mean_distance", "max_distance",
                     "absolute_length_error", "terminal_angle_deg", "hook_length_error", "selected_points"]
            writer = csv.DictWriter(stream, fieldnames=names)
            writer.writeheader()
            for r in records:
                for label, score in r["scores"].items():
                    writer.writerow({"task": r["task"]["task"], "split": r["task"]["split"],
                                     "character": r["task"]["character"], "path": label,
                                     **{k: score["aggregate"][k] for k in names[4:]}})
        print(json.dumps(summaries, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("init", "prepare", "develop", "evaluate"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "init":
        initialize(args.output)
    elif args.phase == "prepare":
        prepare(args.output)
    elif args.phase == "develop":
        Experiment(args.output).develop()
    else:
        Experiment(args.output).evaluate()


if __name__ == "__main__":
    main()
