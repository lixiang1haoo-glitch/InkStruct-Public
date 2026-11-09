from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid

from .models import is_cjk_character
from .paths import native_path


@dataclass
class TaskItem:
    item_id: str
    character: str
    source_index: int
    repeat_index: int
    repeat_total: int
    status: str = "pending"
    sample_id: str | None = None


@dataclass
class CollectionTask:
    task_id: str
    name: str
    source: str
    writer_id: str
    items: list[TaskItem]
    cursor: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = "handwriting_task_v1"

    @classmethod
    def create(
        cls,
        name: str,
        source: str,
        writer_id: str,
        characters: list[tuple[str, int, int]],
    ) -> "CollectionTask":
        items: list[TaskItem] = []
        for character, repeats, source_index in characters:
            for repeat_index in range(1, repeats + 1):
                items.append(
                    TaskItem(
                        item_id=str(uuid.uuid4()),
                        character=character,
                        source_index=source_index,
                        repeat_index=repeat_index,
                        repeat_total=repeats,
                    )
                )
        return cls(str(uuid.uuid4()), name, source, writer_id, items)

    @property
    def completed_count(self) -> int:
        return sum(item.status == "completed" for item in self.items)

    @property
    def is_complete(self) -> bool:
        return bool(self.items) and self.completed_count == len(self.items)

    def current_item(self) -> TaskItem | None:
        if self.is_complete or not self.items:
            return None
        count = len(self.items)
        for offset in range(count):
            index = (self.cursor + offset) % count
            if self.items[index].status == "pending":
                self.cursor = index
                return self.items[index]
        for offset in range(count):
            index = (self.cursor + offset) % count
            if self.items[index].status == "skipped":
                self.cursor = index
                return self.items[index]
        return None

    def complete_current(self, sample_id: str) -> None:
        item = self.current_item()
        if item is None:
            raise ValueError("任务中没有待采样字符")
        item.status = "completed"
        item.sample_id = sample_id
        self.cursor = (self.cursor + 1) % len(self.items)

    def skip_current(self) -> None:
        item = self.current_item()
        if item is None:
            return
        item.status = "skipped"
        self.cursor = (self.cursor + 1) % len(self.items)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "name": self.name,
            "source": self.source,
            "writer_id": self.writer_id,
            "cursor": self.cursor,
            "created_at": self.created_at,
            "items": [asdict(item) for item in self.items],
        }

    @classmethod
    def from_dict(cls, value: dict) -> "CollectionTask":
        if value.get("schema_version") != "handwriting_task_v1":
            raise ValueError("不支持的任务文件版本")
        items = [TaskItem(**item) for item in value["items"]]
        allowed = {"pending", "skipped", "completed"}
        if any(item.status not in allowed for item in items):
            raise ValueError("任务包含未知状态")
        return cls(
            task_id=value["task_id"],
            name=value["name"],
            source=value["source"],
            writer_id=value["writer_id"],
            items=items,
            cursor=int(value.get("cursor", 0)),
            created_at=value["created_at"],
            schema_version=value["schema_version"],
        )


def parse_character_file(path: Path, default_repeats: int) -> list[tuple[str, int, int]]:
    if default_repeats < 1:
        raise ValueError("默认重复次数必须大于等于 1")
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return _parse_txt(path, default_repeats)
    if suffix == ".csv":
        return _parse_csv(path, default_repeats)
    raise ValueError("仅支持 TXT 或 CSV 字表")


def _parse_txt(path: Path, repeats: int) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    errors: list[str] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            for character in line:
                if character.isspace():
                    continue
                if not is_cjk_character(character):
                    errors.append(f"第 {line_number} 行包含无效字符 {character!r}")
                elif character not in seen:
                    result.append((character, repeats, line_number - 1))
                    seen.add(character)
    if errors:
        raise ValueError("\n".join(errors))
    if not result:
        raise ValueError("字表中没有有效汉字")
    return result


def _parse_csv(path: Path, default_repeats: int) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    errors: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "character" not in reader.fieldnames:
            raise ValueError("CSV 必须包含 character 列")
        for line_number, row in enumerate(reader, 2):
            character = (row.get("character") or "").strip()
            repeat_text = (row.get("repeats") or "").strip()
            try:
                repeats = default_repeats if not repeat_text else int(repeat_text)
            except ValueError:
                errors.append(f"第 {line_number} 行 repeats 不是整数")
                continue
            if not is_cjk_character(character):
                errors.append(f"第 {line_number} 行必须是单个汉字")
            elif repeats < 1:
                errors.append(f"第 {line_number} 行 repeats 必须大于等于 1")
            elif character not in seen:
                result.append((character, repeats, line_number - 2))
                seen.add(character)
    if errors:
        raise ValueError("\n".join(errors))
    if not result:
        raise ValueError("字表中没有有效汉字")
    return result


class TaskRepository:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.tasks_dir = self.output_root / "tasks"

    def path_for(self, task_id: str) -> Path:
        return self.tasks_dir / task_id / "state.json"

    def save(self, task: CollectionTask) -> Path:
        path = self.path_for(task.task_id)
        _atomic_json_write(path, task.to_dict())
        return path

    def load(self, path: Path) -> CollectionTask:
        try:
            with Path(path).open("r", encoding="utf-8") as stream:
                return CollectionTask.from_dict(json.load(stream))
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"任务状态文件损坏：{path}") from error

    def incomplete_tasks(self) -> list[tuple[Path, CollectionTask]]:
        result = []
        for path in self.tasks_dir.glob("*/state.json"):
            try:
                task = self.load(path)
            except ValueError:
                continue
            if not task.is_complete:
                result.append((path, task))
        result.sort(key=lambda pair: pair[0].stat().st_mtime, reverse=True)
        return result


def _atomic_json_write(path: Path, value: dict) -> None:
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
        os.replace(native_path(temp_name), native_path(path))
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
