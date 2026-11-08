from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
import math
import os
from pathlib import Path
import tempfile
import uuid

import numpy as np

from .line_tasks import LineCollectionTask, LineTaskItem
from .storage import sanitize_writer_id


RAW_SCHEMA = "handwriting_line_raw_v1"
EXPORT_SCHEMA = "diffink_personal_export_v1"


class SampleProcessingError(ValueError):
    pass


class DatasetExportError(ValueError):
    def __init__(self, message: str, output_dir: Path):
        super().__init__(message)
        self.output_dir = output_dir


@dataclass
class ProcessedLine:
    item_id: str
    sample_id: str
    writer_id: str
    line_text: str
    split: str
    point_seq: np.ndarray
    char_points_idx: np.ndarray
    metrics: dict[str, float | int]
    warnings: list[str]
    source_path: Path


@dataclass
class AuditResult:
    output_dir: Path
    accepted: list[ProcessedLine]
    rejected: list[dict[str, str]]

    @property
    def is_clean(self) -> bool:
        return not self.rejected


def rdp_indices(points: np.ndarray, epsilon: float) -> list[int]:
    """Return retained indexes for Ramer-Douglas-Peucker simplification."""
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("RDP 输入必须是 [N, 2] 坐标")
    if epsilon < 0:
        raise ValueError("RDP epsilon 不能为负数")
    if len(points) <= 2:
        return list(range(len(points)))

    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        segment = points[end] - points[start]
        interior = points[start + 1 : end]
        if len(interior) == 0:
            continue
        norm = float(np.linalg.norm(segment))
        if norm <= 1e-12:
            distances = np.linalg.norm(interior - points[start], axis=1)
        else:
            relative = interior - points[start]
            cross_magnitude = np.abs(
                segment[0] * relative[:, 1] - segment[1] * relative[:, 0]
            )
            distances = cross_magnitude / norm
        offset = int(np.argmax(distances))
        distance = float(distances[offset])
        if distance > epsilon:
            index = start + 1 + offset
            keep.add(index)
            stack.append((start, index))
            stack.append((index, end))
    return sorted(keep)


def preprocess_raw_sample(
    path: Path,
    vocabulary: set[str],
    *,
    expected_item: LineTaskItem | None = None,
    expected_writer_id: str | None = None,
    epsilon: float = 0.4,
    min_points: int = 200,
    max_points: int = 2000,
) -> ProcessedLine:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SampleProcessingError("原始 JSON 无法读取") from error
    if payload.get("schema_version") != RAW_SCHEMA:
        raise SampleProcessingError("不支持的原始整行样本版本")
    try:
        sample_id = str(payload["sample_id"])
        writer_id = str(payload["writer_id"])
        line_text = str(payload["line_text"])
        split = str(payload["split"])
        char_ends = [int(value) for value in payload["char_point_ends"]]
        strokes = payload["strokes"]
        item_id = str(payload["task"]["item_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise SampleProcessingError("原始 JSON 缺少必要字段") from error
    if expected_item is not None:
        if item_id != expected_item.item_id:
            raise SampleProcessingError("样本 item_id 与任务状态不一致")
        if line_text != expected_item.text or split != expected_item.split:
            raise SampleProcessingError("样本文本或 split 与任务状态不一致")
        if expected_item.sample_id and sample_id != expected_item.sample_id:
            raise SampleProcessingError("样本不是任务状态指定的最新版本")
    if expected_writer_id is not None and writer_id != expected_writer_id:
        raise SampleProcessingError("样本 writer_id 与任务不一致")
    unknown = sorted({character for character in line_text if character not in vocabulary})
    if unknown:
        raise SampleProcessingError(
            "包含字表外字符：" + " ".join(repr(value) for value in unknown)
        )
    if split not in {"train", "val"}:
        raise SampleProcessingError("split 必须是 train 或 val")
    if len(char_ends) != len(line_text):
        raise SampleProcessingError("字符结束点数量与文本长度不一致")
    if not char_ends or any(
        right <= left for left, right in zip(char_ends, char_ends[1:])
    ):
        raise SampleProcessingError("字符结束点必须严格递增")
    if not isinstance(strokes, list) or not strokes:
        raise SampleProcessingError("样本没有笔画")

    parsed_strokes: list[dict[str, np.ndarray]] = []
    raw_coordinates: list[np.ndarray] = []
    raw_pressures: list[np.ndarray] = []
    raw_times: list[np.ndarray] = []
    stroke_end_counts: list[int] = []
    point_count = 0
    last_global_time = -1
    for stroke_value in strokes:
        point_values = stroke_value.get("points") if isinstance(stroke_value, dict) else None
        if not isinstance(point_values, list) or not point_values:
            raise SampleProcessingError("存在空笔画")
        try:
            coordinates = np.asarray(
                [[float(point["x"]), float(point["y"])] for point in point_values],
                dtype=np.float64,
            )
            pressures = np.asarray(
                [float(point["pressure"]) for point in point_values], dtype=np.float64
            )
            times = np.asarray(
                [int(point["t_ms"]) for point in point_values], dtype=np.int64
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SampleProcessingError("笔画点字段无效") from error
        if not np.isfinite(coordinates).all() or not np.isfinite(pressures).all():
            raise SampleProcessingError("轨迹包含非有限数值")
        if np.any((pressures < 0) | (pressures > 1)):
            raise SampleProcessingError("压力值超出 [0, 1]")
        if np.any(np.diff(times) < 0) or int(times[0]) < last_global_time:
            raise SampleProcessingError("时间戳没有全局递增")
        last_global_time = int(times[-1])
        point_count += len(coordinates)
        stroke_end_counts.append(point_count)
        raw_coordinates.append(coordinates)
        raw_pressures.append(pressures)
        raw_times.append(times)
        parsed_strokes.append(
            {"coordinates": coordinates, "pressures": pressures, "times": times}
        )
    if char_ends[-1] != point_count:
        raise SampleProcessingError("最后字符结束点不等于原始总点数")
    stroke_end_set = set(stroke_end_counts)
    if any(end not in stroke_end_set for end in char_ends):
        raise SampleProcessingError("字符结束点没有落在笔画末端")

    all_coordinates = np.concatenate(raw_coordinates, axis=0)
    mean_x = float(all_coordinates[:, 0].mean())
    mean_y = float(all_coordinates[:, 1].mean())
    std_y = float(all_coordinates[:, 1].std())
    if not math.isfinite(std_y) or std_y <= 1e-6:
        raise SampleProcessingError("整行纵向方差过小，无法归一化")

    simplified_strokes: list[np.ndarray] = []
    for parsed in parsed_strokes:
        coordinates = parsed["coordinates"]
        normalized = np.column_stack(
            (
                (coordinates[:, 0] - mean_x) / std_y,
                (mean_y - coordinates[:, 1]) / std_y,
            )
        )
        retained = rdp_indices(normalized, epsilon)
        simplified_strokes.append(normalized[retained].astype(np.float32))

    rows: list[list[float]] = []
    processed_char_ends: list[int] = []
    for raw_stroke_end, simplified in zip(stroke_end_counts, simplified_strokes):
        for x, y in simplified:
            rows.append([float(x), float(y), 1.0, 0.0, 0.0])
        if not rows:
            raise SampleProcessingError("简化后出现空轨迹")
        rows[-1][2:5] = [0.0, 1.0, 0.0]
        if raw_stroke_end in char_ends:
            rows[-1][2:5] = [0.0, 0.0, 1.0]
            processed_char_ends.append(len(rows))
    point_seq = np.asarray(rows, dtype=np.float32)
    char_points_idx = np.asarray(processed_char_ends, dtype=np.int32)
    if len(char_points_idx) != len(line_text):
        raise SampleProcessingError("简化后的字符结束点数量不正确")
    if int(char_points_idx[-1]) != len(point_seq):
        raise SampleProcessingError("简化后的最终字符结束点不正确")
    if not np.allclose(point_seq[:, 2:5].sum(axis=1), 1.0):
        raise SampleProcessingError("简化后的状态不是 one-hot")
    if not min_points <= len(point_seq) <= max_points:
        raise SampleProcessingError(
            f"简化后点数为 {len(point_seq)}，要求 {min_points}–{max_points}"
        )

    all_pressures = np.concatenate(raw_pressures)
    all_times = np.concatenate(raw_times)
    time_gaps = np.diff(all_times)
    points_per_char = len(point_seq) / len(line_text)
    metrics: dict[str, float | int] = {
        "raw_point_count": int(point_count),
        "point_count": int(len(point_seq)),
        "stroke_count": int(len(simplified_strokes)),
        "character_count": int(len(line_text)),
        "x_mean": float(point_seq[:, 0].mean()),
        "y_mean": float(point_seq[:, 1].mean()),
        "y_std": float(point_seq[:, 1].std()),
        "points_per_character": float(points_per_char),
        "positive_pressure_ratio": float(np.mean(all_pressures > 0.01)),
        "p99_time_gap_ms": float(np.percentile(time_gaps, 99))
        if len(time_gaps)
        else 0.0,
        "normalization_mean_x": mean_x,
        "normalization_mean_y": mean_y,
        "normalization_std_y": std_y,
        "rdp_epsilon": float(epsilon),
    }
    warnings: list[str] = []
    if abs(float(metrics["y_mean"])) > 0.25:
        warnings.append("简化后 y 均值偏离官方分布")
    if not 0.75 <= float(metrics["y_std"]) <= 1.5:
        warnings.append("简化后 y 标准差偏离官方分布")
    if not 8 <= points_per_char <= 80:
        warnings.append("平均每字点数异常")
    if float(metrics["positive_pressure_ratio"]) < 0.8:
        warnings.append("有效压力点比例偏低")
    if float(metrics["p99_time_gap_ms"]) > 250:
        warnings.append("采样时间间隔存在较大跳变")
    return ProcessedLine(
        item_id=item_id,
        sample_id=sample_id,
        writer_id=writer_id,
        line_text=line_text,
        split=split,
        point_seq=point_seq,
        char_points_idx=char_points_idx,
        metrics=metrics,
        warnings=warnings,
        source_path=path,
    )


def audit_task_items(
    output_root: Path,
    task: LineCollectionTask,
    vocabulary: set[str],
    items: list[LineTaskItem],
    *,
    epsilon: float = 0.4,
    category: str = "audits",
) -> AuditResult:
    root = Path(output_root)
    output_dir = _versioned_output_dir(root / category / task.task_id)
    preview_dir = output_dir / "previews"
    accepted: list[ProcessedLine] = []
    rejected: list[dict[str, str]] = []
    for item in items:
        if item.status != "completed" or not item.sample_path:
            rejected.append(
                {"item_id": item.item_id, "text": item.text, "reason": "任务尚未完成"}
            )
            continue
        sample_path = root / Path(item.sample_path)
        try:
            sample = preprocess_raw_sample(
                sample_path,
                vocabulary,
                expected_item=item,
                expected_writer_id=task.writer_id,
                epsilon=epsilon,
            )
            accepted.append(sample)
            write_svg_preview(
                preview_dir / f"{item.source_index + 1:04d}_{sample.sample_id}.svg",
                sample,
            )
        except SampleProcessingError as error:
            rejected.append(
                {"item_id": item.item_id, "text": item.text, "reason": str(error)}
            )
    _write_audit_files(output_dir, task, accepted, rejected)
    return AuditResult(output_dir=output_dir, accepted=accepted, rejected=rejected)


def export_task_dataset(
    output_root: Path,
    task: LineCollectionTask,
    vocabulary: set[str],
    *,
    expected_train: int = 200,
    expected_val: int = 20,
    epsilon: float = 0.4,
) -> AuditResult:
    result = audit_task_items(
        output_root,
        task,
        vocabulary,
        list(task.items),
        epsilon=epsilon,
        category="exports",
    )
    train_samples = [sample for sample in result.accepted if sample.split == "train"]
    val_samples = [sample for sample in result.accepted if sample.split == "val"]
    if (
        result.rejected
        or len(train_samples) != expected_train
        or len(val_samples) != expected_val
    ):
        raise DatasetExportError(
            "数据集未达到导出要求："
            f"train {len(train_samples)}/{expected_train}，"
            f"val {len(val_samples)}/{expected_val}，"
            f"拒绝 {len(result.rejected)}。详情见 {result.output_dir}",
            result.output_dir,
        )
    _write_hdf5(result.output_dir / "personal_train.h5", train_samples)
    _write_hdf5(result.output_dir / "personal_val.h5", val_samples)
    writer_payload = {"train": [task.writer_id], "test": []}
    _atomic_json_file(result.output_dir / "personal_writer.json", writer_payload)
    _write_training_launchers(result.output_dir, task)
    return result


def write_svg_preview(path: Path, sample: ProcessedLine) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    coordinates = sample.point_seq[:, :2]
    min_x, min_y = coordinates.min(axis=0)
    max_x, max_y = coordinates.max(axis=0)
    width, height, margin = 1600.0, 260.0, 24.0
    span_x = max(float(max_x - min_x), 1e-6)
    span_y = max(float(max_y - min_y), 1e-6)
    scale = min((width - 2 * margin) / span_x, (height - 64 - 2 * margin) / span_y)

    polylines: list[str] = []
    circles: list[str] = []
    current: list[str] = []
    char_end_rows = set(int(value) - 1 for value in sample.char_points_idx)
    for index, row in enumerate(sample.point_seq):
        x = margin + (float(row[0]) - float(min_x)) * scale
        y = margin + (float(max_y) - float(row[1])) * scale
        current.append(f"{x:.2f},{y:.2f}")
        if index in char_end_rows:
            circles.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.2" fill="#16a34a"/>'
            )
        if row[3] == 1 or row[4] == 1:
            polylines.append(
                '<polyline points="'
                + " ".join(current)
                + '" fill="none" stroke="#111827" stroke-width="1.7" '
                'stroke-linecap="round" stroke-linejoin="round"/>'
            )
            current = []
    text_y = height - 18
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" '
        f'height="{int(height)}" viewBox="0 0 {int(width)} {int(height)}">\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        + "\n".join(polylines)
        + "\n"
        + "\n".join(circles)
        + f'\n<text x="{margin}" y="{text_y}" font-family="Microsoft YaHei, sans-serif" '
        f'font-size="20" fill="#334155">{escape(sample.line_text)}</text>\n'
        "</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")


def _write_hdf5(path: Path, samples: list[ProcessedLine]) -> None:
    try:
        import h5py
    except ImportError as error:
        raise DatasetExportError(
            "缺少 h5py；请从 offline_wheels 安装现有离线 wheel", path.parent
        ) from error
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    try:
        string_type = h5py.string_dtype(encoding="utf-8")
        with h5py.File(temp_name, "w") as handle:
            handle.attrs["schema_version"] = EXPORT_SCHEMA
            handle.attrs["normalization"] = "x=(x-mean_x)/std_y;y=(mean_y-y)/std_y"
            handle.attrs["rdp_epsilon"] = 0.4
            for index, sample in enumerate(samples):
                group = handle.create_group(f"line_{index:06d}")
                group.create_dataset("writer_id", data=sample.writer_id, dtype=string_type)
                group.create_dataset("line_text", data=sample.line_text, dtype=string_type)
                group.create_dataset(
                    "point_seq", data=sample.point_seq, dtype=np.float32
                )
                group.create_dataset(
                    "char_points_idx",
                    data=sample.char_points_idx,
                    dtype=np.int32,
                )
                group.attrs["source_sample_id"] = sample.sample_id
                group.attrs["source_item_id"] = sample.item_id
            handle.flush()
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _write_audit_files(
    output_dir: Path,
    task: LineCollectionTask,
    accepted: list[ProcessedLine],
    rejected: list[dict[str, str]],
) -> None:
    report = {
        "schema_version": EXPORT_SCHEMA,
        "task_id": task.task_id,
        "writer_id": task.writer_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "split_counts": {
            "train": sum(sample.split == "train" for sample in accepted),
            "val": sum(sample.split == "val" for sample in accepted),
        },
        "samples": [
            {
                "item_id": sample.item_id,
                "sample_id": sample.sample_id,
                "split": sample.split,
                "line_text": sample.line_text,
                "source_path": str(sample.source_path),
                "metrics": sample.metrics,
                "warnings": sample.warnings,
            }
            for sample in accepted
        ],
        "rejected": rejected,
    }
    _atomic_json_file(output_dir / "export_report.json", report)
    rejected_path = output_dir / "rejected.csv"
    with rejected_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["item_id", "text", "reason"])
        writer.writeheader()
        writer.writerows(rejected)


def _write_training_launchers(output_dir: Path, task: LineCollectionTask) -> None:
    vocabulary_path = Path(task.vocabulary_path).resolve()
    try:
        project_root = vocabulary_path.parents[2]
    except IndexError:
        return
    tuning_script = project_root / "tune_dit_single.py"
    python_path = project_root / ".venv-demo" / "Scripts" / "python.exe"
    if not tuning_script.is_file() or not python_path.is_file():
        return
    train_file = (output_dir / "personal_train.h5").resolve()
    val_file = (output_dir / "personal_val.h5").resolve()
    writer_file = (output_dir / "personal_writer.json").resolve()
    common = (
        f'"{python_path}" "{tuning_script}" ^\n'
        f'  --train-file "{train_file}" ^\n'
        f'  --val-file "{val_file}" ^\n'
        f'  --writer-file "{writer_file}" ^\n'
        f'  --text-file "{vocabulary_path}"'
    )
    full_command = (
        "@echo off\n"
        "setlocal\n"
        f'cd /d "{project_root}"\n'
        + common
        + "\n"
        "if errorlevel 1 pause\n"
    )
    smoke_command = (
        "@echo off\n"
        "setlocal\n"
        f'cd /d "{project_root}"\n'
        + common
        + " ^\n"
        "  --max-steps 1 ^\n"
        "  --grad-accum 1 ^\n"
        "  --model-only-checkpoint\n"
        "pause\n"
    )
    (output_dir / "run_personal_tune.cmd").write_text(
        full_command, encoding="utf-8-sig"
    )
    (output_dir / "smoke_test_one_step.cmd").write_text(
        smoke_command, encoding="utf-8-sig"
    )


def _atomic_json_file(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _versioned_output_dir(parent: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = parent / f"{timestamp}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path
