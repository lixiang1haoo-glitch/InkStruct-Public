"""Convert an InkStruct 1.0 font to the common inkfont v1 ZIP format."""

from base64 import b64encode
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


MIB = 1024**2
MAX_LEGACY_MEMBER = 32 * MIB
MAX_MEMBER = 384 * MIB
MAX_ARCHIVE = 256 * MIB
MAX_UNPACKED = 1024 * MIB
MAX_FILES = 60_000
MAX_CANDIDATES = 30_000
MAX_GLYPH_POINTS = 100_000
MAX_POINTS = 30_000_000
GRID = Decimal("0.001")
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
SHA256 = re.compile(r"[0-9a-f]{64}")
LEGACY_FEATURES = ["centerline-em-v1", "candidate-pools-v1", "latin-style-pools-v1"]
EXTENSIONS = {
    "pressure": "extensions/pressure-v1.json",
    "timing": "extensions/timing-v1.json",
    "math": "extensions/math-metrics-v1.json",
    "provenance": "extensions/provenance-v1.json",
}
ORIGINS = {"measured", "inherited", "inherited_retimed", "synthesized", "absent", "unknown"}
PEN_STATES = {"down", "up", "end"}
SOURCE_KINDS = {"recorded", "generated", "reused", "composed", "unknown"}
STYLES = {"upright", "italic", "unspecified"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encode(value, *, sort_keys=False):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False, sort_keys=sort_keys).encode("utf-8")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"重复 JSON 字段：{key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"非有限 JSON 数值：{value}")


def decode(raw, *, exact=False):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=invalid_constant, parse_float=Decimal if exact else float)


def digest(raw):
    return sha256(raw).hexdigest()


def number(value):
    require(type(value) in (int, float, Decimal), "需要数值")
    v = value if isinstance(value, Decimal) else Decimal(str(value))
    require(v.is_finite(), "需要有限数值")
    return v


def json_number(value):
    return 0 if value == 0 else float(value)


def valid_character(character):
    return (isinstance(character, str) and len(character) == 1 and
            not character.isspace() and unicodedata.category(character) not in {"Cc", "Cs"})


def validate_font_identity(manifest):
    font_id, name = manifest["font_id"], manifest["name"]
    require(isinstance(font_id, str) and str(UUID(font_id)) == font_id, "字体 ID 不是小写 UUID")
    require(isinstance(name, str) and 0 < len(name.strip()) and len(name) <= 128 and
            not any(0xD800 <= ord(c) <= 0xDFFF for c in name), "字体名无效或超过 128 字")


class CheckedArchive:
    def __init__(self, archive, *, legacy=False):
        self.archive = archive
        infos = archive.infolist()
        require(len(infos) <= (100_000 if legacy else MAX_FILES), "ZIP 文件成员过多")
        require(sum(i.file_size for i in infos) <= (4 * MAX_UNPACKED if legacy else MAX_UNPACKED),
                "ZIP 解压大小超限")
        member_limit = MAX_LEGACY_MEMBER if legacy else MAX_MEMBER
        names = set()
        for info in infos:
            name = info.filename
            require(not info.is_dir() and name and name == info.orig_filename and
                    not any(c in name for c in ("\\", ":")) and
                    not any(p in ("", ".", "..") for p in name.split("/")) and
                    not any(ord(c) < 32 or ord(c) == 127 for c in name),
                    f"不安全的 ZIP 路径：{name!r}")
            mode = (info.external_attr >> 16) & 0o170000
            require(mode in (0, 0o100000) and not info.flag_bits & 1,
                    f"不是普通未加密文件：{name}")
            require(info.file_size <= member_limit, f"成员解压大小超限（{member_limit // MIB} MiB）：{name}")
            require(info.compress_type in (ZIP_STORED, ZIP_DEFLATED), f"不支持的压缩方式：{name}")
            key = name.casefold()
            require(key not in names, f"重复 ZIP 成员：{name}")
            names.add(key)
        self.manifest = decode(archive.read("manifest.json"))
        require(isinstance(self.manifest, dict) and isinstance(self.manifest.get("members"), dict),
                "无效的包清单或成员表")
        self.members = self.manifest["members"]
        require(set(archive.namelist()) == {"manifest.json", *self.members} and
                "manifest.json" not in self.members, "ZIP 路径与清单不符")
        for path, entry in self.members.items():
            require(isinstance(entry, dict) and type(entry.get("bytes")) is int and
                    entry["bytes"] == archive.getinfo(path).file_size,
                    f"清单尺寸不符：{path}")
            require(isinstance(entry["sha256"], str) and SHA256.fullmatch(entry["sha256"]),
                    f"清单摘要格式有误：{path}")

    def read(self, path):
        require(path in self.members, f"清单未声明成员：{path}")
        raw = self.archive.read(path)
        require(len(raw) == self.members[path]["bytes"] and
                digest(raw) == self.members[path]["sha256"], f"成员字节校验失败：{path}")
        return raw

    def json(self, path, *, exact=False):
        return decode(self.read(path), exact=exact)


class ExtensionWriter:
    """Spool per-candidate records so a large optional channel needn't fit in memory."""

    def __init__(self, file):
        self.file = file
        self.count = 0
        self.file.write(b'{"schema_version":1,"entries":{')

    def append(self, candidate, entry):
        if self.count:
            self.file.write(b",")
        self.file.write(encode(candidate) + b":" + encode(entry))
        self.count += 1

    def close(self):
        self.file.write(b"}}")
        self.file.close()


def point_shape(arrays, shape):
    return (isinstance(arrays, list) and len(arrays) == len(shape) and
            all(isinstance(row, list) and len(row) == n
                for row, n in zip(arrays, shape, strict=True)))


def origins(values, shape):
    require(isinstance(values, list) and len(values) == len(shape) and
            all(value in ORIGINS for value in values), "动态来源不匹配笔段")


def verify_extension(kind, data, checked, shapes):
    require(isinstance(data, dict) and type(data.get("schema_version")) is int and data["schema_version"] == 1
            and isinstance(data.get("entries"), dict),
            "扩展版本无效")
    for candidate, entry in data["entries"].items():
        require(candidate in shapes, "扩展引用未知候选")
        shape = shapes[candidate]
        path = f"glyphs/{candidate}.json"
        if "source_trajectory_ref" in entry:
            path = entry["source_trajectory_ref"]
            require(kind in ("pressure", "timing") and
                    re.fullmatch(r"extensions/snapshots/[a-z0-9][a-z0-9_-]{0,63}\.json", path),
                    "原轨迹快照引用无效")
            shape = trajectory_shape(checked.json(path))
        require(entry["trajectory_digest"] == checked.members[path]["sha256"],
                "扩展和轨迹摘要不匹配")
        if kind == "pressure":
            require(point_shape(entry["values"], shape), "压力数组不匹配轨迹")
            origins(entry["origin"], shape)
            require(all(v is None or 0 <= number(v) <= 1 for s in entry["values"] for v in s),
                    "压力超出 0–1")
        elif kind == "timing":
            require(point_shape(entry["t_ms"], shape), "时间数组不匹配轨迹")
            origins(entry["time_origin"], shape)
            last = None
            for stroke in entry["t_ms"]:
                for value in stroke:
                    if value is None:
                        continue
                    current = number(value)
                    require(current == 0 if last is None else current >= last, "时间零点或顺序错误")
                    last = current
            if "pen_state" in entry:
                require(point_shape(entry["pen_state"], shape) and
                        all(v is None or v in PEN_STATES for s in entry["pen_state"] for v in s),
                        "笔状态数组无效")
                origins(entry["pen_state_origin"], shape)
        elif kind == "math":
            number(entry["math_axis_em"])
        else:
            require(entry["source_kind"] in SOURCE_KINDS, "来源类型无效")
            if "letter_style" in entry:
                require(entry["letter_style"] in STYLES, "字形风格无效")


def trajectory_shape(data):
    strokes = data["strokes"]
    require(set(data) == {"strokes"} and isinstance(strokes, list) and strokes, "无有效笔段")
    shape = []
    for stroke in strokes:
        require(isinstance(stroke, list) and stroke, "空笔段")
        shape.append(len(stroke))
        for pair in stroke:
            require(isinstance(pair, list) and len(pair) == 2 and
                    all(type(p) in (int, float) and math.isfinite(p) and abs(p) <= 10 for p in pair),
                    "无效 v1 坐标")
    require(sum(shape) <= MAX_GLYPH_POINTS, "单候选点数超限")
    return shape


def core_hash(manifest, paths):
    lines = ["inkfont/1\n", manifest["font_id"] + "\n"]
    for path in sorted(paths):
        lines.append(f'{path}\t{manifest["members"][path]["sha256"]}\n')
    return digest("".join(lines).encode("ascii"))


def indexed_candidates(index, members):
    require(isinstance(index, dict) and index, "字形索引为空或无效")
    seen = set()
    for char, candidates in index.items():
        require(valid_character(char) and isinstance(candidates, list) and candidates, "字符索引项无效")
        for cid in candidates:
            require(isinstance(cid, str) and ID.fullmatch(cid) and cid not in seen, f"重复或无效候选 ID：{cid}")
            path = f"glyphs/{cid}.json"
            require(len(seen) < MAX_CANDIDATES and path in members, "候选数量超限或轨迹缺失")
            seen.add(cid)
            yield char, cid, path


def verify(path):
    size = path.stat().st_size
    require(size <= MAX_ARCHIVE, "v1 ZIP 压缩包超过 256 MiB")
    with ZipFile(path) as archive:
        checked = CheckedArchive(archive)
        m = checked.manifest
        require(m.get("format") == "inkfont" and type(m.get("format_version")) is int and
                m["format_version"] == 1, "需要统一 inkfont v1")
        validate_font_identity(m)
        index = checked.json("index.json")
        shapes = {}
        count = 0
        core_paths = {"index.json"}
        for _, cid, member in indexed_candidates(index, checked.members):
            shape = trajectory_shape(checked.json(member))
            count += sum(shape)
            require(count <= MAX_POINTS, "v1 总点数超限")
            shapes[cid] = shape
            core_paths.add(member)
        ext_sizes = {}
        known = {path: kind for kind, path in EXTENSIONS.items()}
        for member in checked.members.keys() - core_paths:
            if member.startswith("extensions/"):
                ext_sizes[member] = checked.members[member]["bytes"]
                if member in known:
                    verify_extension(known[member], checked.json(member), checked, shapes)
                    continue
            else:
                require(member.startswith("previews/") and
                        member.removeprefix("previews/").removesuffix(".svg") in shapes and
                        member.endswith(".svg"), f"未知核心成员或悬空预览：{member}")
            checked.read(member)
        return {"characters": len(index), "candidates": len(shapes), "points": count,
                "compressed_bytes": size,
                "unpacked_bytes": sum(i.file_size for i in archive.infolist()),
                "extension_unpacked_bytes": ext_sizes,
                "core_sha256": core_hash(m, core_paths)}


def map_points(trajectory, baseline, full_precision, stats):
    require(trajectory.get("coordinate_space") == "em-y-down-baseline-0.88" and
            trajectory.get("schema_version") == "inkfont_trajectory_v1",
            "不支持的旧轨迹坐标或版本")
    strokes = trajectory["strokes"]
    require(isinstance(strokes, list) and strokes, "旧轨迹为空")
    result = []
    count = 0
    for order, stroke in enumerate(strokes, 1):
        require(stroke["order"] == order and stroke["stroke_ref"] == f"stroke-{order}",
                "旧笔序或笔段引用无效")
        pts = stroke["points"]
        require(isinstance(pts, list) and pts, "旧字包含空笔段")
        count += len(pts)
        require(count <= MAX_GLYPH_POINTS and stats["points"] + count <= MAX_POINTS, "v1 点数超限")
        transformed = []
        previous = None
        for point in pts:
            x, y = number(point["x"]), number(point["y"]) - baseline
            require(abs(x) <= 10 and abs(y) <= 10, "换算后的坐标超出 v1 ±10 em")
            new = (x, y) if full_precision else (
                x.quantize(GRID, rounding=ROUND_HALF_UP), y.quantize(GRID, rounding=ROUND_HALF_UP))
            pair = [json_number(v) for v in new]
            if not full_precision:
                distance = math.hypot(float(new[0] - x), float(new[1] - y))
                if distance > stats["max_quantization_error_em"]:
                    stats["max_quantization_error_em"] = distance
            if previous is not None and pair == previous:
                stats["coincident_adjacent_pairs"] += 1
            previous = pair
            transformed.append(pair)
        result.append(transformed)
    stats["points"] += count
    stats["strokes"] += len(strokes)
    return {"strokes": result}


def dynamics(strokes, kind):
    def source(k):
        return [s["dynamic_origin"][k] for s in strokes]

    if kind == "pressure":
        values = [[p.get("pressure") for p in s["points"]] for s in strokes]
        if not any(v is not None for row in values for v in row):
            return None
        require(all(v is None or 0 <= number(v) <= 1 for row in values for v in row),
                "旧压力值超出范围")
        return {"values": [[None if v is None else json_number(number(v)) for v in row]
                           for row in values], "origin": source("pressure")}
    times = [[p.get("t_ms") for p in s["points"]] for s in strokes]
    states = [[p.get("pen_state") for p in s["points"]] for s in strokes]
    first = next((number(t) for row in times for t in row if t is not None), None)
    has_states = any(v is not None for row in states for v in row)
    if first is None and not has_states:
        return None
    data = {"t_ms": [[None if t is None else json_number(number(t) - first) for t in row]
                     for row in times], "time_origin": source("time")}
    if has_states:
        data.update(pen_state=states, pen_state_origin=source("pen_state"))
    return data


def math_axis(summary):
    if summary.get("source_kind") == "composed":
        return summary.get("symbol_construction", {}).get("math_axis_em")
    return summary.get("capture_guides", {}).get("math_axis_em")


def provenance(record, summary):
    kind = summary.get("source_kind")
    if kind == "reuse":
        kind = "reused"
    result = {"source_kind": kind if kind in SOURCE_KINDS else "unknown"}
    if record.get("letter_style") in STYLES:
        result["letter_style"] = record["letter_style"]
    for key in ("generator_version", "source_candidate_id", "review_status"):
        if key in summary:
            result[key] = summary[key]
    if "generator_version" not in result and summary.get("generation_version") is not None:
        result["generator_version"] = summary["generation_version"]
    return result


def convert(src, dst, *, full_precision=False, extensions=(), legacy_context=False):
    require(src.resolve() != dst.resolve(), "输出必须另存为新文件")
    if dst.exists():
        raise FileExistsError(f"目标已存在：{dst}")
    before = src.stat()
    stats = {"source_compressed_bytes": before.st_size, "points": 0, "strokes": 0,
             "coincident_adjacent_pairs": 0, "max_quantization_error_em": 0.0}
    skipped, available, styles_by_character = Counter(), Counter(), {}
    with ZipFile(src) as old, tempfile.TemporaryDirectory(dir=dst.absolute().parent) as tmp:
        temp = Path(tmp)
        checked = CheckedArchive(old, legacy=True)
        m = checked.manifest
        require(m.get("format") == "inkstruct_font" and m.get("format_version") == "1.0" and
                m.get("required_features") == LEGACY_FEATURES, "需要 InkStruct 1.0 字体包")
        actual_manifest_hash = digest(encode(
            {k: v for k, v in m.items() if k != "content_hash"}, sort_keys=True))
        require(actual_manifest_hash == m["content_hash"], "旧清单完整性校验失败")
        validate_font_identity(m)
        old_index = checked.json("index.json")
        require(old_index.get("selection_policy") == "style-priority-uniform-v1",
                "未知旧包候选选择策略")
        records = old_index["candidates"]
        measurements, sources = checked.json("metrics.json", exact=True), checked.json("provenance.json")
        stats["source_unpacked_bytes"] = sum(i.file_size for i in old.infolist())
        stats["source_candidates"] = len(records)
        stats["source_has_license_member"] = "license.txt" in checked.members
        stats["source_has_development_members"] = any(p.startswith("development/") for p in checked.members)
        out_members, index, ids = {}, {}, set()
        staged = temp / "new.inkfont"
        paths = {kind: temp / f"{kind}.json" for kind in extensions}
        writers = {kind: ExtensionWriter(p.open("wb")) for kind, p in paths.items()}
        try:
            with ZipFile(staged, "w", ZIP_DEFLATED, compresslevel=6) as out:
                for record in records:
                    cid, char = record["candidate_id"], record["character"]
                    require(isinstance(cid, str) and ID.fullmatch(cid) and cid not in ids,
                            f"重复或无效的旧候选 ID：{cid}")
                    ids.add(cid)
                    require(type(record["enabled"]) is bool, "旧候选启用字段无效")
                    summary = sources[cid]
                    if not record["enabled"]:
                        skipped["disabled"] += 1
                        continue
                    if summary["review_status"] in {"rejected", "needs_review"}:
                        skipped[summary["review_status"]] += 1
                        continue
                    if not valid_character(char):
                        skipped["whitespace_or_control"] += 1
                        continue
                    require(len(out_members) < MAX_CANDIDATES, "v1 候选过多")
                    baseline = number(measurements[cid]["baseline"])
                    glyph = checked.json(record["file"], exact=True)
                    require(glyph["character"] == char, "旧索引与轨迹字符不符")
                    try:
                        xy = encode(map_points(glyph, baseline, full_precision, stats))
                    except ValueError as error:
                        raise ValueError(f"U+{ord(char):04X} {cid}：{error}") from error
                    track = f"glyphs/{cid}.json"
                    track_hash = digest(xy)
                    out.writestr(track, xy)
                    out_members[track] = {"bytes": len(xy), "sha256": track_hash}
                    index.setdefault(char, []).append(cid)
                    styles_by_character.setdefault(char, set()).add(record.get("letter_style"))
                    strokes = glyph["strokes"]
                    axis = math_axis(summary)
                    has_pressure = any("pressure" in p for s in strokes for p in s["points"])
                    has_timing = any("t_ms" in p or "pen_state" in p for s in strokes for p in s["points"])
                    available["pressure"] += has_pressure
                    available["timing"] += has_timing
                    available["math"] += axis is not None
                    available["provenance"] += 1
                    for kind, writer in writers.items():
                        if kind in ("pressure", "timing"):
                            entry = dynamics(strokes, kind)
                        elif kind == "math":
                            # Legacy axes measure upward from the baseline. V1 y grows downward.
                            entry = {"math_axis_em": json_number(-number(axis))} if axis is not None else None
                        else:
                            entry = provenance(record, summary)
                        if entry is not None:
                            writer.append(cid, {"trajectory_digest": track_hash, **entry})
                require(index, "没有可转换的候选")
                require(set(measurements) == ids and set(sources) == ids, "旧候选与度量或来源不一致")
                for writer in writers.values():
                    writer.close()
                ext_sizes = {EXTENSIONS[k]: p.stat().st_size for k, p in paths.items() if writers[k].count}
                oversized = {p: n for p, n in ext_sizes.items() if n > MAX_MEMBER}
                require(not oversized, f"扩展超过 v1 单成员 {MAX_MEMBER // MIB} MiB，输出未发布：" +
                        json.dumps(ext_sizes, ensure_ascii=False))
                for kind, p in paths.items():
                    if writers[kind].count:
                        raw = p.read_bytes()
                        name = EXTENSIONS[kind]
                        out.writestr(name, raw)
                        out_members[name] = {"bytes": len(raw), "sha256": digest(raw)}
                if legacy_context:
                    reference = {key: m[key] for key in ("font_id", "release_id", "package_id", "core_hash",
                                                         "content_hash", "writer_alias", "font_version", "package_kind")}
                    context = dict(schema_version=1, entries={}, original_release=reference)
                    if "license.txt" in checked.members:
                        context["license_base64"] = b64encode(checked.read("license.txt")).decode("ascii")
                    raw = encode(context)
                    name = "extensions/inkstruct-release-v1.json"
                    out.writestr(name, raw)
                    out_members[name] = {"bytes": len(raw), "sha256": digest(raw)}
                # The legacy index was sorted by priority within each style.
                for candidates in index.values():
                    candidates.sort()
                raw_index = encode(index)
                out.writestr("index.json", raw_index)
                out_members["index.json"] = {"bytes": len(raw_index), "sha256": digest(raw_index)}
                manifest = {"format": "inkfont", "format_version": 1, "font_id": m["font_id"],
                            "name": m["name"], "members": out_members}
                out.writestr("manifest.json", encode(manifest))
        finally:
            for writer in writers.values():
                if not writer.file.closed:
                    writer.file.close()

        checked_output = verify(staged)
        require(checked_output["points"] == stats["points"], "转换后点数有误")
        after = src.stat()
        require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                "源字体在转换期间发生变化")
        os.link(staged, dst)
    stats.update(checked_output)
    stats["skipped"] = dict(skipped)
    stats["source_extension_coverage"] = dict(available)
    stats["characters_with_mixed_letter_styles"] = sum(
        len(styles) > 1 for styles in styles_by_character.values())
    stats["coordinate_mode"] = "full_precision" if full_precision else "grid_0.001_em"
    stats["max_quantization_error_at_20mm"] = stats["max_quantization_error_em"] * 20
    stats["omitted_extensions"] = [name for name in EXTENSIONS if name not in extensions and available[name]]
    stats["not_carried"] = ["固定进位、旧候选优先级、专用排版或校正元数据",
                            "旧包中的预览与开发记录保存在原版"]
    return stats
