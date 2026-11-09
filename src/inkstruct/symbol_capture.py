"""Independent symbol specimens: variable strokes, original points and em metrics."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import string
import tempfile
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .punctuation import CHINESE_PUNCTUATION, SHARED_PUNCTUATION, capture_character
from .symbol_catalog import SYMBOL_GROUPS, symbol_group

CATALOG = {
    "数字": string.digits,
    "英文大写": string.ascii_uppercase,
    "英文小写": string.ascii_lowercase,
    "希腊字母": "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψω",
    "希腊变体": "ϐϑϕϖϱϵϰς",
    "数学与标点": "+−-×÷=≠≈≡±∓<>≤≥∞∑∏∫∮√∂∇∈∉∋⊂⊃⊆⊇∪∩∅∀∃¬∧∨⇒⇔→←↔↑↓∝∠⊥∥·⋅/!%‰°′″()[]{}|.,:;?",
    "中文专用标点": CHINESE_PUNCTUATION,
    "中英共用标点": ''.join(SHARED_PUNCTUATION),
    "英文引号": '\"\'',
}
CHARACTERS = "".join(dict.fromkeys("".join(CATALOG.values()) +
                                   "".join(chars for _, chars, _ in SYMBOL_GROUPS.values())))
CAPTURE_CHARACTERS = ''.join(dict.fromkeys(capture_character(c) for c in CHARACTERS))
FRAME = {
    "version": "symbol_guides_v1",
    "canvas_width": 560,
    "canvas_height": 320,
    "origin_x_px": 140.0,
    "baseline_y_px": 250.0,
    "em_px": 200.0,
    "cap_height_em": 0.70,
    "x_height_em": 0.50,
    "math_axis_em": 0.25,
    "descender_em": 0.20,
}


def scaled_frame(percent: int = 100) -> dict:
    """Scale the capture frame while retaining raw logical-pixel coordinates."""
    if percent not in range(50, 151, 5):
        raise ValueError("画布大小需为 50%–150%，每档 5%")
    frame = dict(FRAME)
    for key in ("canvas_width", "canvas_height", "origin_x_px", "baseline_y_px", "em_px"):
        frame[key] = FRAME[key] * percent / 100
    frame["canvas_width"] = round(frame["canvas_width"])
    frame["canvas_height"] = round(frame["canvas_height"])
    return frame


def symbol_info(character: str) -> dict:
    key = symbol_group(character)
    if key == "other":
        raise ValueError(f"不支持的单字符：{character!r}；请选择字母与符号字表中的字符")
    group = SYMBOL_GROUPS[key][0] if key in SYMBOL_GROUPS else "英文字母"
    math_class = "ordinary"
    if character in "+−-×÷±∓∪∩∧∨·⋅":
        math_class = "binary"
    elif character in "=≠≈≡<>≤≥∈∉∋⊂⊃⊆⊇⇒⇔→←↔↑↓∝⊥∥":
        math_class = "relation"
    elif character in "∑∏∫∮":
        math_class = "large_operator"
    elif character == "√":
        math_class = "radical"
    elif character in "([{（［｛【《〈「『“‘":
        math_class = "open"
    elif character in ")]}）］｝】》〉」』”’":
        math_class = "close"
    elif character in ".．,:;，。；：、":
        math_class = "punctuation"
    elif character == "|":
        math_class = "contextual_delimiter"
    return {
        "character": character,
        "codepoint": f"U+{ord(character):04X}",
        "unicode_name": unicodedata.name(character),
        "category": group,
        "math_class_hint": math_class,
        "math_class_is_contextual": True,
    }


def parse_symbol_file(path: Path, default_repeats: int = 5) -> list[tuple[str, int, int]]:
    if not 1 <= default_repeats <= 100:
        raise ValueError("每字份数需在 1—100 之间")
    result, seen = [], {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        if path.suffix.lower() == ".txt":
            entries = (
                (c, default_repeats, i) for i, line in enumerate(f) for c in line if not c.isspace()
            )
        elif path.suffix.lower() == ".csv":
            reader = csv.DictReader(f)
            if "character" not in (reader.fieldnames or []):
                raise ValueError("CSV 必须包含 character 列")
            entries = (
                (
                    r.get("character", "").strip(),
                    int(r.get("repeats", "").strip() or default_repeats),
                    i,
                )
                for i, r in enumerate(reader)
            )
        else:
            raise ValueError("请选择 TXT 或 CSV")
        for c, repeats, i in entries:
            symbol_info(c)
            c = capture_character(c)
            if not 1 <= repeats <= 100:
                raise ValueError("每字份数需在 1—100 之间")
            if c not in seen:
                result.append((c, repeats, i))
                seen[c] = repeats
            elif seen[c] != repeats:
                raise ValueError(f"共用采集字符 {c!r} 的份数不一致，请统一后导入")
    if not result:
        raise ValueError("字表为空")
    return result


def write_catalog(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["character", "repeats", "category", "codepoint", "unicode_name"])
        for c in CAPTURE_CHARACTERS:
            info = symbol_info(c)
            w.writerow([c, 5, info["category"], info["codepoint"], info["unicode_name"]])


def build_specimen(
    *,
    writer_id,
    task,
    item,
    trajectory,
    canvas_width,
    canvas_height,
    device_pixel_ratio,
    variant_note="",
    sample_id=None,
) -> dict:
    from .symbol_tasks import item_letter_style
    info = symbol_info(item.character)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", writer_id):
        raise ValueError("书写者 ID 需以字母或数字开头，仅含字母、数字、点、横线或下划线")
    if task.writer_id != writer_id or item not in task.items:
        raise ValueError("样本与任务书写者或任务项目不一致")
    if not all(math.isfinite(v) and v > 0 for v in (canvas_width, canvas_height)):
        raise ValueError("无效的画布尺寸")
    percent = round(canvas_width / FRAME["canvas_width"] * 100)
    guides = scaled_frame(percent)
    if (canvas_width, canvas_height) != (guides["canvas_width"], guides["canvas_height"]):
        raise ValueError("画布尺寸与参考线不一致，不能保存错误度量")
    if not math.isfinite(device_pixel_ratio) or device_pixel_ratio <= 0:
        raise ValueError("无效的显示缩放比例")
    trajectory.validate(canvas_width, canvas_height)
    sid = str(uuid.UUID(sample_id)) if sample_id else str(uuid.uuid4())
    points = list(trajectory.iter_points())
    xs = [(p.x - guides["origin_x_px"]) / guides["em_px"] for p in points]
    ys = [(guides["baseline_y_px"] - p.y) / guides["em_px"] for p in points]
    bounds = [min(xs), min(ys), max(xs), max(ys)]
    advance = max(0.12, max(xs) + 0.08)
    return {
        "schema_version": "inkstruct_symbol_sample_v1",
        "sample_id": sid,
        "writer_id": writer_id,
        **info,
        "task": {
            "task_id": task.task_id,
            "item_id": item.item_id,
            "source": task.source,
            "source_index": item.source_index,
            "repeat_index": item.repeat_index,
            "repeat_total": item.repeat_total,
        },
        "capture": {
            "created_at": datetime.now(UTC).isoformat(),
            "input_type": "tablet",
            "canvas_width": canvas_width,
            "canvas_height": canvas_height,
            "device_pixel_ratio": device_pixel_ratio,
            "canvas_scale": percent / 100,
            "coordinate_space": "logical_px",
            "duration_ms": trajectory.duration_ms,
        },
        "strokes": [s.to_dict(i) for i, s in enumerate(trajectory.strokes)],
        "stats": {"stroke_count": len(trajectory.strokes), "point_count": len(points)},
        "guides": guides,
        "metrics": {
            "coordinate_space": "em",
            "origin": "guide_origin_at_baseline",
            "x_direction": "right",
            "y_direction": "up",
            "baseline_em": 0.0,
            "ink_bounds_em": bounds,
            "ascent_em": max(0, max(ys)),
            "descent_em": max(0, -min(ys)),
            "left_side_bearing_em": min(xs),
            "advance_em": advance,
            "right_side_bearing_em": advance - max(xs),
            "advance_source": "ink_right_plus_margin_initial_estimate",
            "calibration_status": "guide_based_unreviewed",
            "math_axis_em": FRAME["math_axis_em"],
        },
        "variant": {
            "letter_style": item_letter_style(task, item),
            "note": variant_note.strip(),
            "selection_group": [writer_id, item.character],
            "review_status": "unreviewed",
            "stroke_count_policy": "variable",
        },
    }


class SymbolStorage:
    """One atomic JSON per specimen; task state can be reconciled after interruption."""

    def __init__(self, root: Path, note_provider=lambda: ""):
        self.root = root
        self.note_provider = note_provider

    def save_single(self, **kwargs):
        payload = build_specimen(**kwargs, variant_note=self.note_provider())
        path = (
            self.root
            / "samples"
            / payload["writer_id"]
            / payload["codepoint"]
            / f"{payload['sample_id']}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(path)
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            # Same-directory rename also works on common Windows removable filesystems.
            # IDs are UUIDs; explicit duplicate IDs were rejected before staging.
            from handwriting_collector.paths import native_path
            os.replace(native_path(temporary), native_path(path))
        finally:
            Path(temporary).unlink(missing_ok=True)
        return payload["sample_id"], path

    def reconcile_task(self, task):
        from .symbol_revisions import recover_revisions
        recover_revisions(self.root, task)
        pending = {i.item_id: i for i in task.items if i.status != "completed"}
        recovered = 0
        for path in (self.root / "samples").glob("*/*/*.json"):
            try:
                p = json.loads(path.read_text(encoding="utf-8"))
                t = p["task"]
                item = pending.get(t["item_id"])
                if (
                    p["schema_version"] == "inkstruct_symbol_sample_v1"
                    and t["task_id"] == task.task_id
                    and p["writer_id"] == task.writer_id
                    and item is not None
                    and p["character"] == item.character
                ):
                    item.status, item.sample_id = "completed", p["sample_id"]
                    pending.pop(item.item_id)
                    recovered += 1
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return recovered
