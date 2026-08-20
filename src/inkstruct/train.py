from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import platform
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from .factorized import CONTEXT_FEATURES, stroke_context_tokens
from .geometry import bbox, resample
from .structures import StructureRepository


def _require_training_dependencies():
    try:
        import lmdb
        import torch
    except ImportError as error:
        raise RuntimeError(
            "run this command in an environment installed with inkstruct[train]"
        ) from error
    return lmdb, torch


def _split_casia_strokes(coordinates: np.ndarray) -> list[list[tuple[float, float]]]:
    strokes: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for row in np.asarray(coordinates):
        current.append((float(row[0]), float(row[1])))
        if float(row[3]) > 0.5 or float(row[4]) > 0.5:
            if len(current) >= 2:
                strokes.append(current)
            current = []
    if len(current) >= 2:
        strokes.append(current)
    if not strokes:
        raise ValueError("CASIA record has no complete strokes")
    all_points = [point for stroke in strokes for point in stroke]
    x0, y0, x1, y1 = bbox(all_points)
    scale = max(x1 - x0, y1 - y0, 1e-6)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [
        [(0.5 + (x - cx) * 0.85 / scale, 0.5 + (y - cy) * 0.85 / scale) for x, y in stroke]
        for stroke in strokes
    ]


def _token(points: list[tuple[float, float]], *, order: int, count: int) -> np.ndarray:
    sampled = np.asarray(resample(points, 16), dtype=np.float32).reshape(-1)
    x0, y0, x1, y1 = bbox(points)
    extras = np.asarray(
        [x0, y0, x1, y1, order / max(count, 1), len(points) / 64.0, x1 - x0, y1 - y0],
        dtype=np.float32,
    )
    return np.concatenate((sampled, extras))


class CasiaCorpus:
    def __init__(
        self,
        lmdb_path: Path,
        structures: StructureRepository,
        max_records: int,
        *,
        partition: str = "all",
        validation_fraction: float = 0.1,
        split_seed: int = 1001,
        environment=None,
    ):
        lmdb, _ = _require_training_dependencies()
        self.environment = environment or lmdb.open(
            str(lmdb_path), readonly=True, lock=False, readahead=False, max_readers=32
        )
        self.structures = structures
        supported_characters = set(structures.characters())
        self.records: list[tuple[int, str, str]] = []
        self.by_writer: dict[str, list[int]] = defaultdict(list)
        with self.environment.begin(write=False) as transaction:
            available = int(transaction.get(b"num_sample").decode())
            for index in range(min(available, max_records)):
                value = pickle.loads(transaction.get(str(index).encode()))
                character, writer = value["tag_char"], str(value["fname"]).split(".")[0]
                if character not in supported_characters:
                    continue
                corpus_index = len(self.records)
                self.records.append((index, character, writer))
                self.by_writer[writer].append(corpus_index)
        valid_writers = {writer for writer, indexes in self.by_writer.items() if len(indexes) >= 2}
        if partition not in {"all", "train", "validation"}:
            raise ValueError(f"unknown writer partition: {partition}")
        if partition != "all":
            validation_writers = {
                writer
                for writer in valid_writers
                if int.from_bytes(
                    hashlib.sha256(f"{split_seed}:{writer}".encode()).digest()[:8], "big"
                )
                / 2**64
                < validation_fraction
            }
            if not validation_writers and valid_writers:
                validation_writers = {
                    min(
                        valid_writers,
                        key=lambda writer: hashlib.sha256(
                            f"{split_seed}:{writer}".encode()
                        ).digest(),
                    )
                }
            if validation_writers == valid_writers and len(valid_writers) > 1:
                validation_writers.remove(max(validation_writers))
            valid_writers = (
                valid_writers - validation_writers
                if partition == "train"
                else validation_writers
            )
        self.records = [record for record in self.records if record[2] in valid_writers]
        rebuilt: dict[str, list[int]] = defaultdict(list)
        for index, record in enumerate(self.records):
            rebuilt[record[2]].append(index)
        self.by_writer = rebuilt
        if not self.records:
            raise ValueError("no usable CASIA episodes were found")
        self.index_sha256 = hashlib.sha256(
            "\n".join(f"{index}:{character}:{writer}" for index, character, writer in self.records).encode()
        ).hexdigest()

    def partition(
        self,
        partition: str,
        *,
        validation_fraction: float,
        split_seed: int,
    ) -> CasiaCorpus:
        if partition not in {"train", "validation"}:
            raise ValueError(f"unknown writer partition: {partition}")
        valid_writers = set(self.by_writer)
        validation_writers = {
            writer
            for writer in valid_writers
            if int.from_bytes(
                hashlib.sha256(f"{split_seed}:{writer}".encode()).digest()[:8], "big"
            )
            / 2**64
            < validation_fraction
        }
        if not validation_writers and valid_writers:
            validation_writers = {
                min(
                    valid_writers,
                    key=lambda writer: hashlib.sha256(
                        f"{split_seed}:{writer}".encode()
                    ).digest(),
                )
            }
        if validation_writers == valid_writers and len(valid_writers) > 1:
            validation_writers.remove(max(validation_writers))
        selected = (
            valid_writers - validation_writers
            if partition == "train"
            else validation_writers
        )
        view = object.__new__(CasiaCorpus)
        view.environment = self.environment
        view.structures = self.structures
        view.records = [record for record in self.records if record[2] in selected]
        view.by_writer = defaultdict(list)
        for index, record in enumerate(view.records):
            view.by_writer[record[2]].append(index)
        if not view.records:
            raise ValueError(f"no usable CASIA {partition} episodes were found")
        view.index_sha256 = hashlib.sha256(
            "\n".join(
                f"{index}:{character}:{writer}"
                for index, character, writer in view.records
            ).encode()
        ).hexdigest()
        return view

    def read(self, corpus_index: int) -> tuple[str, str, list[list[tuple[float, float]]]]:
        lmdb_index, character, writer = self.records[corpus_index]
        with self.environment.begin(write=False) as transaction:
            value = pickle.loads(transaction.get(str(lmdb_index).encode()))
        return character, writer, _split_casia_strokes(value["coordinates"])

    def episode(
        self,
        index: int,
        references: int = 8,
        *,
        rng: random.Random | None = None,
    ) -> dict[str, np.ndarray]:
        rng = rng or random
        query_index = index % len(self.records)
        character, writer, user_strokes = self.read(query_index)
        graph = self.structures.get(character)
        if len(user_strokes) != len(graph.strokes):
            return self.episode(index + 1, references, rng=rng)
        writer_pool = [value for value in self.by_writer[writer] if value != query_index]
        if not writer_pool:
            return self.episode(index + 1, references, rng=rng)
        chosen = rng.sample(writer_pool, min(references, len(writer_pool)))
        style_tokens: list[np.ndarray] = []
        for reference_index in chosen:
            try:
                _, _, strokes = self.read(reference_index)
            except ValueError:
                continue
            style_tokens.extend(
                _token(stroke, order=order, count=len(strokes))
                for order, stroke in enumerate(strokes, 1)
            )
        if not style_tokens:
            return self.episode(index + 1, references, rng=rng)
        structure_tokens = [
            _token(stroke.median, order=stroke.order, count=len(graph.strokes))
            for stroke in graph.strokes
        ]
        residuals = []
        standard_controls = []
        target_controls = []
        stroke_origins = []
        stroke_scales = []
        confidences = []
        density = []
        for standard, user in zip(graph.strokes, user_strokes):
            standard_points = np.asarray(resample(standard.median, 8), dtype=np.float32)
            user_points = np.asarray(resample(user, 8), dtype=np.float32)
            minimum = standard_points.min(axis=0)
            span = standard_points.max(axis=0) - minimum
            scale = max(float(span.max()), 1e-6)
            standard_local = (standard_points - minimum) / scale
            user_local = (user_points - minimum) / scale
            residual = user_local - standard_local
            residuals.append(residual)
            standard_controls.append(standard_local)
            target_controls.append(user_points)
            stroke_origins.append(minimum)
            stroke_scales.append(scale)
            confidences.append(math.exp(-5.0 * float(np.mean(np.linalg.norm(residual, axis=1)))))
            density.append(min(128, max(24, len(user))) / 128.0)
        return {
            "style": np.stack(style_tokens[:96]),
            "structure": np.stack(structure_tokens),
            "context": stroke_context_tokens(graph),
            "residual": np.stack(residuals),
            "standard_controls": np.stack(standard_controls),
            "target_controls": np.stack(target_controls),
            "stroke_origins": np.stack(stroke_origins),
            "stroke_scales": np.asarray(stroke_scales, dtype=np.float32),
            "density": np.asarray(density, dtype=np.float32),
            "confidence": np.asarray(confidences, dtype=np.float32),
        }


def _pad_episodes(episodes: list[dict[str, np.ndarray]], torch) -> dict:
    batch = len(episodes)
    max_style = max(len(item["style"]) for item in episodes)
    max_strokes = max(len(item["structure"]) for item in episodes)
    style = torch.zeros(batch, max_style, 40)
    structure = torch.zeros(batch, max_strokes, 40)
    context = torch.zeros(batch, max_strokes, CONTEXT_FEATURES)
    residual = torch.zeros(batch, max_strokes, 8, 2)
    standard_controls = torch.zeros(batch, max_strokes, 8, 2)
    target_controls = torch.zeros(batch, max_strokes, 8, 2)
    stroke_origins = torch.zeros(batch, max_strokes, 2)
    stroke_scales = torch.ones(batch, max_strokes)
    density = torch.zeros(batch, max_strokes)
    confidence = torch.zeros(batch, max_strokes)
    style_mask = torch.ones(batch, max_style, dtype=torch.bool)
    structure_mask = torch.ones(batch, max_strokes, dtype=torch.bool)
    for row, item in enumerate(episodes):
        style_count, stroke_count = len(item["style"]), len(item["structure"])
        style[row, :style_count] = torch.from_numpy(item["style"])
        structure[row, :stroke_count] = torch.from_numpy(item["structure"])
        context[row, :stroke_count] = torch.from_numpy(item["context"])
        residual[row, :stroke_count] = torch.from_numpy(item["residual"])
        standard_controls[row, :stroke_count] = torch.from_numpy(item["standard_controls"])
        target_controls[row, :stroke_count] = torch.from_numpy(item["target_controls"])
        stroke_origins[row, :stroke_count] = torch.from_numpy(item["stroke_origins"])
        stroke_scales[row, :stroke_count] = torch.from_numpy(item["stroke_scales"])
        density[row, :stroke_count] = torch.from_numpy(item["density"])
        confidence[row, :stroke_count] = torch.from_numpy(item["confidence"])
        style_mask[row, :style_count] = False
        structure_mask[row, :stroke_count] = False
    return {
        "style": style,
        "structure": structure,
        "context": context,
        "residual": residual,
        "standard_controls": standard_controls,
        "target_controls": target_controls,
        "stroke_origins": stroke_origins,
        "stroke_scales": stroke_scales,
        "density": density,
        "confidence": confidence,
        "style_mask": style_mask,
        "structure_mask": structure_mask,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inkstruct train")
    parser.add_argument("--casia-lmdb", type=Path, default=Path("data/CASIA_CHINESE/train"))
    parser.add_argument(
        "--database", type=Path, default=Path("artifacts/structures/characters.sqlite3")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/models/hierarchical_residual.pt")
    )
    parser.add_argument("--steps", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-records", type=int, default=50_000)
    parser.add_argument("--references", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--seed", type=int, default=1001)
    parser.add_argument("--split-seed", type=int, default=1001)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--allow-resume-config-change", action="store_true")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow a non-smoke run from a dirty worktree (never use for formal reports)",
    )
    parser.add_argument("--save-every", type=int, default=100)
    parser.add_argument("--validate-every", type=int, default=100)
    parser.add_argument("--validation-episodes", type=int, default=128)
    parser.add_argument("--early-stop-patience", type=int, default=10)
    parser.add_argument("--early-stop-min-delta", type=float, default=1e-4)
    parser.add_argument("--last-output", type=Path)
    parser.add_argument("--refiner", action="store_true")
    parser.add_argument("--factorized-style", action="store_true")
    parser.add_argument("--curve-loss-weight", type=float, default=0.0)
    parser.add_argument("--sdf-loss-weight", type=float, default=0.0)
    parser.add_argument("--render-sizes", default="32,64")
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--calibrate-episodes", type=int, default=128)
    parser.add_argument("--test-lmdb", type=Path, default=Path("data/CASIA_CHINESE/test"))
    parser.add_argument("--smoke", action="store_true", help="run one optimisation step")
    return parser


def _git_metadata(root: Path) -> dict:
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


def _save_checkpoint(
    path: Path,
    model,
    optimizer,
    steps: int,
    history: list[dict],
    torch,
    training_config: dict,
    calibrated_threshold: float | None = None,
    training_state: dict | None = None,
    training_status: str = "formal",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".building")
    payload = model.checkpoint_payload()
    payload.update(
        {
            "steps": steps,
            "history": history[-100:],
            "optimizer_state": optimizer.state_dict(),
            "model_version": "hierarchical_residual_v3",
            "training_config": training_config,
            "calibrated_confidence_threshold": calibrated_threshold,
            "training_state": training_state or {},
            "training_status": training_status,
        }
    )
    torch.save(payload, temporary)
    temporary.replace(path)


def _validation_loss(
    model,
    corpus: CasiaCorpus,
    *,
    episodes: int,
    batch_size: int,
    references: int,
    seed: int,
    curve_loss_weight: float,
    torch,
    auxiliary_curve_loss,
) -> dict[str, float]:
    rng = random.Random(seed)
    totals: dict[str, list[float]] = defaultdict(list)
    model.eval()
    with torch.inference_mode():
        for start in range(0, episodes, batch_size):
            count = min(batch_size, episodes - start)
            values = [
                corpus.episode(rng.randrange(len(corpus.records)), references, rng=rng)
                for _ in range(count)
            ]
            batch = {key: value.cuda() for key, value in _pad_episodes(values, torch).items()}
            prediction = model(
                batch["style"],
                batch["structure"],
                style_padding_mask=batch["style_mask"],
                structure_padding_mask=batch["structure_mask"],
                context_tokens=batch["context"],
            )
            valid = (~batch["structure_mask"]).float()
            residual = (
                ((prediction["residual"] - batch["residual"]) ** 2).mean((-1, -2))
                * valid
            ).sum() / valid.sum()
            density = (
                ((prediction["density"] - batch["density"]) ** 2) * valid
            ).sum() / valid.sum()
            confidence = (
                torch.nn.functional.binary_cross_entropy(
                    prediction["confidence"], batch["confidence"], reduction="none"
                )
                * valid
            ).sum() / valid.sum()
            predicted_controls = batch["stroke_origins"].unsqueeze(-2) + (
                batch["standard_controls"] + prediction["residual"]
            ) * batch["stroke_scales"].unsqueeze(-1).unsqueeze(-1)
            curve_values = auxiliary_curve_loss(
                predicted_controls, batch["target_controls"], batch["structure_mask"]
            )
            curve = (
                curve_values["curve"]
                + 0.35 * curve_values["endpoint"]
                + 0.2 * curve_values["tangent"]
                + 0.1 * curve_values["curvature"]
            )
            loss = residual + 0.2 * density + 0.1 * confidence + curve_loss_weight * curve
            totals["loss"].append(float(loss))
            totals["residual"].append(float(residual))
            totals["curve"].append(float(curve))
    model.train()
    return {key: float(np.mean(values)) for key, values in totals.items()}


def _calibrate_confidence_threshold(
    model,
    corpus: CasiaCorpus,
    *,
    episodes: int,
    batch_size: int,
    references: int,
    torch,
) -> float:
    if episodes <= 0:
        return 0.55
    generator = random.Random(1103)
    thresholds = [round(value, 2) for value in np.arange(0.30, 0.801, 0.05)]
    losses: dict[float, list[float]] = {threshold: [] for threshold in thresholds}
    model.eval()
    with torch.inference_mode():
        for start in range(0, episodes, batch_size):
            count = min(batch_size, episodes - start)
            values = [
                corpus.episode(
                    generator.randrange(len(corpus.records)), references, rng=generator
                )
                for _ in range(count)
            ]
            batch = {key: value.cuda() for key, value in _pad_episodes(values, torch).items()}
            prediction = model(
                batch["style"],
                batch["structure"],
                style_padding_mask=batch["style_mask"],
                structure_padding_mask=batch["structure_mask"],
                context_tokens=batch["context"],
            )
            valid = (~batch["structure_mask"]).float()
            predicted_error = (
                ((prediction["residual"] - batch["residual"]) ** 2).mean((-1, -2)) * valid
            ).sum(-1) / valid.sum(-1).clamp_min(1)
            fallback_error = ((batch["residual"] ** 2).mean((-1, -2)) * valid).sum(-1) / valid.sum(
                -1
            ).clamp_min(1)
            per_stroke_confidence = prediction["confidence"]
            if "residual_log_variance" in prediction:
                uncertainty = torch.exp(0.5 * prediction["residual_log_variance"])
                per_stroke_confidence = per_stroke_confidence * torch.exp(-0.5 * uncertainty)
            confidence = (per_stroke_confidence * valid).sum(-1) / valid.sum(-1).clamp_min(1)
            for threshold in thresholds:
                chosen = torch.where(
                    confidence >= threshold, predicted_error, fallback_error
                )
                losses[threshold].extend(chosen.float().cpu().tolist())
    model.train()
    return min(thresholds, key=lambda threshold: (float(np.mean(losses[threshold])), threshold))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, torch = _require_training_dependencies()
    if not torch.cuda.is_available():
        raise RuntimeError("inkstruct train requires a CUDA-capable NVIDIA GPU")
    from .model import HierarchicalResidualModel, ModelConfig
    from .torch_render import auxiliary_curve_loss, multiscale_sdf_loss

    started_clock = time.perf_counter()
    repository_root = Path(__file__).resolve().parents[2]
    git = _git_metadata(repository_root)
    if git["dirty"] and not (args.smoke or args.allow_dirty):
        raise RuntimeError(
            "formal training requires a clean Git worktree; use --allow-dirty only for diagnostics"
        )
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False)
    torch.backends.cuda.enable_math_sdp(True)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    training_rng = random.Random(args.seed)
    structures = StructureRepository(args.database)
    train_source = CasiaCorpus(
        args.casia_lmdb,
        structures,
        args.max_records,
    )
    corpus = train_source.partition(
        "train",
        validation_fraction=args.validation_fraction,
        split_seed=args.split_seed,
    )
    validation_corpus = train_source.partition(
        "validation",
        validation_fraction=args.validation_fraction,
        split_seed=args.split_seed,
    )
    test_corpus = CasiaCorpus(args.test_lmdb, structures, args.max_records)
    writer_overlap = set(corpus.by_writer) & set(test_corpus.by_writer)
    if writer_overlap:
        raise RuntimeError(
            f"CASIA train/test writer leakage detected: {sorted(writer_overlap)[:5]}"
        )
    resume_payload = (
        torch.load(args.resume, map_location="cuda", weights_only=False)
        if args.resume
        else None
    )
    model_config = (
        ModelConfig(**resume_payload["model_config"])
        if resume_payload is not None
        else ModelConfig(
            use_refiner=args.refiner,
            use_factorized_style=args.factorized_style,
        )
    )
    model = HierarchicalResidualModel(model_config).cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    target_steps = 1 if args.smoke else args.steps
    if args.validate_every < 1 or args.validation_episodes < 1:
        raise ValueError("validation cadence and episode count must be positive")
    last_output = args.last_output or args.output.with_name(
        f"{args.output.stem}.last{args.output.suffix}"
    )
    start_step = 0
    history: list[dict] = []
    best_validation = float("inf")
    best_step = 0
    validations_without_improvement = 0
    render_sizes = tuple(int(value) for value in args.render_sizes.split(",") if value)
    training_config = {
        "references": args.references,
        "batch_size": args.batch_size,
        "seed": args.seed,
        "split_seed": args.split_seed,
        "max_records": args.max_records,
        "learning_rate": args.learning_rate,
        "refiner": model_config.use_refiner,
        "factorized_style": model_config.use_factorized_style,
        "curve_loss_weight": args.curve_loss_weight,
        "sdf_loss_weight": args.sdf_loss_weight,
        "dynamic_supervision": "unavailable_in_casia_pot",
        "density_normalization_points": 128,
        "render_sizes": render_sizes,
        "validate_every": args.validate_every,
        "validation_episodes": args.validation_episodes,
        "early_stop_patience": args.early_stop_patience,
        "early_stop_min_delta": args.early_stop_min_delta,
        "train_writer_count": len(corpus.by_writer),
        "validation_writer_count": len(validation_corpus.by_writer),
        "test_writer_count": len(test_corpus.by_writer),
        "train_index_sha256": corpus.index_sha256,
        "validation_index_sha256": validation_corpus.index_sha256,
        "test_index_sha256": test_corpus.index_sha256,
        "structure_version": structures.metadata().get("source_version"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0),
        "git": git,
    }
    training_config["config_sha256"] = hashlib.sha256(
        json.dumps(training_config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if resume_payload is not None:
        previous_config = resume_payload.get("training_config", {})
        guarded_keys = (
            "seed",
            "split_seed",
            "max_records",
            "batch_size",
            "references",
            "curve_loss_weight",
            "sdf_loss_weight",
            "render_sizes",
        )
        changed = {
            key: {"previous": previous_config.get(key), "current": training_config.get(key)}
            for key in guarded_keys
            if previous_config.get(key) != training_config.get(key)
        }
        if changed and not args.allow_resume_config_change:
            raise ValueError(f"resume training configuration changed: {changed}")
        training_config["resume_checkpoint"] = str(args.resume.resolve())
        training_config["resume_config_changes"] = changed
        model.load_state_dict(resume_payload["model_state"])
        if "optimizer_state" in resume_payload:
            optimizer.load_state_dict(resume_payload["optimizer_state"])
        start_step = int(resume_payload.get("steps", 0))
        history.extend(resume_payload.get("history", []))
        state = resume_payload.get("training_state", {})
        best_validation = float(state.get("best_validation", best_validation))
        best_step = int(state.get("best_step", 0))
        validations_without_improvement = int(
            state.get("validations_without_improvement", 0)
        )
        if state.get("training_rng_state") is not None:
            training_rng.setstate(state["training_rng_state"])
        if state.get("torch_rng_state") is not None:
            torch.set_rng_state(state["torch_rng_state"].cpu())
        if state.get("cuda_rng_state_all") is not None:
            torch.cuda.set_rng_state_all(
                [value.cpu() for value in state["cuda_rng_state_all"]]
            )
    training_status = "smoke" if args.smoke else "formal"

    def checkpoint_state() -> dict:
        return {
            "best_validation": best_validation,
            "best_step": best_step,
            "validations_without_improvement": validations_without_improvement,
            "training_rng_state": training_rng.getstate(),
            "torch_rng_state": torch.get_rng_state(),
            "cuda_rng_state_all": torch.cuda.get_rng_state_all(),
        }

    stopped_early = False
    completed_step = start_step
    for step in range(start_step, target_steps):
        episodes = [
            corpus.episode(
                training_rng.randrange(len(corpus.records)),
                args.references,
                rng=training_rng,
            )
            for _ in range(args.batch_size)
        ]
        batch = {key: value.cuda() for key, value in _pad_episodes(episodes, torch).items()}
        prediction = model(
            batch["style"],
            batch["structure"],
            style_padding_mask=batch["style_mask"],
            structure_padding_mask=batch["structure_mask"],
            context_tokens=batch["context"],
        )
        valid = (~batch["structure_mask"]).float()
        residual_loss = (
            ((prediction["residual"] - batch["residual"]) ** 2).mean((-1, -2)) * valid
        ).sum() / valid.sum()
        density_loss = (
            ((prediction["density"] - batch["density"]) ** 2) * valid
        ).sum() / valid.sum()
        confidence_loss = (
            torch.nn.functional.binary_cross_entropy(
                prediction["confidence"], batch["confidence"], reduction="none"
            )
            * valid
        ).sum() / valid.sum()
        loss = (
            residual_loss
            + 0.2 * density_loss
            + 0.1 * confidence_loss
        )
        if model_config.use_factorized_style:
            writer_mean = prediction["writer_mean"]
            writer_log_variance = prediction["writer_log_variance"]
            writer_kl = -0.5 * (
                1 + writer_log_variance - writer_mean.square() - writer_log_variance.exp()
            ).mean()
            per_stroke_error = ((prediction["residual"] - batch["residual"]) ** 2).mean(
                (-1, -2)
            )
            uncertainty_loss = (
                (
                    per_stroke_error * (-prediction["residual_log_variance"]).exp()
                    + prediction["residual_log_variance"]
                )
                * valid
            ).sum() / valid.sum()
            loss = loss + 1e-4 * writer_kl + 1e-4 * uncertainty_loss
        predicted_controls = batch["stroke_origins"].unsqueeze(-2) + (
            batch["standard_controls"] + prediction["residual"]
        ) * batch["stroke_scales"].unsqueeze(-1).unsqueeze(-1)
        curve_losses = auxiliary_curve_loss(
            predicted_controls, batch["target_controls"], batch["structure_mask"]
        )
        curve_loss = (
            curve_losses["curve"]
            + 0.35 * curve_losses["endpoint"]
            + 0.2 * curve_losses["tangent"]
            + 0.1 * curve_losses["curvature"]
        )
        sdf_loss = (
            multiscale_sdf_loss(
                predicted_controls,
                batch["target_controls"],
                batch["structure_mask"],
                sizes=render_sizes,
            )
            if args.sdf_loss_weight > 0
            else torch.zeros((), device="cuda")
        )
        loss = loss + args.curve_loss_weight * curve_loss + args.sdf_loss_weight * sdf_loss
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        record = {
            "step": step + 1,
            "loss": float(loss.detach()),
            "residual": float(residual_loss.detach()),
            "curve": float(curve_loss.detach()),
            "sdf": float(sdf_loss.detach()),
        }
        history.append(record)
        completed_step = step + 1
        if step == start_step or (step + 1) % 10 == 0:
            print(json.dumps(record))
        if args.save_every > 0 and (step + 1) % args.save_every == 0:
            _save_checkpoint(
                last_output,
                model,
                optimizer,
                step + 1,
                history,
                torch,
                training_config,
                training_state=checkpoint_state(),
                training_status=training_status,
            )
        should_validate = (step + 1) % args.validate_every == 0 or step + 1 == target_steps
        if should_validate:
            validation = _validation_loss(
                model,
                validation_corpus,
                episodes=args.validation_episodes,
                batch_size=args.batch_size,
                references=args.references,
                seed=args.split_seed + 10_000,
                curve_loss_weight=args.curve_loss_weight,
                torch=torch,
                auxiliary_curve_loss=auxiliary_curve_loss,
            )
            validation_record = {"step": step + 1, "validation": validation}
            history.append(validation_record)
            print(json.dumps(validation_record))
            if validation["loss"] < best_validation - args.early_stop_min_delta:
                best_validation = validation["loss"]
                best_step = step + 1
                validations_without_improvement = 0
                _save_checkpoint(
                    args.output,
                    model,
                    optimizer,
                    step + 1,
                    history,
                    torch,
                    training_config,
                    training_state=checkpoint_state(),
                    training_status=training_status,
                )
            else:
                validations_without_improvement += 1
            if validations_without_improvement >= args.early_stop_patience:
                stopped_early = True
                break
    _save_checkpoint(
        last_output,
        model,
        optimizer,
        completed_step,
        history,
        torch,
        training_config,
        training_state=checkpoint_state(),
        training_status=training_status,
    )
    if best_step == 0 or not args.output.is_file():
        validation = _validation_loss(
            model,
            validation_corpus,
            episodes=args.validation_episodes,
            batch_size=args.batch_size,
            references=args.references,
            seed=args.split_seed + 10_000,
            curve_loss_weight=args.curve_loss_weight,
            torch=torch,
            auxiliary_curve_loss=auxiliary_curve_loss,
        )
        best_validation = validation["loss"]
        best_step = completed_step
        _save_checkpoint(
            args.output,
            model,
            optimizer,
            completed_step,
            history,
            torch,
            training_config,
            training_state=checkpoint_state(),
            training_status=training_status,
        )
    best_payload = torch.load(args.output, map_location="cuda", weights_only=False)
    model.load_state_dict(best_payload["model_state"])
    if "optimizer_state" in best_payload:
        optimizer.load_state_dict(best_payload["optimizer_state"])
    calibrated_threshold = _calibrate_confidence_threshold(
        model,
        validation_corpus,
        episodes=args.calibrate_episodes,
        batch_size=args.batch_size,
        references=args.references,
        torch=torch,
    )
    elapsed_seconds = time.perf_counter() - started_clock
    training_config.update(
        {
            "calibrated_confidence_threshold": calibrated_threshold,
            "completed_step": completed_step,
            "best_step": best_step,
            "best_validation": best_validation,
            "stopped_early": stopped_early,
            "elapsed_seconds": elapsed_seconds,
        }
    )
    _save_checkpoint(
        args.output,
        model,
        optimizer,
        best_step,
        history,
        torch,
        training_config,
        calibrated_threshold,
        checkpoint_state(),
        training_status,
    )
    report = {
        "schema_version": "training_report_v1",
        "best_checkpoint": str(args.output.resolve()),
        "last_checkpoint": str(last_output.resolve()),
        "training_status": training_status,
        "completed_step": completed_step,
        "best_step": best_step,
        "best_validation": best_validation,
        "stopped_early": stopped_early,
        "calibrated_confidence_threshold": calibrated_threshold,
        "elapsed_seconds": elapsed_seconds,
        "reproducibility": {
            "git": git,
            "config_sha256": training_config["config_sha256"],
            "train_index_sha256": training_config["train_index_sha256"],
            "validation_index_sha256": training_config["validation_index_sha256"],
            "test_index_sha256": training_config["test_index_sha256"],
            "structure_version": training_config["structure_version"],
        },
        "training_config": training_config,
        "history": history,
    }
    report_path = args.output.with_suffix(".training.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "history"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
