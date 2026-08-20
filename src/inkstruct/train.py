from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import random
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
        self.records: list[tuple[int, str, str]] = []
        self.by_writer: dict[str, list[int]] = defaultdict(list)
        with self.environment.begin(write=False) as transaction:
            available = int(transaction.get(b"num_sample").decode())
            for index in range(min(available, max_records)):
                value = pickle.loads(transaction.get(str(index).encode()))
                character, writer = value["tag_char"], str(value["fname"]).split(".")[0]
                try:
                    self.structures.get(character)
                except KeyError:
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

    def read(self, corpus_index: int) -> tuple[str, str, list[list[tuple[float, float]]]]:
        lmdb_index, character, writer = self.records[corpus_index]
        with self.environment.begin(write=False) as transaction:
            value = pickle.loads(transaction.get(str(lmdb_index).encode()))
        return character, writer, _split_casia_strokes(value["coordinates"])

    def episode(self, index: int, references: int = 8) -> dict[str, np.ndarray]:
        query_index = index % len(self.records)
        character, writer, user_strokes = self.read(query_index)
        graph = self.structures.get(character)
        if len(user_strokes) != len(graph.strokes):
            return self.episode(index + 1, references)
        writer_pool = [value for value in self.by_writer[writer] if value != query_index]
        if not writer_pool:
            return self.episode(index + 1, references)
        chosen = random.sample(writer_pool, min(references, len(writer_pool)))
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
            return self.episode(index + 1, references)
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
            density.append(min(64, max(8, len(user))) / 64.0)
        stroke_count = len(graph.strokes)
        return {
            "style": np.stack(style_tokens[:96]),
            "structure": np.stack(structure_tokens),
            "context": stroke_context_tokens(graph),
            "residual": np.stack(residuals),
            "standard_controls": np.stack(standard_controls),
            "target_controls": np.stack(target_controls),
            "stroke_origins": np.stack(stroke_origins),
            "stroke_scales": np.asarray(stroke_scales, dtype=np.float32),
            "pressure": np.full((stroke_count, 8), 0.5, dtype=np.float32),
            "duration": np.full(stroke_count, 0.5, dtype=np.float32),
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
    pressure = torch.zeros(batch, max_strokes, 8)
    duration = torch.zeros(batch, max_strokes)
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
        pressure[row, :stroke_count] = torch.from_numpy(item["pressure"])
        duration[row, :stroke_count] = torch.from_numpy(item["duration"])
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
        "pressure": pressure,
        "duration": duration,
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
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--save-every", type=int, default=100)
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


def _save_checkpoint(
    path: Path,
    model,
    optimizer,
    steps: int,
    history: list[dict],
    torch,
    training_config: dict,
    calibrated_threshold: float | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".building")
    payload = model.checkpoint_payload()
    payload.update(
        {
            "steps": steps,
            "history": history[-100:],
            "optimizer_state": optimizer.state_dict(),
            "model_version": "hierarchical_residual_v2",
            "training_config": training_config,
            "calibrated_confidence_threshold": calibrated_threshold,
        }
    )
    torch.save(payload, temporary)
    temporary.replace(path)


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
                corpus.episode(generator.randrange(len(corpus.records)), references)
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
            confidence = (prediction["confidence"] * valid).sum(-1) / valid.sum(-1).clamp_min(1)
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

    random.seed(1001)
    np.random.seed(1001)
    torch.manual_seed(1001)
    structures = StructureRepository(args.database)
    corpus = CasiaCorpus(
        args.casia_lmdb,
        structures,
        args.max_records,
        partition="train",
        validation_fraction=args.validation_fraction,
    )
    validation_corpus = CasiaCorpus(
        args.casia_lmdb,
        structures,
        args.max_records,
        partition="validation",
        validation_fraction=args.validation_fraction,
        environment=corpus.environment,
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
    start_step = 0
    history: list[dict] = []
    render_sizes = tuple(int(value) for value in args.render_sizes.split(",") if value)
    training_config = {
        "references": args.references,
        "learning_rate": args.learning_rate,
        "refiner": model_config.use_refiner,
        "factorized_style": model_config.use_factorized_style,
        "curve_loss_weight": args.curve_loss_weight,
        "sdf_loss_weight": args.sdf_loss_weight,
        "render_sizes": render_sizes,
        "train_writer_count": len(corpus.by_writer),
        "validation_writer_count": len(validation_corpus.by_writer),
        "test_writer_count": len(test_corpus.by_writer),
    }
    if resume_payload is not None:
        model.load_state_dict(resume_payload["model_state"])
        if "optimizer_state" in resume_payload:
            optimizer.load_state_dict(resume_payload["optimizer_state"])
        start_step = int(resume_payload.get("steps", 0))
        history.extend(resume_payload.get("history", []))
    for step in range(start_step, target_steps):
        episodes = [
            corpus.episode(random.randrange(len(corpus.records)), args.references)
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
        pressure_loss = (
            ((prediction["pressure"] - batch["pressure"]) ** 2).mean(-1) * valid
        ).sum() / valid.sum()
        duration_loss = (
            ((prediction["duration"] - batch["duration"]) ** 2) * valid
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
            + 0.2 * pressure_loss
            + 0.1 * duration_loss
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
        if step == start_step or (step + 1) % 10 == 0:
            print(json.dumps(record))
        if args.save_every > 0 and (step + 1) % args.save_every == 0:
            _save_checkpoint(
                args.output, model, optimizer, step + 1, history, torch, training_config
            )
    calibrated_threshold = _calibrate_confidence_threshold(
        model,
        validation_corpus,
        episodes=args.calibrate_episodes,
        batch_size=args.batch_size,
        references=args.references,
        torch=torch,
    )
    training_config["calibrated_confidence_threshold"] = calibrated_threshold
    _save_checkpoint(
        args.output,
        model,
        optimizer,
        target_steps,
        history,
        torch,
        training_config,
        calibrated_threshold,
    )
    print(f"saved checkpoint: {args.output.resolve()}")
    return 0
