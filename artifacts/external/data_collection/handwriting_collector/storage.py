from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

import numpy as np

from .models import Trajectory, is_cjk_character
from .line_tasks import LineCollectionTask, LineTaskItem
from .tasks import CollectionTask, TaskItem
from .tasks import _atomic_json_write
from .paths import native_path


def sanitize_writer_id(writer_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", writer_id.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise ValueError("书写者 ID 不能为空或只包含特殊字符")
    return cleaned[:80]


class SampleStorage:
    def __init__(self, output_root: Path):
        self.root = Path(output_root)

    def save_single(
        self,
        *,
        writer_id: str,
        task: CollectionTask,
        item: TaskItem,
        trajectory: Trajectory,
        canvas_width: int,
        canvas_height: int,
        device_pixel_ratio: float,
        sample_id: str | None = None,
    ) -> tuple[str, Path]:
        writer = sanitize_writer_id(writer_id)
        if task.writer_id != writer_id:
            raise ValueError("当前书写者 ID 与任务创建时不一致")
        if not is_cjk_character(item.character):
            raise ValueError("任务字符不是单个汉字")
        trajectory.validate(canvas_width, canvas_height)
        sample_id = sample_id or str(uuid.uuid4())
        codepoint = f"U+{ord(item.character):04X}"
        json_path = self.root / "samples" / writer / codepoint / f"{sample_id}.json"
        npy_path = self.root / "legacy" / writer / f"{sample_id}.npy"
        text_dir = self.root / "legacy" / writer / sample_id
        for target in (json_path, npy_path, text_dir):
            if target.exists():
                raise FileExistsError(f"样本目标已存在：{target}")

        point_seq, char_points_idx = trajectory.to_point_seq()
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema_version": "handwriting_single_v1",
            "sample_id": sample_id,
            "writer_id": writer_id,
            "character": item.character,
            "codepoint": codepoint,
            "task": {
                "task_id": task.task_id,
                "item_id": item.item_id,
                "source": task.source,
                "source_index": item.source_index,
                "repeat_index": item.repeat_index,
                "repeat_total": item.repeat_total,
            },
            "capture": {
                "created_at": created_at,
                "input_type": "tablet",
                "canvas_width": int(canvas_width),
                "canvas_height": int(canvas_height),
                "device_pixel_ratio": float(device_pixel_ratio),
                "coordinate_space": "logical_px",
                "duration_ms": trajectory.duration_ms,
            },
            "strokes": [
                stroke.to_dict(index) for index, stroke in enumerate(trajectory.strokes)
            ],
            "stats": {
                "stroke_count": len(trajectory.strokes),
                "point_count": trajectory.point_count,
            },
        }
        legacy = {
            "point_seq": point_seq,
            "line_text": item.character,
            "char_points_idx": np.asarray(char_points_idx, dtype=np.int32),
            "writer_id": writer_id,
            "format_version": "diffink_v1_char_end",
        }

        staging_parent = self.root / ".staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"{sample_id}-", dir=staging_parent))
        published: list[Path] = []
        try:
            staged_json = staging / "sample.json"
            with staged_json.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())

            staged_npy = staging / "sample.npy"
            with staged_npy.open("wb") as stream:
                np.save(stream, legacy, allow_pickle=True)
                stream.flush()
                os.fsync(stream.fileno())

            staged_text = staging / "text"
            staged_text.mkdir()
            _write_legacy_text(staged_text, point_seq, item.character, char_points_idx, writer_id)

            json_path.parent.mkdir(parents=True, exist_ok=True)
            npy_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(native_path(staged_json), native_path(json_path))
            published.append(json_path)
            os.replace(native_path(staged_npy), native_path(npy_path))
            published.append(npy_path)
            os.replace(native_path(staged_text), native_path(text_dir))
            published.append(text_dir)
        except Exception:
            for path in reversed(published):
                if path.is_dir():
                    shutil.rmtree(native_path(path), ignore_errors=True)
                else:
                    Path(native_path(path)).unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(native_path(staging), ignore_errors=True)
        return sample_id, json_path

    def reconcile_task(self, task: CollectionTask) -> int:
        """Recover progress when a sample committed before task state was updated."""
        recovered = 0
        sample_root = self.root / "samples"
        if not sample_root.exists():
            return recovered
        by_item = {item.item_id: item for item in task.items if item.status != "completed"}
        if not by_item:
            return recovered
        for path in sample_root.glob("*/*/*.json"):
            try:
                with path.open("r", encoding="utf-8") as stream:
                    payload = json.load(stream)
                task_data = payload.get("task", {})
                if task_data.get("task_id") != task.task_id:
                    continue
                item = by_item.get(task_data.get("item_id"))
                if item is not None:
                    item.status = "completed"
                    item.sample_id = payload["sample_id"]
                    recovered += 1
            except (OSError, KeyError, json.JSONDecodeError):
                continue
        return recovered

    def save_line_raw(
        self,
        *,
        writer_id: str,
        task: LineCollectionTask,
        item: LineTaskItem,
        trajectory: Trajectory,
        char_ends: list[int],
        canvas_width: int,
        canvas_height: int,
        device_pixel_ratio: float,
        logical_dpi_x: float,
        logical_dpi_y: float,
        capture_route: str,
        sample_id: str | None = None,
    ) -> tuple[str, Path]:
        writer = sanitize_writer_id(writer_id)
        if task.writer_id != writer_id:
            raise ValueError("当前书写者 ID 与整行任务创建时不一致")
        if capture_route not in {"direct_surface", "moonlight_pen"}:
            raise ValueError("未知的采集链路")
        if task.capture_route != capture_route:
            raise ValueError("当前采集链路与整行任务创建时不一致")
        if item not in task.items:
            raise ValueError("当前整行项目不属于该任务")
        trajectory.validate(canvas_width, canvas_height)
        ends = [int(value) for value in char_ends]
        if len(ends) != len(item.text):
            raise ValueError(
                f"字符结束点数量应为 {len(item.text)}，实际为 {len(ends)}"
            )
        if any(right <= left for left, right in zip(ends, ends[1:])):
            raise ValueError("字符结束点必须严格递增")
        if not ends or ends[-1] != trajectory.point_count:
            raise ValueError("最后一个字符结束点必须等于总点数")
        stroke_ends: list[int] = []
        count = 0
        for stroke in trajectory.strokes:
            count += len(stroke.points)
            stroke_ends.append(count)
        invalid_boundaries = [end for end in ends if end not in set(stroke_ends)]
        if invalid_boundaries:
            raise ValueError("字符结束点必须位于抬笔后的笔画末端")

        sample_id = sample_id or str(uuid.uuid4())
        json_path = (
            self.root
            / "line_samples"
            / writer
            / task.task_id
            / f"{sample_id}.json"
        )
        if json_path.exists():
            raise FileExistsError(f"整行样本目标已存在：{json_path}")
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema_version": "handwriting_line_raw_v1",
            "sample_id": sample_id,
            "writer_id": writer_id,
            "line_text": item.text,
            "split": item.split,
            "char_point_ends": ends,
            "supersedes": item.sample_id
            or (item.sample_history[-1] if item.sample_history else None),
            "task": {
                "task_id": task.task_id,
                "item_id": item.item_id,
                "source": task.source,
                "source_index": item.source_index,
            },
            "capture": {
                "created_at": created_at,
                "input_type": "tablet",
                "capture_route": capture_route,
                "canvas_width": int(canvas_width),
                "canvas_height": int(canvas_height),
                "device_pixel_ratio": float(device_pixel_ratio),
                "logical_dpi_x": float(logical_dpi_x),
                "logical_dpi_y": float(logical_dpi_y),
                "coordinate_space": "logical_px_qt_y_down",
                "duration_ms": trajectory.duration_ms,
            },
            "strokes": [
                stroke.to_dict(index) for index, stroke in enumerate(trajectory.strokes)
            ],
            "stats": {
                "stroke_count": len(trajectory.strokes),
                "point_count": trajectory.point_count,
                "character_count": len(item.text),
            },
        }
        _atomic_json_write(json_path, payload)
        return sample_id, json_path

    def reconcile_line_task(self, task: LineCollectionTask) -> int:
        """Recover newest durable line samples missing from task state."""
        recovered = 0
        writer = sanitize_writer_id(task.writer_id)
        sample_root = self.root / "line_samples" / writer / task.task_id
        if not sample_root.exists():
            return recovered
        candidates: dict[str, tuple[float, Path, dict]] = {}
        for path in sample_root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                task_data = payload.get("task", {})
                if task_data.get("task_id") != task.task_id:
                    continue
                item_id = task_data["item_id"]
                timestamp = path.stat().st_mtime
                if item_id not in candidates or timestamp > candidates[item_id][0]:
                    candidates[item_id] = (timestamp, path, payload)
            except (OSError, KeyError, json.JSONDecodeError):
                continue
        for item in task.items:
            if item.status == "completed" or item.item_id not in candidates:
                continue
            _, path, payload = candidates[item.item_id]
            item.status = "completed"
            item.sample_id = payload["sample_id"]
            item.sample_path = path.relative_to(self.root).as_posix()
            recovered += 1
        return recovered


def save_line_legacy(
    output_root: Path,
    writer_id: str,
    line_text: str,
    point_seq: np.ndarray,
    char_points_idx: list[int],
) -> Path:
    writer = sanitize_writer_id(writer_id)
    base_dir = Path(output_root) / "legacy" / writer
    base_dir.mkdir(parents=True, exist_ok=True)
    max_number = -1
    for path in base_dir.glob(f"{writer}_line_*.npy"):
        try:
            max_number = max(max_number, int(path.stem.rsplit("_", 1)[1]))
        except ValueError:
            continue
    name = f"{writer}_line_{max_number + 1:04d}"
    npy_path = base_dir / f"{name}.npy"
    sample = {
        "point_seq": point_seq,
        "line_text": line_text,
        "char_points_idx": np.asarray(char_points_idx, dtype=np.int32),
        "writer_id": writer_id,
        "format_version": "diffink_v1_char_end",
    }
    with npy_path.open("xb") as stream:
        np.save(stream, sample, allow_pickle=True)
    text_dir = base_dir / name
    text_dir.mkdir()
    _write_legacy_text(text_dir, point_seq, line_text, char_points_idx, writer_id)
    return npy_path


def _write_legacy_text(
    directory: Path,
    point_seq: np.ndarray,
    text: str,
    char_points_idx: list[int],
    writer_id: str,
) -> None:
    with (directory / "point_seq.txt").open("w", encoding="utf-8") as stream:
        for row in point_seq:
            stream.write(
                f"{row[0]:.2f} {row[1]:.2f} "
                f"{int(row[2])} {int(row[3])} {int(row[4])}\n"
            )
    (directory / "line_text.txt").write_text(text, encoding="utf-8")
    (directory / "char_points_idx.txt").write_text(
        " ".join(map(str, char_points_idx)), encoding="utf-8"
    )
    (directory / "writer_id.txt").write_text(writer_id, encoding="utf-8")

