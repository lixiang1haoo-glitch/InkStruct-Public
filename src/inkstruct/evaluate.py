from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .alignment import align_sample, standard_order_indices
from .generate import generate_run
from .geometry import bbox, polyline_distance, resample
from .geometry_audit import audit_glyph
from .metrics import aggregate_stroke_metrics
from .profile import build_profile
from .samples import iter_index
from .structures import StructureRepository


class _WriterStyleEmbedder:
    def __init__(self, checkpoint: Path):
        import torch

        from .model import HierarchicalResidualModel, ModelConfig

        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        config = ModelConfig(**payload["model_config"])
        if not config.use_factorized_style:
            raise ValueError("style checkpoint has no writer-disjoint factorized encoder")
        self.model = HierarchicalResidualModel(config)
        self.model.load_state_dict(payload["model_state"])
        self.model.eval()
        self.torch = torch

    @staticmethod
    def _token(stroke: list[tuple[float, float]], order: int, count: int) -> list[float]:
        sampled = np.asarray(resample(stroke, 16), dtype=np.float32).reshape(-1)
        x0, y0, x1, y1 = bbox(stroke)
        return [
            *sampled.tolist(),
            x0,
            y0,
            x1,
            y1,
            order / max(count, 1),
            len(stroke) / 64.0,
            x1 - x0,
            y1 - y0,
        ]

    def embedding(self, strokes: list[list[tuple[float, float]]]) -> np.ndarray:
        values = [self._token(stroke, index + 1, len(strokes)) for index, stroke in enumerate(strokes)]
        with self.torch.inference_mode():
            _, mean, _ = self.model.encode_writer(
                self.torch.tensor([values], dtype=self.torch.float32)
            )
        return mean[0].float().numpy()

    def similarity(
        self,
        generated: list[list[tuple[float, float]]],
        target: list[list[tuple[float, float]]],
    ) -> float:
        left, right = self.embedding(generated), self.embedding(target)
        denominator = max(float(np.linalg.norm(left) * np.linalg.norm(right)), 1e-9)
        return float(np.dot(left, right) / denominator)


def evaluate_run(run_dir: Path, structures: StructureRepository) -> dict:
    run_dir = Path(run_dir).resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []
    confidence_values: list[float] = []
    checked = 0
    canvas_fitted = 0
    canvas_review = []
    geometry_audits = {}
    for path in sorted((run_dir / "trajectories").glob("U+*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            character = value["character"]
            graph = structures.get(character)
            strokes = value["strokes"]
            if len(strokes) != len(graph.strokes):
                raise ValueError(f"stroke count {len(strokes)} != {len(graph.strokes)}")
            expected_orders = list(range(1, len(graph.strokes) + 1))
            actual_orders = [int(stroke["order"]) for stroke in strokes]
            if actual_orders != expected_orders:
                raise ValueError("stroke order is not sequential")
            expected_ids = [stroke.stroke_id for stroke in graph.strokes]
            actual_ids = [str(stroke["standard_stroke_id"]) for stroke in strokes]
            if actual_ids != expected_ids:
                raise ValueError("standard stroke IDs do not match the character graph")
            previous_time = -1
            for stroke in strokes:
                if len(stroke["points"]) < 2:
                    raise ValueError(f"stroke {stroke['order']} has fewer than two points")
                for point in stroke["points"]:
                    if not 0 <= float(point["x"]) <= 1 or not 0 <= float(point["y"]) <= 1:
                        raise ValueError("coordinate outside [0, 1]")
                    if not 0 <= float(point["pressure"]) <= 1:
                        raise ValueError("pressure outside [0, 1]")
                    if int(point["t_ms"]) < previous_time:
                        raise ValueError("time is not monotonic")
                    previous_time = int(point["t_ms"])
            fit = value.get("canvas_fit", {})
            if not isinstance(fit, dict):
                raise TypeError("canvas fit metadata must be an object")
            geometry_audit = audit_glyph(value, graph)
            if fit.get("applied"):
                canvas_fitted += 1
            if fit.get("review_required"):
                canvas_review.append(character)
            confidence_values.append(float(value["confidence"]))
            geometry_audits[character] = geometry_audit
            checked += 1
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            failures.append({"path": str(path), "reason": str(error)})
    result = {
        "schema_version": "generation_evaluation_v1",
        "run_id": manifest.get("run_id"),
        "checked_count": checked,
        "structural_failure_count": len(failures),
        "canvas_fitted_count": canvas_fitted,
        "canvas_review_characters": canvas_review,
        "structural_pass_rate": checked / max(1, checked + len(failures)),
        "mean_confidence": sum(confidence_values) / max(1, len(confidence_values)),
        "geometry_warning_character_count": sum(
            bool(audit["geometry_warnings"]) for audit in geometry_audits.values()
        ),
        "geometry_audits": geometry_audits,
        "requested_count": manifest.get("requested_count"),
        "generation_failed_count": manifest.get("failed_count"),
        "structure_coverage_rate": checked / max(1, int(manifest.get("requested_count", 0))),
        "content_safety_passed": (
            not failures
            and not manifest.get("failed_count")
            and checked == int(manifest.get("requested_count", 0))
        ),
        "failures": failures,
        "style_metrics": {
            "status": "requires held-out samples not used by the profile",
            "dtw_improvement_target": 0.15,
            "blind_preference_target": 0.70,
        },
    }
    (run_dir / "evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def evaluate_writer(
    writer_id: str,
    index_path: Path,
    structures: StructureRepository,
    *,
    output_root: Path,
    heldout_ratio: float = 0.2,
    checkpoint: Path | None = None,
    component_conditioning: bool | str = True,
    component_strength: float = 1.0,
    heldout_characters: set[str] | None = None,
    style_checkpoint: Path | None = None,
    confidence_threshold: float | None = None,
) -> dict:
    if not 0.1 <= heldout_ratio <= 0.4:
        raise ValueError("heldout ratio must be between 0.1 and 0.4")
    samples = list(iter_index(index_path))
    characters = sorted({sample.character for sample in samples}, key=ord)
    if heldout_characters is None:
        heldout_count = max(1, round(len(characters) * heldout_ratio))
        stride = max(1, len(characters) // heldout_count)
        heldout = set(characters[::stride][:heldout_count])
    else:
        heldout = set(heldout_characters)
        missing = heldout - set(characters)
        if missing:
            raise ValueError(f"held-out characters are absent from the index: {''.join(sorted(missing))}")
    train_samples = [sample for sample in samples if sample.character not in heldout]
    evaluation_root = Path(output_root).resolve() / writer_id
    evaluation_root.mkdir(parents=True, exist_ok=True)
    train_index = evaluation_root / "train_index.jsonl"
    with train_index.open("w", encoding="utf-8") as stream:
        for sample in train_samples:
            stream.write(
                json.dumps(asdict(sample), ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    profile, profile_path = build_profile(
        writer_id,
        train_index,
        structures,
        evaluation_root / "profiles",
        checkpoint,
    )
    _, run_dir = generate_run(
        writer_id,
        sorted(heldout, key=ord),
        structures,
        profile_path,
        output_root=evaluation_root / "outputs",
        run_id="heldout",
        png=False,
        checkpoint=checkpoint,
        confidence_threshold=confidence_threshold,
        component_conditioning=component_conditioning,
        component_strength=component_strength,
    )
    baseline_distances: list[float] = []
    generated_distances: list[float] = []
    extended_values: dict[str, list[float]] = {}
    baseline_extended_values: dict[str, list[float]] = {}
    pressure_errors: list[float] = []
    duration_errors: list[float] = []
    density_errors: list[float] = []
    style_embedder = _WriterStyleEmbedder(style_checkpoint) if style_checkpoint else None
    character_metrics: list[dict] = []
    skipped: list[dict[str, str]] = []
    first_by_character = {}
    for sample in samples:
        first_by_character.setdefault(sample.character, sample)
    for character in sorted(heldout, key=ord):
        sample = first_by_character[character]
        graph = structures.get(character)
        aligned = align_sample(sample, graph)
        user_indices = standard_order_indices(aligned, len(graph.strokes))
        if user_indices is None:
            skipped.append(
                {
                    "character": character,
                    "reason": (
                        "stroke topology is not a complete one-to-one mapping: "
                        f"user={len(aligned.normalized_strokes)}, standard={len(graph.strokes)}"
                    ),
                }
            )
            continue
        target_strokes = [aligned.normalized_strokes[index] for index in user_indices]
        target_pressures = [aligned.pressure_strokes[index] for index in user_indices]
        target_times_by_stroke = [aligned.time_strokes[index] for index in user_indices]
        generated_path = run_dir / "trajectories" / f"U+{ord(character):04X}.json"
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
        baseline = []
        styled = []
        generated_strokes = []
        for standard, user, output_stroke in zip(
            graph.strokes, target_strokes, generated["strokes"]
        ):
            baseline.append(polyline_distance(standard.median, user))
            output = [(point["x"], point["y"]) for point in output_stroke["points"]]
            generated_strokes.append(output)
            styled.append(polyline_distance(output, user))
        extended = aggregate_stroke_metrics(generated_strokes, target_strokes)
        baseline_extended = aggregate_stroke_metrics(
            [standard.median for standard in graph.strokes], target_strokes
        )
        if style_embedder is not None:
            extended["casia_writer_style_similarity"] = style_embedder.similarity(
                generated_strokes, target_strokes
            )
        for key, value in extended.items():
            extended_values.setdefault(key, []).append(value)
        for key, value in baseline_extended.items():
            baseline_extended_values.setdefault(key, []).append(value)
        for stroke_index, output_stroke in enumerate(generated["strokes"]):
            output_points = output_stroke["points"]
            output_pressure = np.asarray(
                [float(point["pressure"]) for point in output_points], dtype=np.float64
            )
            target_pressure = np.asarray(target_pressures[stroke_index], dtype=np.float64)
            axis = np.linspace(0.0, 1.0, 16)
            output_pressure = np.interp(
                axis, np.linspace(0.0, 1.0, len(output_pressure)), output_pressure
            )
            target_pressure = np.interp(
                axis, np.linspace(0.0, 1.0, len(target_pressure)), target_pressure
            )
            pressure_errors.append(float(np.mean(np.abs(output_pressure - target_pressure))))
            output_duration = max(1, int(output_points[-1]["t_ms"]) - int(output_points[0]["t_ms"]))
            target_times = target_times_by_stroke[stroke_index]
            target_duration = max(1, int(target_times[-1]) - int(target_times[0]))
            duration_errors.append(abs(output_duration - target_duration) / target_duration)
            density_errors.append(abs(len(output_points) - len(target_times)) / max(1, len(target_times)))
        baseline_mean = float(np.mean(baseline))
        styled_mean = float(np.mean(styled))
        baseline_distances.extend(baseline)
        generated_distances.extend(styled)
        character_metrics.append(
            {
                "character": character,
                "baseline_distance": baseline_mean,
                "generated_distance": styled_mean,
                "improvement": 1.0 - styled_mean / max(baseline_mean, 1e-9),
                **extended,
                **{f"baseline_{key}": value for key, value in baseline_extended.items()},
            }
        )
    baseline_mean = float(np.mean(baseline_distances)) if baseline_distances else 0.0
    generated_mean = float(np.mean(generated_distances)) if generated_distances else 0.0
    improvement = 1.0 - generated_mean / max(baseline_mean, 1e-9)
    result = {
        "schema_version": "writer_heldout_evaluation_v1",
        "writer_id": writer_id,
        "source_character_count": len(characters),
        "training_character_count": len(set(characters) - heldout),
        "heldout_character_count": len(heldout),
        "evaluated_character_count": len(character_metrics),
        "skipped_character_count": len(skipped),
        "baseline_distance": baseline_mean,
        "generated_distance": generated_mean,
        "relative_improvement": improvement,
        "extended_metrics": {
            **{
                key: float(np.mean(values)) if values else 0.0
                for key, values in sorted(extended_values.items())
            },
            "pressure_mae": float(np.mean(pressure_errors)) if pressure_errors else 0.0,
            "duration_relative_error": (
                float(np.mean(duration_errors)) if duration_errors else 0.0
            ),
            "density_relative_error": float(np.mean(density_errors)) if density_errors else 0.0,
            "style_embedding_source": (
                "casia_writer_disjoint_factorized_v1"
                if style_embedder is not None
                else "deterministic_descriptor_v1"
            ),
        },
        "baseline_extended_metrics": {
            key: float(np.mean(values)) if values else 0.0
            for key, values in sorted(baseline_extended_values.items())
        },
        "style_target": 0.15,
        "style_target_passed": improvement >= 0.15,
        "profile_sample_count": profile.sample_count,
        "component_mode": (
            component_conditioning
            if isinstance(component_conditioning, str)
            else ("adaptive" if component_conditioning else "off")
        ),
        "component_strength": component_strength,
        "component_layout_prototype_count": len(profile.component_layouts),
        "character_layout_prototype_count": len(profile.character_layouts),
        "component_stroke_prototype_count": len(profile.component_strokes),
        "component_relation_prototype_count": len(profile.component_relations),
        "component_trajectory_prototype_count": len(profile.component_trajectories),
        "character_component_trajectory_prototype_count": len(
            profile.character_component_trajectories
        ),
        "checkpoint": str(checkpoint.resolve()) if checkpoint else None,
        "character_metrics": character_metrics,
        "skipped": skipped,
        "blind_preference": {"status": "not_run", "target": 0.70},
    }
    (evaluation_root / "evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _write_index(path: Path, samples: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".jsonl.building")
    with temporary.open("w", encoding="utf-8") as stream:
        for sample in samples:
            stream.write(json.dumps(asdict(sample), ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
    temporary.replace(path)


def _comparison_sheet(
    path: Path,
    characters: list[str],
    user_strokes: dict[str, list[list[tuple[float, float]]]],
    old_run: Path,
    updated_run: Path,
    *,
    sample_label: str = "HELD-OUT SAMPLE",
    old_label: str = "OLD PROFILE",
    updated_label: str = "UPDATED PROFILE",
) -> None:
    from PIL import Image, ImageDraw

    cell = 256
    header = 36
    canvas = Image.new("RGB", (cell * 3, header + cell * len(characters)), "white")
    draw = ImageDraw.Draw(canvas)
    for column, label in enumerate((sample_label, old_label, updated_label)):
        draw.text((column * cell + 8, 10), label, fill="#111827")
    for row, character in enumerate(characters):
        top = header + row * cell
        strokes = user_strokes.get(character, [])
        for stroke in strokes:
            points = [(12 + x * (cell - 24), top + 12 + y * (cell - 24)) for x, y in stroke]
            if len(points) >= 2:
                draw.line(points, fill="#111827", width=3, joint="curve")
        draw.text((8, top + 8), f"U+{ord(character):04X}", fill="#2563eb")
        for column, run in ((1, old_run), (2, updated_run)):
            preview = run / "previews" / f"U+{ord(character):04X}.png"
            image = Image.open(preview).convert("RGB").resize((cell, cell))
            canvas.paste(image, (column * cell, top))
        draw.line((0, top, cell * 3, top), fill="#d1d5db", width=1)
        draw.line((cell, top, cell, top + cell), fill="#d1d5db", width=1)
        draw.line((cell * 2, top, cell * 2, top + cell), fill="#d1d5db", width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def compare_profile_update(
    writer_id: str,
    base_index_path: Path,
    update_index_path: Path,
    reference_profile_path: Path,
    structures: StructureRepository,
    *,
    output_root: Path,
    heldout_count: int = 12,
) -> dict:
    """Measure geometric transfer from new characters with a fixed held-out set."""
    base_samples = list(iter_index(base_index_path))
    update_samples = list(iter_index(update_index_path))
    if any(sample.writer_id != writer_id for sample in [*base_samples, *update_samples]):
        raise ValueError("writer mismatch in comparison indexes")
    base_characters = {sample.character for sample in base_samples}
    candidate_characters = sorted(
        {sample.character for sample in update_samples} - base_characters, key=ord
    )
    if not candidate_characters:
        raise ValueError("update index contains no characters absent from the base index")
    heldout_count = min(max(1, heldout_count), len(candidate_characters))
    positions = np.linspace(0, len(candidate_characters) - 1, heldout_count, dtype=int)
    heldout = {candidate_characters[int(position)] for position in positions}
    heldout_characters = sorted(heldout, key=ord)
    training_samples = [
        *base_samples,
        *(sample for sample in update_samples if sample.character not in heldout),
    ]
    evaluation_samples = [sample for sample in update_samples if sample.character in heldout]
    root = Path(output_root).resolve() / writer_id / "component_sample_update"
    root.mkdir(parents=True, exist_ok=True)
    train_index = root / "train_index.jsonl"
    heldout_index = root / "heldout_index.jsonl"
    _write_index(train_index, training_samples)
    _write_index(heldout_index, evaluation_samples)
    _, updated_profile_path = build_profile(writer_id, train_index, structures, root / "profiles")
    _, old_run = generate_run(
        writer_id,
        heldout_characters,
        structures,
        reference_profile_path,
        output_root=root / "outputs_old",
        run_id="heldout",
        png=True,
    )
    _, updated_run = generate_run(
        writer_id,
        heldout_characters,
        structures,
        updated_profile_path,
        output_root=root / "outputs_updated",
        run_id="heldout",
        png=True,
    )
    sample_by_character = {}
    for sample in evaluation_samples:
        sample_by_character.setdefault(sample.character, sample)
    baseline_distances: list[float] = []
    old_distances: list[float] = []
    updated_distances: list[float] = []
    user_strokes: dict[str, list[list[tuple[float, float]]]] = {}
    character_metrics: list[dict] = []
    skipped: list[dict[str, str]] = []
    for character in heldout_characters:
        sample = sample_by_character[character]
        graph = structures.get(character)
        aligned = align_sample(sample, graph)
        user_indices = standard_order_indices(aligned, len(graph.strokes))
        if user_indices is None:
            skipped.append(
                {
                    "character": character,
                    "reason": (
                        f"stroke count mismatch: user={len(aligned.normalized_strokes)}, "
                        f"standard={len(graph.strokes)}"
                    ),
                }
            )
            continue
        target_strokes = [aligned.normalized_strokes[index] for index in user_indices]
        user_strokes[character] = target_strokes
        old_value = json.loads(
            (old_run / "trajectories" / f"U+{ord(character):04X}.json").read_text(encoding="utf-8")
        )
        updated_value = json.loads(
            (updated_run / "trajectories" / f"U+{ord(character):04X}.json").read_text(
                encoding="utf-8"
            )
        )
        baseline_values: list[float] = []
        old_values: list[float] = []
        updated_values: list[float] = []
        for standard, user, old_stroke, updated_stroke in zip(
            graph.strokes,
            target_strokes,
            old_value["strokes"],
            updated_value["strokes"],
        ):
            baseline_values.append(polyline_distance(standard.median, user))
            old_values.append(
                polyline_distance(
                    [(point["x"], point["y"]) for point in old_stroke["points"]], user
                )
            )
            updated_values.append(
                polyline_distance(
                    [(point["x"], point["y"]) for point in updated_stroke["points"]], user
                )
            )
        baseline_mean = float(np.mean(baseline_values))
        old_mean = float(np.mean(old_values))
        updated_mean = float(np.mean(updated_values))
        baseline_distances.extend(baseline_values)
        old_distances.extend(old_values)
        updated_distances.extend(updated_values)
        character_metrics.append(
            {
                "character": character,
                "baseline_distance": baseline_mean,
                "old_profile_distance": old_mean,
                "updated_profile_distance": updated_mean,
                "updated_vs_old_improvement": 1.0 - updated_mean / max(old_mean, 1e-9),
            }
        )
    baseline_mean = float(np.mean(baseline_distances)) if baseline_distances else 0.0
    old_mean = float(np.mean(old_distances)) if old_distances else 0.0
    updated_mean = float(np.mean(updated_distances)) if updated_distances else 0.0
    preview_path = root / "comparison.png"
    _comparison_sheet(
        preview_path,
        [item["character"] for item in character_metrics],
        user_strokes,
        old_run,
        updated_run,
    )
    result = {
        "schema_version": "profile_update_comparison_v1",
        "writer_id": writer_id,
        "base_sample_count": len(base_samples),
        "update_sample_count": len(update_samples),
        "training_sample_count": len(training_samples),
        "new_character_count": len(candidate_characters),
        "heldout_characters": "".join(heldout_characters),
        "heldout_character_count": len(heldout_characters),
        "evaluated_character_count": len(character_metrics),
        "skipped_character_count": len(skipped),
        "baseline_distance": baseline_mean,
        "old_profile_distance": old_mean,
        "updated_profile_distance": updated_mean,
        "updated_vs_old_improvement": 1.0 - updated_mean / max(old_mean, 1e-9),
        "updated_vs_baseline_improvement": 1.0 - updated_mean / max(baseline_mean, 1e-9),
        "reference_profile": str(Path(reference_profile_path).resolve()),
        "updated_profile": str(updated_profile_path),
        "preview": str(preview_path),
        "old_run": str(old_run),
        "updated_run": str(updated_run),
        "character_metrics": character_metrics,
        "skipped": skipped,
    }
    (root / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def compare_profiles_on_samples(
    writer_id: str,
    sample_index_path: Path,
    old_profile_path: Path,
    updated_profile_path: Path,
    structures: StructureRepository,
    *,
    output_root: Path,
) -> dict:
    """Compare two fixed profiles against the same online sample trajectories."""
    samples = list(iter_index(sample_index_path))
    if any(sample.writer_id != writer_id for sample in samples):
        raise ValueError("writer mismatch in comparison sample index")
    sample_by_character = {}
    for sample in samples:
        sample_by_character.setdefault(sample.character, sample)
    characters = sorted(sample_by_character, key=ord)
    root = Path(output_root).resolve()
    _, old_run = generate_run(
        writer_id,
        characters,
        structures,
        old_profile_path,
        output_root=root / "outputs_old",
        run_id="rerecord_fit",
        png=True,
    )
    _, updated_run = generate_run(
        writer_id,
        characters,
        structures,
        updated_profile_path,
        output_root=root / "outputs_updated",
        run_id="rerecord_fit",
        png=True,
    )
    baseline_distances: list[float] = []
    old_distances: list[float] = []
    updated_distances: list[float] = []
    user_strokes: dict[str, list[list[tuple[float, float]]]] = {}
    metrics: list[dict] = []
    skipped: list[dict[str, str]] = []
    for character in characters:
        sample = sample_by_character[character]
        graph = structures.get(character)
        aligned = align_sample(sample, graph)
        user_indices = standard_order_indices(aligned, len(graph.strokes))
        if user_indices is None:
            skipped.append({"character": character, "reason": "stroke count mismatch"})
            continue
        target_strokes = [aligned.normalized_strokes[index] for index in user_indices]
        user_strokes[character] = target_strokes
        old_value = json.loads(
            (old_run / "trajectories" / f"U+{ord(character):04X}.json").read_text(encoding="utf-8")
        )
        updated_value = json.loads(
            (updated_run / "trajectories" / f"U+{ord(character):04X}.json").read_text(
                encoding="utf-8"
            )
        )
        baseline_values: list[float] = []
        old_values: list[float] = []
        updated_values: list[float] = []
        for standard, user, old_stroke, updated_stroke in zip(
            graph.strokes,
            target_strokes,
            old_value["strokes"],
            updated_value["strokes"],
        ):
            baseline_values.append(polyline_distance(standard.median, user))
            old_values.append(
                polyline_distance(
                    [(point["x"], point["y"]) for point in old_stroke["points"]], user
                )
            )
            updated_values.append(
                polyline_distance(
                    [(point["x"], point["y"]) for point in updated_stroke["points"]], user
                )
            )
        baseline_mean = float(np.mean(baseline_values))
        old_mean = float(np.mean(old_values))
        updated_mean = float(np.mean(updated_values))
        baseline_distances.extend(baseline_values)
        old_distances.extend(old_values)
        updated_distances.extend(updated_values)
        metrics.append(
            {
                "character": character,
                "baseline_distance": baseline_mean,
                "old_profile_distance": old_mean,
                "updated_profile_distance": updated_mean,
                "updated_vs_old_improvement": 1.0 - updated_mean / max(old_mean, 1e-9),
            }
        )
    baseline_mean = float(np.mean(baseline_distances)) if baseline_distances else 0.0
    old_mean = float(np.mean(old_distances)) if old_distances else 0.0
    updated_mean = float(np.mean(updated_distances)) if updated_distances else 0.0
    preview = root / "rerecord_comparison.png"
    _comparison_sheet(
        preview,
        [item["character"] for item in metrics],
        user_strokes,
        old_run,
        updated_run,
        sample_label="RERECORDED SAMPLE",
    )
    result = {
        "schema_version": "profile_sample_fit_comparison_v1",
        "evaluation_mode": "profile_fit_not_generalization",
        "writer_id": writer_id,
        "characters": "".join(item["character"] for item in metrics),
        "evaluated_character_count": len(metrics),
        "skipped_character_count": len(skipped),
        "baseline_distance": baseline_mean,
        "old_profile_distance": old_mean,
        "updated_profile_distance": updated_mean,
        "updated_vs_old_improvement": 1.0 - updated_mean / max(old_mean, 1e-9),
        "preview": str(preview),
        "old_run": str(old_run),
        "updated_run": str(updated_run),
        "character_metrics": metrics,
        "skipped": skipped,
    }
    (root / "rerecord_comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
