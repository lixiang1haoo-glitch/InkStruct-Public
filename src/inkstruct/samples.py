from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .schemas import RawPoint, RawSample, RawStroke

SUPPORTED_SCHEMA = "handwriting_single_v1"
INDEX_SCHEMA = "sample_index_v1"
DEFAULT_SAMPLE_ROOT = Path("artifacts/samples")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} is not numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} is not finite")
    return number


def load_raw_sample(path: Path, *, expected_writer: str | None = None) -> RawSample:
    path = Path(path).resolve()
    return parse_raw_sample(path.read_bytes(), path, expected_writer=expected_writer)


def parse_raw_sample(raw: bytes, path: Path, *, expected_writer: str | None = None) -> RawSample:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("sample must be a JSON object")
    if value.get("schema_version") != SUPPORTED_SCHEMA:
        raise ValueError(f"unsupported schema: {value.get('schema_version')!r}")
    writer_id = str(value.get("writer_id", "")).strip()
    if not writer_id:
        raise ValueError("writer_id is empty")
    if expected_writer is not None and writer_id != expected_writer:
        raise ValueError(f"writer mismatch: expected {expected_writer}, found {writer_id}")
    character = value.get("character")
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError("character must contain exactly one Unicode character")
    capture = dict(value.get("capture") or {})
    width = _finite(capture.get("canvas_width"), "capture.canvas_width")
    height = _finite(capture.get("canvas_height"), "capture.canvas_height")
    if width <= 0 or height <= 0:
        raise ValueError("canvas dimensions must be positive")
    raw_strokes = value.get("strokes")
    if not isinstance(raw_strokes, list) or not raw_strokes:
        raise ValueError("sample has no strokes")
    strokes: list[RawStroke] = []
    previous_global_time = -1
    for expected_index, stroke_value in enumerate(raw_strokes):
        point_values = stroke_value.get("points") if isinstance(stroke_value, dict) else None
        if not isinstance(point_values, list) or len(point_values) < 2:
            raise ValueError(f"stroke {expected_index} has fewer than two points")
        points: list[RawPoint] = []
        previous_time = -1
        for point_value in point_values:
            x = _finite(point_value.get("x"), "point.x")
            y = _finite(point_value.get("y"), "point.y")
            pressure = _finite(point_value.get("pressure", 0.5), "point.pressure")
            try:
                time = int(point_value.get("t_ms"))
            except (TypeError, ValueError) as error:
                raise ValueError("point.t_ms is not an integer") from error
            if not 0 <= x <= width or not 0 <= y <= height:
                raise ValueError(f"stroke {expected_index} contains an out-of-bounds point")
            if not 0 <= pressure <= 1:
                raise ValueError(f"stroke {expected_index} pressure is outside [0, 1]")
            if time < previous_time or time < previous_global_time:
                raise ValueError("timestamps are not globally monotonic")
            points.append(RawPoint(x, y, pressure, time))
            previous_time = time
            previous_global_time = time
        strokes.append(RawStroke(expected_index, points))
    codepoint = f"U+{ord(character):04X}"
    if value.get("codepoint") not in (None, codepoint):
        raise ValueError("codepoint does not match character")
    return RawSample(
        schema_version=SUPPORTED_SCHEMA,
        sample_id=str(value.get("sample_id") or path.stem),
        writer_id=writer_id,
        character=character,
        codepoint=codepoint,
        canvas_width=width,
        canvas_height=height,
        strokes=strokes,
        source_path=str(path),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        capture=capture,
    )


def scan_samples(source: Path, writer_id: str):
    source = Path(source).resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    paths = sorted(source.rglob("*.json"))
    accepted: list[RawSample] = []
    rejected: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    foreign = set()
    for path in paths:
        try:
            sample = load_raw_sample(path)
            if sample.writer_id != writer_id:
                foreign.add(sample.writer_id)
                raise ValueError(f"writer mismatch: expected {writer_id}, found {sample.writer_id}")
            if sample.sample_id in seen_ids:
                raise ValueError(f"duplicate sample_id: {sample.sample_id}")
            seen_ids.add(sample.sample_id)
            accepted.append(sample)
        except (OSError, ValueError, TypeError, AttributeError) as error:
            rejected.append({"path": str(path), "reason": str(error)})
    return accepted, rejected, sorted(foreign)


def sample_identity(sample):
    return sample.sample_id, sample.source_path, sample.source_sha256


def import_samples(
    source: Path,
    writer_id: str,
    destination_root: Path = DEFAULT_SAMPLE_ROOT,
    *,
    require_single_writer: bool = False,
) -> dict:
    source = Path(source).resolve()
    accepted, rejected, foreign = scan_samples(source, writer_id)
    if require_single_writer and foreign:
        raise ValueError(f"样本目录包含其他书写者：{'、'.join(foreign)}。请选择仅属于 {writer_id} 的目录。")
    return write_sample_index(source, writer_id, destination_root, accepted, rejected)


def write_sample_index(source, writer_id, destination_root, accepted, rejected):
    """Persist an already validated scan using the existing index and report format."""
    writer_dir = Path(destination_root).resolve() / writer_id
    writer_dir.mkdir(parents=True, exist_ok=True)
    index_path = writer_dir / "index.jsonl"
    temporary = index_path.with_suffix(".jsonl.building")
    with temporary.open("w", encoding="utf-8") as stream:
        for sample in accepted:
            stream.write(json.dumps(asdict(sample), ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
    temporary.replace(index_path)
    digest = sha256_file(index_path)
    report = {
        "schema_version": INDEX_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "writer_id": writer_id,
        "source": str(source),
        "index": str(index_path),
        "index_sha256": digest,
        "accepted_count": len(accepted),
        "unique_character_count": len({sample.character for sample in accepted}),
        "rejected_count": len(rejected),
        "rejected": rejected,
        "source_files_copied": False,
    }
    (writer_dir / "import_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def merge_indexes(
    index_paths: list[Path],
    writer_id: str,
    destination_root: Path = DEFAULT_SAMPLE_ROOT,
) -> dict:
    """Merge validated indexes without modifying any source index.

    Samples are de-duplicated first by sample id and then by source payload hash.
    A repeated id or payload is accepted only when its content is identical.
    Conflicting sample ids are reported and omitted rather than silently replacing
    an earlier sample.
    """
    if len(index_paths) < 2:
        raise ValueError("at least two sample indexes are required")
    resolved_indexes = [Path(path).resolve() for path in index_paths]
    samples_by_id: dict[str, RawSample] = {}
    ids_by_hash: dict[str, str] = {}
    duplicate_ids: list[dict[str, str]] = []
    duplicate_payloads: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    input_counts: list[dict[str, object]] = []
    for index_path in resolved_indexes:
        count = 0
        for sample in iter_index(index_path):
            count += 1
            if sample.writer_id != writer_id:
                raise ValueError(
                    f"writer mismatch in {index_path}: expected {writer_id}, found {sample.writer_id}"
                )
            previous = samples_by_id.get(sample.sample_id)
            if previous is not None:
                if previous.source_sha256 == sample.source_sha256:
                    duplicate_ids.append(
                        {"sample_id": sample.sample_id, "source_sha256": sample.source_sha256}
                    )
                else:
                    conflicts.append(
                        {
                            "sample_id": sample.sample_id,
                            "kept_sha256": previous.source_sha256,
                            "omitted_sha256": sample.source_sha256,
                        }
                    )
                continue
            previous_id = ids_by_hash.get(sample.source_sha256)
            if previous_id is not None:
                duplicate_payloads.append(
                    {
                        "sample_id": sample.sample_id,
                        "same_as_sample_id": previous_id,
                        "source_sha256": sample.source_sha256,
                    }
                )
                continue
            samples_by_id[sample.sample_id] = sample
            ids_by_hash[sample.source_sha256] = sample.sample_id
        input_counts.append({"index": str(index_path), "sample_count": count})
    writer_dir = Path(destination_root).resolve() / writer_id
    writer_dir.mkdir(parents=True, exist_ok=True)
    index_path = writer_dir / "index.jsonl"
    temporary = index_path.with_suffix(".jsonl.building")
    ordered = sorted(
        samples_by_id.values(), key=lambda sample: (ord(sample.character), sample.sample_id)
    )
    with temporary.open("w", encoding="utf-8") as stream:
        for sample in ordered:
            stream.write(json.dumps(asdict(sample), ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
    temporary.replace(index_path)
    report = {
        "schema_version": "sample_index_merge_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "writer_id": writer_id,
        "inputs": input_counts,
        "index": str(index_path),
        "index_sha256": sha256_file(index_path),
        "sample_count": len(ordered),
        "unique_character_count": len({sample.character for sample in ordered}),
        "duplicate_id_count": len(duplicate_ids),
        "duplicate_payload_count": len(duplicate_payloads),
        "conflict_count": len(conflicts),
        "duplicate_ids": duplicate_ids,
        "duplicate_payloads": duplicate_payloads,
        "conflicts": conflicts,
        "source_indexes_modified": False,
    }
    (writer_dir / "merge_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def replace_index_samples(
    index_path: Path,
    replacement_index_path: Path,
    writer_id: str,
    superseded_ids: set[str],
    destination_root: Path,
) -> dict:
    """Create a new index by replacing explicit sample IDs with validated samples."""
    if not superseded_ids:
        raise ValueError("at least one superseded sample id is required")
    original = list(iter_index(index_path))
    replacements = list(iter_index(replacement_index_path))
    if any(sample.writer_id != writer_id for sample in [*original, *replacements]):
        raise ValueError("writer mismatch in replacement indexes")
    found = {sample.sample_id for sample in original} & superseded_ids
    missing = sorted(superseded_ids - found)
    if missing:
        raise ValueError(f"superseded sample ids not found: {', '.join(missing)}")
    removed = [sample for sample in original if sample.sample_id in superseded_ids]
    retained = [sample for sample in original if sample.sample_id not in superseded_ids]
    removed_characters = Counter(sample.character for sample in removed)
    replacement_characters = Counter(sample.character for sample in replacements)
    if removed_characters != replacement_characters:
        raise ValueError(
            "replacement characters do not match superseded characters: "
            f"removed={dict(removed_characters)}, replacements={dict(replacement_characters)}"
        )
    retained_ids = {sample.sample_id for sample in retained}
    replacement_ids = [sample.sample_id for sample in replacements]
    if len(replacement_ids) != len(set(replacement_ids)):
        raise ValueError("replacement index contains duplicate sample ids")
    conflicting_ids = sorted(set(replacement_ids) & retained_ids)
    if conflicting_ids:
        raise ValueError(f"replacement sample ids conflict with retained samples: {conflicting_ids}")
    retained_hashes = {sample.source_sha256 for sample in retained}
    conflicting_hashes = sorted(
        sample.source_sha256 for sample in replacements if sample.source_sha256 in retained_hashes
    )
    if conflicting_hashes:
        raise ValueError("replacement payload already exists in retained samples")
    result_samples = sorted(
        [*retained, *replacements], key=lambda sample: (ord(sample.character), sample.sample_id)
    )
    writer_dir = Path(destination_root).resolve() / writer_id
    writer_dir.mkdir(parents=True, exist_ok=True)
    result_index = writer_dir / "index.jsonl"
    temporary = result_index.with_suffix(".jsonl.building")
    with temporary.open("w", encoding="utf-8") as stream:
        for sample in result_samples:
            stream.write(json.dumps(asdict(sample), ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
    temporary.replace(result_index)
    report = {
        "schema_version": "sample_index_replacement_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "writer_id": writer_id,
        "source_index": str(Path(index_path).resolve()),
        "replacement_index": str(Path(replacement_index_path).resolve()),
        "index": str(result_index),
        "index_sha256": sha256_file(result_index),
        "original_sample_count": len(original),
        "removed_sample_count": len(removed),
        "replacement_sample_count": len(replacements),
        "result_sample_count": len(result_samples),
        "unique_character_count": len({sample.character for sample in result_samples}),
        "replaced_characters": "".join(sorted(removed_characters, key=ord)),
        "superseded_sample_ids": sorted(superseded_ids),
        "replacement_sample_ids": sorted(replacement_ids),
        "source_indexes_modified": False,
    }
    (writer_dir / "replacement_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _raw_sample_from_dict(value: dict) -> RawSample:
    strokes = [
        RawStroke(
            stroke_index=int(stroke["stroke_index"]),
            points=[RawPoint(**point) for point in stroke["points"]],
        )
        for stroke in value["strokes"]
    ]
    return RawSample(**{**value, "strokes": strokes})


def iter_index(index_path: Path) -> Iterator[RawSample]:
    with Path(index_path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield _raw_sample_from_dict(json.loads(line))
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid index row {line_number}: {error}") from error
