from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from ..document.schema import PageProfile, StyleProfile

RATINGS = {"good": "好", "bad": "不好", "review": "待复核"}
SESSION_VERSION = "inkstruct_review_v1"


def file_hash(path: Path) -> str | None:
    return sha256(path.read_bytes()).hexdigest() if path.exists() else None


def atomic_write(path: Path, data: bytes, expected_hash: str | None = None) -> str:
    """Preserve an existing file on errors or an external modification."""
    if file_hash(path) != expected_hash:
        raise ValueError("文件已被其他程序修改，请另存为新文件。")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".inkstruct-review-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if file_hash(path) != expected_hash:
            raise ValueError("保存期间文件发生变化，请另存为新文件。")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return sha256(data).hexdigest()


class SourceBuffer:
    """Map Qt's LF display back to raw newlines, preserving unrelated source bytes."""

    def __init__(self, source: str = ""):
        self.raw = source
        self.versions = {self.display: source}

    @property
    def display(self) -> str:
        return self.raw.replace("\r\n", "\n").replace("\r", "\n")

    def boundaries(self) -> list[int]:
        result, index = [0], 0
        while index < len(self.raw):
            index += 2 if self.raw[index : index + 2] == "\r\n" else 1
            result.append(index)
        return result

    def raw_to_display(self, offset: int) -> int:
        import bisect

        return bisect.bisect_left(self.boundaries(), offset)

    def update(self, displayed: str) -> None:
        if displayed == self.display:
            return
        if displayed in self.versions:
            self.raw = self.versions[displayed]
            return
        old = self.display
        start = 0
        while start < min(len(old), len(displayed)) and old[start] == displayed[start]:
            start += 1
        end = 0
        while (
            end < min(len(old), len(displayed)) - start
            and old[len(old) - end - 1] == displayed[len(displayed) - end - 1]
        ):
            end += 1
        offsets = self.boundaries()
        newline = "\r\n" if "\r\n" in self.raw else "\r" if "\r" in self.raw else "\n"
        inserted = displayed[start : len(displayed) - end].replace("\n", newline)
        self.raw = self.raw[: offsets[start]] + inserted + self.raw[offsets[len(old) - end] :]
        self.versions[displayed] = self.raw
        # Raw newline history is an optimization for native undo, not identity migration.
        while len(self.versions) > 128:
            del self.versions[next(iter(self.versions))]


@dataclass(frozen=True)
class Review:
    asset_id: str
    character: str
    rating: str
    note: str
    run_path: str
    writer_id: str
    generator: str
    profile_version: str
    context: str
    source_hash: str
    source_start: int
    updated_at: str


class ReviewBook:
    def __init__(self, reviews: list[Review] | None = None):
        self.records = {r.asset_id: r for r in reviews or []}
        self.undo_stack: list[tuple[str, Review | None, Review | None]] = []
        self.redo_stack: list[tuple[str, Review | None, Review | None]] = []

    def set(self, asset, rating: str | None, note: str, run: Path, source: str, start: int):
        if rating is not None and rating not in RATINGS:
            raise ValueError("Unknown review rating")
        value = json.loads(asset.original_json)
        current = self.records.get(asset.asset_id)
        record = (
            None
            if rating is None
            else Review(
                asset.asset_id,
                asset.character,
                rating,
                note,
                str(run.resolve()),
                value.get("writer_id", ""),
                value.get("generator", ""),
                value.get("profile_version", ""),
                source[max(0, start - 16) : start + 17],
                sha256(source.encode()).hexdigest(),
                start,
                datetime.now(UTC).isoformat(),
            )
        )
        self._apply(asset.asset_id, record)
        self.undo_stack.append((asset.asset_id, current, record))
        self.redo_stack.clear()

    def _apply(self, key, value):
        if value is None:
            self.records.pop(key, None)
        else:
            self.records[key] = value

    def undo(self):
        if self.undo_stack:
            key, before, after = self.undo_stack.pop()
            self._apply(key, before)
            self.redo_stack.append((key, before, after))

    def redo(self):
        if self.redo_stack:
            key, before, after = self.redo_stack.pop()
            self._apply(key, after)
            self.undo_stack.append((key, before, after))

    def csv_bytes(self) -> bytes:
        stream = io.StringIO(newline="")
        columns = list(Review.__dataclass_fields__)
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for record in self.records.values():
            row = asdict(record)
            row["rating"] = RATINGS[record.rating]
            # Safe when opened in a spreadsheet; preserve the literal value in JSON.
            writer.writerow(
                {
                    k: "'" + v
                    if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                    else v
                    for k, v in row.items()
                }
            )
        return stream.getvalue().encode("utf-8-sig")


def session_bytes(
    source: str, run: str, book: ReviewBook, page: PageProfile, style: StyleProfile
) -> bytes:
    return json.dumps(
        {
            "schema_version": SESSION_VERSION,
            "source": source,
            "run_path": run,
            "page": asdict(page),
            "style": asdict(style),
            "reviews": [asdict(r) for r in book.records.values()],
        },
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode()


def load_session(path: Path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("检查项目超过 16 MiB 限制")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("schema_version") != SESSION_VERSION:
        raise ValueError("不支持的检查项目版本")
    source, run = value["source"], value["run_path"]
    if not isinstance(source, str) or len(source) > 100_000 or not isinstance(run, str):
        raise ValueError("检查项目正文或路径无效")
    source.encode("utf-8")
    records = [Review(**r) for r in value["reviews"]]
    for r in records:
        if (
            not isinstance(r.asset_id, str)
            or not isinstance(r.rating, str)
            or r.rating not in RATINGS
            or len(r.asset_id) != 64
            or any(c not in "0123456789abcdef" for c in r.asset_id)
            or not isinstance(r.note, str)
            or not isinstance(r.character, str)
            or len(r.character) != 1
            or not all(
                isinstance(v, str)
                for v in (
                    r.run_path,
                    r.writer_id,
                    r.generator,
                    r.profile_version,
                    r.context,
                    r.source_hash,
                    r.updated_at,
                )
            )
            or not isinstance(r.source_start, int)
            or r.source_start < 0
        ):
            raise ValueError("检查项目包含无效标记")
    if len({r.asset_id for r in records}) != len(records):
        raise ValueError("检查项目包含重复字形评价")
    page, style = PageProfile(**value["page"]), StyleProfile(**value["style"])
    if not (
        20 <= page.width_mm <= 1000
        and 20 <= page.height_mm <= 1000
        and 2 <= style.em_mm <= 20
        and 3 <= style.line_height_mm <= 30
        and 0.05 <= style.stroke_width_mm <= 1
    ):
        raise ValueError("检查项目的页面或样式超出本版编辑器支持范围")
    return (
        SourceBuffer(source),
        run,
        ReviewBook(records),
        page,
        style,
    )
