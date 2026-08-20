from __future__ import annotations

import argparse
import json
import math
import pickle
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

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


def _local(points: np.ndarray) -> np.ndarray:
    minimum = points.min(axis=0)
    span = points.max(axis=0) - minimum
    return (points - minimum) / max(float(span.max()), 1e-6)


def _token(points: list[tuple[float, float]], *, order: int, count: int) -> np.ndarray:
    sampled = np.asarray(resample(points, 16), dtype=np.float32).reshape(-1)
    x0, y0, x1, y1 = bbox(points)
    extras = np.asarray(
        [x0, y0, x1, y1, order / max(count, 1), len(points) / 64.0, x1 - x0, y1 - y0],
        dtype=np.float32,
    )
    return np.concatenate((sampled, extras))


class CasiaCorpus:
    def __init__(self, lmdb_path: Path, structures: StructureRepository, max_records: int):
        lmdb, _ = _require_training_dependencies()
        self.environment = lmdb.open(
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
        confidences = []
        density = []
        for standard, user in zip(graph.strokes, user_strokes):
            standard_points = np.asarray(resample(standard.median, 8), dtype=np.float32)
            user_points = np.asarray(resample(user, 8), dtype=np.float32)
            residual = _local(user_points) - _local(standard_points)
            residuals.append(residual)
            confidences.append(math.exp(-5.0 * float(np.mean(np.linalg.norm(residual, axis=1)))))
            density.append(min(64, max(8, len(user))) / 64.0)
        stroke_count = len(graph.strokes)
        return {
            "style": np.stack(style_tokens[:96]),
            "structure": np.stack(structure_tokens),
            "residual": np.stack(residuals),
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
    residual = torch.zeros(batch, max_strokes, 8, 2)
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
        residual[row, :stroke_count] = torch.from_numpy(item["residual"])
        pressure[row, :stroke_count] = torch.from_numpy(item["pressure"])
        duration[row, :stroke_count] = torch.from_numpy(item["duration"])
        density[row, :stroke_count] = torch.from_numpy(item["density"])
        confidence[row, :stroke_count] = torch.from_numpy(item["confidence"])
        style_mask[row, :style_count] = False
        structure_mask[row, :stroke_count] = False
    return {
        "style": style,
        "structure": structure,
        "residual": residual,
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
    parser.add_argument("--smoke", action="store_true", help="run one optimisation step")
    return parser


def _save_checkpoint(path: Path, model, optimizer, steps: int, history: list[dict], torch) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".building")
    payload = model.checkpoint_payload()
    payload.update(
        {
            "steps": steps,
            "history": history[-100:],
            "optimizer_state": optimizer.state_dict(),
        }
    )
    torch.save(payload, temporary)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, torch = _require_training_dependencies()
    if not torch.cuda.is_available():
        raise RuntimeError("inkstruct train requires a CUDA-capable NVIDIA GPU")
    from .model import HierarchicalResidualModel

    random.seed(1001)
    np.random.seed(1001)
    torch.manual_seed(1001)
    corpus = CasiaCorpus(args.casia_lmdb, StructureRepository(args.database), args.max_records)
    model = HierarchicalResidualModel().cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    target_steps = 1 if args.smoke else args.steps
    start_step = 0
    history: list[dict] = []
    if args.resume:
        payload = torch.load(args.resume, map_location="cuda", weights_only=False)
        model.load_state_dict(payload["model_state"])
        if "optimizer_state" in payload:
            optimizer.load_state_dict(payload["optimizer_state"])
        start_step = int(payload.get("steps", 0))
        history.extend(payload.get("history", []))
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
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        record = {
            "step": step + 1,
            "loss": float(loss.detach()),
            "residual": float(residual_loss.detach()),
        }
        history.append(record)
        if step == start_step or (step + 1) % 10 == 0:
            print(json.dumps(record))
        if args.save_every > 0 and (step + 1) % args.save_every == 0:
            _save_checkpoint(args.output, model, optimizer, step + 1, history, torch)
    _save_checkpoint(args.output, model, optimizer, target_steps, history, torch)
    print(f"saved checkpoint: {args.output.resolve()}")
    return 0
