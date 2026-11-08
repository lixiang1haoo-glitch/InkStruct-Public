from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from .tasks import _atomic_json_write


LINE_TASK_SCHEMA = "handwriting_line_task_v1"
BUILTIN_PROMPTS_SCHEMA = "diffink_builtin_lines_v2"
ALLOWED_ITEM_STATES = {"pending", "skipped", "completed"}
ALLOWED_SPLITS = {"train", "val"}


@dataclass
class LineTaskItem:
    item_id: str
    text: str
    split: str
    source_index: int
    status: str = "pending"
    sample_id: str | None = None
    sample_path: str | None = None
    sample_history: list[str] = field(default_factory=list)


@dataclass
class LineCollectionTask:
    task_id: str
    name: str
    source: str
    writer_id: str
    capture_route: str
    vocabulary_path: str
    items: list[LineTaskItem]
    cursor: int = 0
    pilot_size: int = 20
    pilot_approved: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = LINE_TASK_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source: str,
        writer_id: str,
        capture_route: str,
        vocabulary_path: Path,
        prompts: list[tuple[str, str, int, str | None]],
        pilot_size: int = 20,
    ) -> "LineCollectionTask":
        items = [
            LineTaskItem(
                item_id=item_id or str(uuid.uuid4()),
                text=text,
                split=split,
                source_index=source_index,
            )
            for text, split, source_index, item_id in prompts
        ]
        if len({item.item_id for item in items}) != len(items):
            raise ValueError("整行任务包含重复 task_id")
        return cls(
            task_id=str(uuid.uuid4()),
            name=name,
            source=source,
            writer_id=writer_id,
            capture_route=capture_route,
            vocabulary_path=str(Path(vocabulary_path).resolve()),
            items=items,
            pilot_size=pilot_size,
        )

    @property
    def completed_count(self) -> int:
        return sum(item.status == "completed" for item in self.items)

    @property
    def is_complete(self) -> bool:
        return bool(self.items) and self.completed_count == len(self.items)

    @property
    def pilot_items(self) -> list[LineTaskItem]:
        train_items = [item for item in self.items if item.split == "train"]
        return train_items[: self.pilot_size]

    @property
    def pilot_ready(self) -> bool:
        return bool(self.pilot_items) and all(
            item.status == "completed" for item in self.pilot_items
        )

    @property
    def blocked_for_pilot(self) -> bool:
        return self.pilot_ready and not self.pilot_approved

    def current_item(self) -> LineTaskItem | None:
        if not self.items or self.is_complete or self.blocked_for_pilot:
            return None
        allowed_ids: set[str] | None = None
        if not self.pilot_approved:
            allowed_ids = {item.item_id for item in self.pilot_items}
        count = len(self.items)
        for wanted_status in ("pending", "skipped"):
            for offset in range(count):
                index = (self.cursor + offset) % count
                item = self.items[index]
                if allowed_ids is not None and item.item_id not in allowed_ids:
                    continue
                if item.status == wanted_status:
                    self.cursor = index
                    return item
        return None

    def complete_current(self, sample_id: str, sample_path: str) -> None:
        item = self.current_item()
        if item is None:
            raise ValueError("整行任务中没有待采样项目")
        if item.sample_id:
            item.sample_history.append(item.sample_id)
        item.status = "completed"
        item.sample_id = sample_id
        item.sample_path = sample_path
        self.cursor = (self.cursor + 1) % len(self.items)

    def skip_current(self) -> None:
        item = self.current_item()
        if item is None:
            return
        item.status = "skipped"
        self.cursor = (self.cursor + 1) % len(self.items)

    def redo_item(self, item_id: str) -> None:
        index = next(
            (idx for idx, item in enumerate(self.items) if item.item_id == item_id),
            None,
        )
        if index is None:
            raise ValueError("未找到需要重录的整行任务")
        item = self.items[index]
        if item.sample_id:
            item.sample_history.append(item.sample_id)
        item.sample_id = None
        item.sample_path = None
        item.status = "pending"
        self.cursor = index

    def redo_previous(self) -> bool:
        if not self.items:
            return False
        for offset in range(1, len(self.items) + 1):
            index = (self.cursor - offset) % len(self.items)
            if self.items[index].status == "completed":
                self.redo_item(self.items[index].item_id)
                return True
        return False

    def approve_pilot(self) -> None:
        if not self.pilot_ready:
            raise ValueError("需要先完成全部试采行")
        self.pilot_approved = True

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "name": self.name,
            "source": self.source,
            "writer_id": self.writer_id,
            "capture_route": self.capture_route,
            "vocabulary_path": self.vocabulary_path,
            "cursor": self.cursor,
            "pilot_size": self.pilot_size,
            "pilot_approved": self.pilot_approved,
            "created_at": self.created_at,
            "items": [asdict(item) for item in self.items],
        }

    @classmethod
    def from_dict(cls, value: dict) -> "LineCollectionTask":
        if value.get("schema_version") != LINE_TASK_SCHEMA:
            raise ValueError("不支持的整行任务文件版本")
        items = [LineTaskItem(**item) for item in value["items"]]
        if any(item.status not in ALLOWED_ITEM_STATES for item in items):
            raise ValueError("整行任务包含未知状态")
        if any(item.split not in ALLOWED_SPLITS for item in items):
            raise ValueError("整行任务包含未知数据集分区")
        return cls(
            task_id=value["task_id"],
            name=value["name"],
            source=value["source"],
            writer_id=value["writer_id"],
            capture_route=value.get("capture_route", "direct_surface"),
            vocabulary_path=value["vocabulary_path"],
            items=items,
            cursor=int(value.get("cursor", 0)),
            pilot_size=int(value.get("pilot_size", 20)),
            pilot_approved=bool(value.get("pilot_approved", False)),
            created_at=value["created_at"],
            schema_version=value["schema_version"],
        )


def load_vocabulary(path: Path) -> set[str]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 DiffInk 字表：{path}") from error
    if not isinstance(value, dict) or not value:
        raise ValueError("DiffInk 字表必须是非空 JSON 对象")
    vocabulary = set(value)
    if any(len(character) != 1 for character in vocabulary):
        raise ValueError("DiffInk 字表中存在非单字符键")
    return vocabulary


def load_builtin_line_prompts(
    vocabulary: set[str],
) -> list[tuple[str, str, int, str | None]]:
    path = Path(__file__).with_name("assets") / "builtin_diffink_220.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取内置 DiffInk 整行任务：{path}") from error
    if value.get("schema_version") != BUILTIN_PROMPTS_SCHEMA:
        raise ValueError("不支持的内置 DiffInk 整行任务版本")
    train_rows = value.get("train")
    val_rows = value.get("val")
    if not isinstance(train_rows, list) or len(train_rows) != 200:
        raise ValueError("内置 DiffInk 训练任务必须正好包含 200 行")
    if not isinstance(val_rows, list) or len(val_rows) != 20:
        raise ValueError("内置 DiffInk 验证任务必须正好包含 20 行")

    prompts: list[tuple[str, str, int, str | None]] = []
    seen: set[str] = set()
    errors: list[str] = []
    for split, rows in (("train", train_rows), ("val", val_rows)):
        for split_index, row in enumerate(rows):
            source_index = len(prompts)
            text = row.get("text") if isinstance(row, dict) else None
            if not isinstance(text, str):
                errors.append(f"{split} 第 {split_index + 1} 行缺少 text")
                continue
            if not 15 <= len(text) <= 20:
                errors.append(
                    f"{split} 第 {split_index + 1} 行长度为 {len(text)}，要求 15–20"
                )
            unknown = sorted({character for character in text if character not in vocabulary})
            if unknown:
                errors.append(
                    f"{split} 第 {split_index + 1} 行包含字表外字符："
                    + " ".join(repr(value) for value in unknown)
                )
            if text in seen:
                errors.append(f"{split} 第 {split_index + 1} 行文本重复")
            seen.add(text)
            prompts.append(
                (
                    text,
                    split,
                    source_index,
                    f"builtin-{split}-{split_index + 1:03d}",
                )
            )
    if errors:
        raise ValueError("\n".join(errors[:50]))
    if len(prompts) != 220 or len(seen) != 220:
        raise ValueError("内置 DiffInk 整行任务数量或唯一性校验失败")
    return prompts


def parse_line_file(
    path: Path,
    vocabulary: set[str],
    *,
    train_count: int = 200,
    val_count: int = 20,
    min_length: int = 15,
    max_length: int = 20,
) -> list[tuple[str, str, int, str | None]]:
    path = Path(path)
    if path.suffix.lower() == ".txt":
        rows = _read_txt_rows(path)
    elif path.suffix.lower() == ".csv":
        rows = _read_csv_rows(path)
    else:
        raise ValueError("整行任务仅支持 TXT 或 CSV")
    if train_count < 1 or val_count < 1:
        raise ValueError("训练集与验证集数量必须大于零")

    errors: list[str] = []
    seen_text: dict[str, int] = {}
    validated: list[tuple[str, str | None, int, str | None]] = []
    for text, split, source_index, item_id in rows:
        display_line = source_index + 1
        if not min_length <= len(text) <= max_length:
            errors.append(
                f"第 {display_line} 行长度为 {len(text)}，要求 {min_length}–{max_length}"
            )
        unknown = sorted({character for character in text if character not in vocabulary})
        if unknown:
            errors.append(
                f"第 {display_line} 行包含字表外字符："
                + " ".join(repr(value) for value in unknown)
            )
        if text in seen_text:
            errors.append(
                f"第 {display_line} 行与第 {seen_text[text]} 行文本重复"
            )
        else:
            seen_text[text] = display_line
        if split not in (None, "", "train", "val", "reserve"):
            errors.append(f"第 {display_line} 行 split 必须是 train、val 或 reserve")
        validated.append((text, split or None, source_index, item_id))
    if errors:
        summary = "\n".join(errors[:50])
        if len(errors) > 50:
            summary += f"\n……另有 {len(errors) - 50} 项错误"
        raise ValueError(summary)

    has_explicit_split = any(row[1] is not None for row in validated)
    if has_explicit_split and any(row[1] is None for row in validated):
        raise ValueError("CSV 一旦使用 split 列，每个任务都必须填写 split")

    selected: list[tuple[str, str, int, str | None]] = []
    if has_explicit_split:
        train_rows = [row for row in validated if row[1] == "train"]
        val_rows = [row for row in validated if row[1] == "val"]
        if len(train_rows) < train_count or len(val_rows) < val_count:
            raise ValueError(
                f"有效任务不足：train 需要 {train_count} 行、实际 {len(train_rows)}；"
                f"val 需要 {val_count} 行、实际 {len(val_rows)}"
            )
        selected.extend(
            (text, "train", source_index, item_id)
            for text, _, source_index, item_id in train_rows[:train_count]
        )
        selected.extend(
            (text, "val", source_index, item_id)
            for text, _, source_index, item_id in val_rows[:val_count]
        )
    else:
        required = train_count + val_count
        if len(validated) < required:
            raise ValueError(f"有效任务至少需要 {required} 行，实际只有 {len(validated)}")
        for index, (text, _, source_index, item_id) in enumerate(validated[:required]):
            split = "train" if index < train_count else "val"
            selected.append((text, split, source_index, item_id))
    return selected


def _read_txt_rows(path: Path) -> list[tuple[str, None, int, None]]:
    rows: list[tuple[str, None, int, None]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for source_index, line in enumerate(stream):
            text = line.strip()
            if text:
                rows.append((text, None, source_index, None))
    if not rows:
        raise ValueError("文本文件中没有非空任务行")
    return rows


def _read_csv_rows(path: Path) -> list[tuple[str, str | None, int, str | None]]:
    rows: list[tuple[str, str | None, int, str | None]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "text" not in reader.fieldnames:
            raise ValueError("整行 CSV 必须包含 text 列")
        for source_index, row in enumerate(reader, 1):
            text = (row.get("text") or "").strip()
            if not text:
                raise ValueError(f"CSV 第 {source_index + 1} 行 text 为空")
            split = (row.get("split") or "").strip().lower() or None
            item_id = (row.get("task_id") or "").strip() or None
            rows.append((text, split, source_index, item_id))
    return rows


class LineTaskRepository:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.tasks_dir = self.output_root / "line_tasks"

    def path_for(self, task_id: str) -> Path:
        return self.tasks_dir / task_id / "state.json"

    def save(self, task: LineCollectionTask) -> Path:
        path = self.path_for(task.task_id)
        _atomic_json_write(path, task.to_dict())
        return path

    def load(self, path: Path) -> LineCollectionTask:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            return LineCollectionTask.from_dict(value)
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"整行任务状态文件损坏：{path}") from error

    def incomplete_tasks(self) -> list[tuple[Path, LineCollectionTask]]:
        return [pair for pair in self.all_tasks() if not pair[1].is_complete]

    def all_tasks(self) -> list[tuple[Path, LineCollectionTask]]:
        result: list[tuple[Path, LineCollectionTask]] = []
        for path in self.tasks_dir.glob("*/state.json"):
            try:
                task = self.load(path)
            except ValueError:
                continue
            result.append((path, task))
        result.sort(key=lambda pair: pair[0].stat().st_mtime, reverse=True)
        return result
