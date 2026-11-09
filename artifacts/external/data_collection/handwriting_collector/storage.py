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
from .tasks import CollectionTask, TaskItem
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
