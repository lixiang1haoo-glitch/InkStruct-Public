from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from .alignment import align_sample
from .samples import iter_index
from .structures import StructureRepository


def audit_samples_for_rerecord(
    index_path: Path,
    structures: StructureRepository,
    *,
    writer_id: str,
    output_csv: Path,
    confidence_threshold: float = 0.5,
) -> dict:
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence threshold must be inside [0, 1]")
    issues: dict[str, list[dict]] = defaultdict(list)
    checked = 0
    for sample in iter_index(index_path):
        if sample.writer_id != writer_id:
            raise ValueError(
                f"writer mismatch: expected {writer_id}, found {sample.writer_id}"
            )
        checked += 1
        try:
            graph = structures.get(sample.character)
            aligned = align_sample(sample, graph)
        except (KeyError, ValueError) as error:
            issues[sample.character].append(
                {
                    "sample_id": sample.sample_id,
                    "expected_strokes": "",
                    "observed_strokes": len(sample.strokes),
                    "alignment_confidence": "",
                    "issue": "structure_or_alignment_error",
                    "reason": str(error),
                }
            )
            continue
        expected = len(graph.strokes)
        observed = len(sample.strokes)
        reasons: list[str] = []
        issue_codes: list[str] = []
        if observed != expected:
            issue_codes.append("stroke_count_mismatch")
            reasons.append(f"笔画数不一致：采集 {observed} 笔，标准 {expected} 笔")
        if aligned.confidence < confidence_threshold:
            issue_codes.append("low_alignment_confidence")
            reasons.append(
                f"轨迹对齐置信度 {aligned.confidence:.3f} 低于 {confidence_threshold:.3f}"
            )
        if reasons:
            issues[sample.character].append(
                {
                    "sample_id": sample.sample_id,
                    "expected_strokes": expected,
                    "observed_strokes": observed,
                    "alignment_confidence": round(aligned.confidence, 6),
                    "issue": "+".join(issue_codes),
                    "reason": "；".join(reasons),
                }
            )
    rows: list[dict] = []
    for character in sorted(issues, key=ord):
        values = issues[character]
        rows.append(
            {
                "character": character,
                "repeats": len(values),
                "purpose": "quality_rerecord",
                "expected_strokes": values[0]["expected_strokes"],
                "observed_strokes": " ".join(
                    str(value["observed_strokes"]) for value in values
                ),
                "alignment_confidence": " ".join(
                    str(value["alignment_confidence"])
                    for value in values
                    if value["alignment_confidence"] != ""
                ),
                "issue": " ".join(dict.fromkeys(value["issue"] for value in values)),
                "reason": "；".join(value["reason"] for value in values),
                "source_sample_ids": " ".join(value["sample_id"] for value in values),
            }
        )
    output_csv = Path(output_csv).resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_csv.with_suffix(".csv.building")
    fieldnames = [
        "character",
        "repeats",
        "purpose",
        "expected_strokes",
        "observed_strokes",
        "alignment_confidence",
        "issue",
        "reason",
        "source_sample_ids",
    ]
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output_csv)
    report = {
        "schema_version": "sample_quality_audit_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "writer_id": writer_id,
        "index": str(Path(index_path).resolve()),
        "confidence_threshold": confidence_threshold,
        "checked_sample_count": checked,
        "rerecord_character_count": len(rows),
        "rerecord_sample_count": sum(int(row["repeats"]) for row in rows),
        "rerecord_characters": "".join(row["character"] for row in rows),
        "csv": str(output_csv),
        "rows": rows,
    }
    report_path = output_csv.with_suffix(".json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
