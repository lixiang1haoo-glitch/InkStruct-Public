"""Translate validated grouped runs to InkStruct's physical-stroke font format."""

import re

from .assets.glyph_provider import GlyphMetrics
from .fonts.core import validate_summary, validate_trajectory
from .generation_workflow import read
from .samples import sha256_file
from .v63 import GLYPH, RUN


SHA256 = re.compile(r"[0-9a-f]{64}")


def validate_grouped_glyph(glyph, writer, character):
    if (glyph.get("schema_version") != GLYPH or glyph.get("writer_id") != writer
            or glyph.get("character") != character or not isinstance(character, str) or len(character) != 1):
        raise ValueError("连笔字形格式、作者或字符不符")
    slots = glyph["standard_slots"]
    segments = glyph["segments"]
    if (not isinstance(slots, list) or not slots or not isinstance(segments, list) or not segments
            or any(not isinstance(s, str) or not s for s in slots) or len(set(slots)) != len(slots)):
        raise ValueError("标准笔位或物理笔段无效")
    if [slot for s in segments for slot in s["standard_slots"]] != slots:
        raise ValueError("物理笔段必须按序覆盖全部标准笔位，且每笔只能覆盖一次")
    for i, segment in enumerate(segments):
        kind = segment.get("kind")
        width = len(segment["standard_slots"])
        if kind not in {"author_group", "author_split", "reference"} or width not in (1, 2):
            raise ValueError("笔段映射无效")
        if width > 1 and kind != "author_group":
            raise ValueError("多笔位必须有连写来源")
        if kind != "reference" and not SHA256.fullmatch(segment.get("source_sha256", "")):
            raise ValueError("缺少可追踪的笔段来源")
        points = segment["points"]
        expected = "end" if i == len(segments)-1 else "up"
        if len(points) < 2 or points[-1].get("pen_state") != expected or any(
            p.get("pen_state") != "down" for p in points[:-1]
        ):
            raise ValueError("物理抬笔边界无效")
    validate_trajectory(trajectory_for(glyph))


def trajectory_for(glyph):
    strokes = []
    for i, segment in enumerate(glyph["segments"], 1):
        author = segment["kind"] != "reference"
        strokes.append({"order": i, "stroke_ref": f"stroke-{i}", "points": segment["points"],
                        "dynamic_origin": {"pressure": "inherited" if author else "synthesized",
                                           "time": "inherited_retimed" if author else "synthesized",
                                           "pen_state": "synthesized"}})
    return {"schema_version": "inkfont_trajectory_v1", "character": glyph["character"],
            "coordinate_space": "em-y-down-baseline-0.88", "strokes": strokes}


def grouped_records(root, writer):
    manifest = read(root / "v63-run.json")
    if manifest.get("schema_version") != RUN or manifest.get("writer") != writer:
        raise ValueError("连笔生成批次协议或作者不符")
    for char, spec in manifest["files"].items():
        if len(char) != 1 or spec["name"] != f"U+{ord(char):04X}.json":
            raise ValueError("连笔生成批次文件名无效")
        path = (root / spec["name"]).resolve()
        if not path.is_relative_to(root.resolve()) or sha256_file(path) != spec["sha256"]:
            raise ValueError("连笔生成字形摘要不符")
        glyph = read(path)
        validate_grouped_glyph(glyph, writer, char)
        yield glyph, None, {"legacy_source_hash": spec["sha256"]}, manifest


def make_grouped(glyph):
    validate_grouped_glyph(glyph, glyph["writer_id"], glyph["character"])
    trajectory = trajectory_for(glyph)
    segments = glyph["segments"]
    author = [i for i, s in enumerate(segments, 1) if s["kind"] != "reference"]
    references = [i for i, s in enumerate(segments, 1) if s["kind"] == "reference"]
    status = "reference_only" if not author else "partial" if references else "complete"
    summary = {
        "source_kind": "generated", "task_status": "completed", "author_source_status": status,
        "protocol_status": "valid", "review_status": "unreviewed", "author_strokes": author,
        "reference_strokes": references, "unknown_strokes": [],
        "gaps": [{"order": i, "reason": "v6.2 参考替代"} for i in references],
        "generator": "v6.3 exp", "generation_method": "v6.3 exp", "generation_mode": glyph["method"],
        "same_character_sources_excluded": glyph["method"] != "same_character",
        "warnings": ["含参考替代笔画"] if references else [],
        "v63_standard_slots": glyph["standard_slots"],
        "v63_physical_sources": [{k: v for k, v in s.items() if k != "points"} for s in segments],
    }
    validate_summary(summary, len(segments))
    from dataclasses import asdict
    return trajectory, asdict(GlyphMetrics()), summary
