"""Data-only .inkfont core, independent of generator and Qt.

Source protocols remain strict. This protocol accepts finite em coordinates and
optional dynamics, preserving every point and each field's presence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import tempfile
import time
import uuid
import zipfile
import re
from pathlib import Path, PurePosixPath

from ..assets.glyph_provider import GlyphMetrics
from ..assets.symbol_provider import ResolvedGlyph

FORMAT = "inkstruct_font"
VERSION = "1.0"
PROVIDER = "inkfont-core-v1"
FEATURES = ["centerline-em-v1", "candidate-pools-v1", "latin-style-pools-v1"]
MAX_MEMBER = 32 * 1024**2
MAX_TOTAL = 4 * 1024**3
MAX_POINTS = 100_000


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def semantic_hash(value):
    """Versioned, typed hash: preserve integer/float and optional-field identity."""
    h = hashlib.sha256(b"inkfont-typed-v1\0")

    def visit(v):
        if v is None:
            h.update(b"n")
        elif type(v) is bool:
            h.update(b"t" if v else b"f")
        elif type(v) is int:
            raw = str(v).encode()
            h.update(b"i" + struct.pack(">I", len(raw)) + raw)
        elif type(v) is float:
            if not math.isfinite(v):
                raise ValueError("非有限数值")
            h.update(b"d" + struct.pack(">d", v))
        elif isinstance(v, str):
            raw = v.encode()
            h.update(b"s" + struct.pack(">I", len(raw)) + raw)
        elif isinstance(v, (list, tuple)):
            h.update(b"a" + struct.pack(">I", len(v)))
            for item in v:
                visit(item)
        elif isinstance(v, dict):
            h.update(b"o" + struct.pack(">I", len(v)))
            for key in sorted(v):
                visit(key)
                visit(v[key])
        else:
            raise ValueError("不支持的字体数据类型")

    visit(value)
    return h.hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("重复 JSON 字段")
            result[k] = v
        return result

    def constant(v):
        raise ValueError("非有限数值：" + v)

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("字体 JSON 损坏") from exc


def latin(char):
    return len(char) == 1 and ("A" <= char <= "Z" or "a" <= char <= "z")


def validate_trajectory(t):
    if t.get("schema_version") != "inkfont_trajectory_v1":
        raise ValueError("不支持的字体轨迹版本")
    char = t.get("character", "")
    if not isinstance(char, str) or len(char) != 1 or 0xD800 <= ord(char) <= 0xDFFF:
        raise ValueError("无效的字符")
    if t.get("coordinate_space") != "em-y-down-baseline-0.88":
        raise ValueError("无效的字体坐标协议")
    strokes = t.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        raise ValueError("空轨迹")
    previous = -1
    count = 0
    for i, s in enumerate(strokes):
        if s.get("order") != i + 1 or s.get("stroke_ref") != f"stroke-{i + 1}":
            raise ValueError("字形笔序不一致")
        points = s.get("points")
        if not isinstance(points, list) or not points:
            raise ValueError("空笔画")
        for p in points:
            count += 1
            if count > MAX_POINTS:
                raise ValueError("单字点数超过资源预算")
            if set(p) - {"x", "y", "pressure", "t_ms", "pen_state"}:
                raise ValueError("未知轨迹字段")
            for axis in ("x", "y"):
                v = p.get(axis)
                if type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10:
                    raise ValueError("无效坐标")
            for k in ("pressure", "t_ms"):
                if k in p and (type(p[k]) not in (int, float) or not math.isfinite(p[k])):
                    raise ValueError("无效动态字段")
            if "pressure" in p and not 0 <= p["pressure"] <= 1:
                raise ValueError("压力超出范围")
            if "t_ms" in p:
                if p["t_ms"] < previous or p["t_ms"] < 0:
                    raise ValueError("时间不单调")
                previous = p["t_ms"]
            if "pen_state" in p and p["pen_state"] not in ("down", "up", "end"):
                raise ValueError("无效笔状态")
        dynamic = s.get("dynamic_origin", {})
        if set(dynamic) != {"pressure", "time", "pen_state"} or any(
            v
            not in {
                "measured",
                "inherited",
                "inherited_retimed",
                "synthesized",
                "absent",
                "unknown",
            }
            for v in dynamic.values()
        ):
            raise ValueError("缺少动态来源状态")
    return count


def trajectory_hashes(t):
    xy = [[[p["x"], p["y"]] for p in s["points"]] for s in t["strokes"]]

    def channel(name, origin):
        return [
            {
                "origin": s["dynamic_origin"][origin],
                "values": [{"value": p[name]} if name in p else {} for p in s["points"]],
            }
            for s in t["strokes"]
        ]

    return {
        "geometry_hash": semantic_hash([t["coordinate_space"], xy]),
        "pressure_hash": semantic_hash(channel("pressure", "pressure")),
        "time_hash": semantic_hash(channel("t_ms", "time")),
        "trajectory_hash": semantic_hash(t),
    }


def validate_summary(summary, count):
    if 'writer_link' in summary or 'imported_from' in summary:
        from ..capture_management import valid_writer

        link = summary.get('writer_link')
        if 'writer_link' in summary and (not isinstance(link, dict)
                or set(link) != {'source_writer', 'target_writer', 'batch_sha256', 'samples_sha256'}
                or not all(valid_writer(link[k]) for k in ('source_writer', 'target_writer'))
                or link['source_writer'] == link['target_writer']
                or not all(isinstance(link[k], str) and re.fullmatch(r'[0-9a-f]{64}', link[k])
                           for k in ('batch_sha256', 'samples_sha256'))):
            raise ValueError('无效的书写者关联信息')
        origin = summary.get('imported_from')
        if 'imported_from' in summary and (not isinstance(origin, dict)
                or set(origin) != {'writer_id', 'sample_id', 'sha256'} or not valid_writer(origin['writer_id'])
                or not isinstance(origin['sample_id'], str) or not origin['sample_id']
                or not isinstance(origin['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', origin['sha256'])):
            raise ValueError('无效的样本导入来源')
    construction = summary.get('symbol_construction', {})
    if isinstance(construction, dict) and 'math_axis_em' in construction:
        axis = construction['math_axis_em']
        if (summary.get('source_kind') != 'composed'
                or type(axis) not in (int, float) or not math.isfinite(axis) or not 0 <= axis <= 2):
            raise ValueError('无效的合成字形数学轴信息')
    if "optical_layout_frame" in summary:
        frame = summary["optical_layout_frame"]
        if not isinstance(frame, dict) or set(frame) != {"bounds", "metrics"}:
            raise ValueError("无效的校正排版框")
        bounds = frame["bounds"]
        if (not isinstance(bounds, list) or len(bounds) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10 for v in bounds)
                or bounds[0] > bounds[2] or bounds[1] > bounds[3]):
            raise ValueError("无效的校正排版边界")
        if (not isinstance(frame["metrics"], dict) or
                set(frame["metrics"]) != {"advance", "baseline", "ascent", "descent"} or
                any(type(v) not in (int, float) for v in frame["metrics"].values())):
            raise ValueError("无效的校正排版度量")
        GlyphMetrics(**frame["metrics"])
    if 'capture_guides' in summary:
        guides = summary['capture_guides']
        if (summary.get('source_kind') != 'recorded' or not isinstance(guides, dict)
                or set(guides) != {'math_axis_em'}):
            raise ValueError('无效的字体采集参考信息')
        axis = guides['math_axis_em']
        if type(axis) not in (int, float) or not math.isfinite(axis) or not 0 <= axis <= 2:
            raise ValueError('无效的字体数学轴参考信息')
    parts = [summary.get(k, []) for k in ("author_strokes", "reference_strokes", "unknown_strokes")]
    flat = [i for part in parts for i in part]
    if any(type(i) is not int for i in flat) or sorted(flat) != list(range(1, count + 1)):
        raise ValueError("来源分区不完整或相互重叠")
    expected = (
        "unknown"
        if parts[2]
        else "reference_only"
        if len(parts[1]) == count
        else "partial"
        if parts[1]
        else "complete"
    )
    if summary.get("author_source_status") != expected:
        raise ValueError("来源状态与笔画分区矛盾")
    if summary.get("protocol_status") != "valid":
        raise ValueError("轨迹协议未通过")
    if summary.get("review_status") not in {"unreviewed", "accepted", "needs_review", "rejected"}:
        raise ValueError("无效评价状态")


def core_digest(manifest):
    return semantic_hash(
        {k: manifest[k] for k in ("font_id", "release_id", "required_features", "core_members")}
    )


def validate_candidate(record, trajectory, metrics, summary):
    """The same checks for import verification and resolved layout glyphs."""
    points = validate_trajectory(trajectory)
    validate_summary(summary, len(trajectory["strokes"]))
    if record["character"] != trajectory["character"]:
        raise ValueError("候选字符不一致")
    if any(record[k] != v for k, v in trajectory_hashes(trajectory).items()):
        raise ValueError("轨迹内容身份不一致")
    if (
        semantic_hash(metrics) != record["metrics_id"]
        or semantic_hash(summary) != record["source_summary_hash"]
    ):
        raise ValueError("度量或来源身份不一致")
    if record["letter_style"] not in {"upright", "italic", "unspecified", "not_applicable"}:
        raise ValueError("无效字形类别")
    return points, GlyphMetrics(**metrics)


def resolved_candidate(record, trajectory, metrics, summary, identity, *, _reuse=None):
    core = {
        "schema_version": "inkfont_resolved_v1",
        "identity": identity,
        "record": record,
        "trajectory": trajectory,
        "metrics": metrics,
        "summary": summary,
    }
    raw = encoded(core)
    # Only factory-validated immutable descriptors can be reused. Compare all
    # canonical input bytes, including numeric types, dynamics and provenance.
    # Dataclass replacements do not inherit this private validation marker.
    if (
        _reuse is not None
        and _reuse.__dict__.get('_validated_font_core') is _reuse.original_json
        and _reuse.original_json == raw
    ):
        return _reuse
    _, checked_metrics = validate_candidate(record, trajectory, metrics, summary)
    glyph = ResolvedGlyph(
        sha(raw),
        record["character"],
        record["candidate_id"],
        identity["writer_alias"],
        tuple(tuple((p["x"], p["y"]) for p in s["points"]) for s in trajectory["strokes"]),
        checked_metrics,
        record["metrics_id"],
        raw,
        PROVIDER,
    )
    object.__setattr__(glyph, '_validated_font_core', raw)
    object.__setattr__(glyph, '_font_metadata', {
        "identity": identity, "record": record, "summary": summary,
    })
    return glyph


def from_embedded(raw):
    core = decode(raw)
    if core.get("schema_version") != "inkfont_resolved_v1":
        raise ValueError("无效字体快照")
    return resolved_candidate(
        core["record"], core["trajectory"], core["metrics"], core["summary"], core["identity"]
    )


class FontPackage:
    """Index resident; point arrays decoded only for requested characters."""

    def __init__(self, path, *, verify_all=True):
        self.path = Path(path)
        self.fingerprint = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
        with zipfile.ZipFile(self.path) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            if len(names) > 100_000 or len({n.casefold() for n in names}) != len(names):
                raise ValueError("字体成员过多或路径重复")
            if sum(i.file_size for i in infos) > MAX_TOTAL:
                raise ValueError("字体展开大小超限")
            for info in infos:
                p = PurePosixPath(info.filename)
                if (
                    p.is_absolute()
                    or ".." in p.parts
                    or "\\" in info.filename
                    or ":" in info.filename
                    or info.file_size > MAX_MEMBER
                    or info.flag_bits & 1
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("不安全的字体成员")
            self.manifest = decode(self._read(z, "manifest.json"))
            m = self.manifest
            for identity_key in ("font_id", "release_id", "package_id"):
                if str(uuid.UUID(m[identity_key])) != m[identity_key]:
                    raise ValueError("无效的字体身份")
            if m.get("format") != FORMAT or m.get("format_version") != VERSION:
                raise ValueError("不支持的字体包格式")
            if (
                m.get("package_kind") not in {"user", "developer"}
                or m.get("required_features") != FEATURES
            ):
                raise ValueError("不支持的字体包特性")
            if (
                sha(encoded({k: v for k, v in m.items() if k != "content_hash"}))
                != m["content_hash"]
            ):
                raise ValueError("字体清单哈希不符")
            if set(names) != {"manifest.json", *m["members"]} or m["core_hash"] != core_digest(m):
                raise ValueError("字体核心身份或成员不符")
            if set(m["core_members"]) != {
                k for k in m["members"] if not k.startswith("development/")
            }:
                raise ValueError("字体核心成员声明不符")
            for name, h in m["core_members"].items():
                if m["members"][name]["sha256"] != h:
                    raise ValueError("字体核心摘要不符")
            if verify_all:
                for name in m["members"]:
                    self._checked(z, name)
            self.index = decode(self._checked(z, "index.json"))
            self.metrics = decode(self._checked(z, "metrics.json"))
            self.provenance = decode(self._checked(z, "provenance.json"))
        if self.index.get("selection_policy") != "style-priority-uniform-v1":
            raise ValueError("不支持的候选选择策略")
        if m["package_kind"] == "user" and any(n.startswith("development/") for n in names):
            raise ValueError("用户版不能包含开发记录")
        self.records = self.index["candidates"]
        self.pools = {}
        ids = set()
        for r in self.records:
            if (
                r["file"] not in m["core_members"]
                or not r["file"].startswith("glyphs/")
                or type(r["enabled"]) is not bool
                or type(r["priority"]) is not int
            ):
                raise ValueError("候选核心引用或选择规则无效")
            if str(uuid.UUID(r["candidate_id"])) != r["candidate_id"]:
                raise ValueError("无效的候选身份")
            if r["candidate_id"] in ids:
                raise ValueError("重复候选身份")
            ids.add(r["candidate_id"])
            self.pools.setdefault(r["character"], []).append(r)
        if set(self.metrics) != ids or set(self.provenance) != ids:
            raise ValueError("度量和来源索引与候选不一致")
        self.identity = {k: m[k] for k in ("font_id", "release_id", "core_hash", "writer_alias")}

    @staticmethod
    def _read(z, name):
        with z.open(name) as f:
            raw = f.read(MAX_MEMBER + 1)
        if len(raw) > MAX_MEMBER:
            raise ValueError("字体成员超限")
        return raw

    def _checked(self, z, name):
        raw = self._read(z, name)
        spec = self.manifest["members"][name]
        if len(raw) != spec["bytes"] or sha(raw) != spec["sha256"]:
            raise ValueError("字体成员损坏：" + name)
        return raw

    def glyphs(self, characters=None, *, reuse=(), cancelled=None):
        from ..document.cancellation import check_cancel

        if self.fingerprint != (self.path.stat().st_size, self.path.stat().st_mtime_ns):
            raise ValueError("字体文件已变化，请重新导入")
        chars = set(self.pools) if characters is None else set(characters)
        previous = {g.sample_id: g for g in reuse if g.provider_version == PROVIDER}
        with zipfile.ZipFile(self.path) as z:
            for char in sorted(chars):
                for r in self.pools.get(char, ()):
                    check_cancel(cancelled)
                    t = decode(self._checked(z, r["file"]))
                    cid = r["candidate_id"]
                    yield resolved_candidate(
                        r, t, self.metrics[cid], self.provenance[cid], self.identity,
                        _reuse=previous.get(cid),
                    )

    def _verify_record(self, archive, record):
        trajectory = decode(self._checked(archive, record['file']))
        cid = record['candidate_id']
        summary = self.provenance[cid]
        points, _ = validate_candidate(record, trajectory, self.metrics[cid], summary)
        return points, summary['author_source_status'] != 'complete', record['letter_style']

    def _verify_remaining(self):
        checked = {record['file'] for record in self.records}
        with zipfile.ZipFile(self.path) as archive:
            for name in self.manifest['members']:
                if name not in checked:
                    self._checked(archive, name)
        if self.fingerprint != (self.path.stat().st_size, self.path.stat().st_mtime_ns):
            raise ValueError("字体文件已变化，请重新导入")

    def _verification_statistics(self, count, points, gaps, styles):
        return {
            "characters": len(self.pools),
            "candidates": count,
            "points": points,
            "source_warning_candidates": gaps,
            "latin_candidates": styles,
            "core_hash": self.manifest["core_hash"],
            "content_hash": self.manifest["content_hash"],
        }

    def verify(self, *, progress=None):
        """Validate every member and candidate without materializing layout assets."""
        if self.fingerprint != (self.path.stat().st_size, self.path.stat().st_mtime_ns):
            raise ValueError("字体文件已变化，请重新导入")
        count = points = gaps = 0
        styles = {"upright": 0, "italic": 0, "unspecified": 0}
        last_progress = 0.0
        total = len(self.records)
        with zipfile.ZipFile(self.path) as z:
            for record in self.records:
                point_count, gap, style = self._verify_record(z, record)
                count += 1
                points += point_count
                gaps += gap
                if style in styles:
                    styles[style] += 1
                now = time.monotonic()
                if progress and (now - last_progress >= .1 or count == total):
                    progress(f'正在验证字形 {count}/{total}…')
                    last_progress = now
            # Includes development records and unreferenced core members. A
            # metadata-only constructor is never a substitute for full verification.
            if progress:
                progress('正在核对其余字体成员…')
        self._verify_remaining()
        return self._verification_statistics(count, points, gaps, styles)


def write_archive(path, members, manifest):
    """members are byte values or existing Paths, allowing streamed packaging."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    if len(members) + 1 > 100_000:
        raise ValueError("字体成员过多")
    path.parent.mkdir(parents=True, exist_ok=True)
    m = dict(manifest)
    m["members"] = {}
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            total = 0
            for name, value in sorted(members.items()):
                raw = value.read_bytes() if isinstance(value, Path) else value
                if len(raw) > MAX_MEMBER:
                    raise ValueError("字体成员超限：" + name)
                total += len(raw)
                if total > MAX_TOTAL:
                    raise ValueError("字体展开大小超限")
                z.writestr(name, raw)
                m["members"][name] = {"sha256": sha(raw), "bytes": len(raw)}
            m["core_members"] = {
                k: v["sha256"] for k, v in m["members"].items() if not k.startswith("development/")
            }
            m["core_hash"] = core_digest(m)
            m["content_hash"] = sha(encoded({k: v for k, v in m.items() if k != "content_hash"}))
            raw_manifest = encoded(m)
            if len(raw_manifest) > MAX_MEMBER:
                raise ValueError("字体成员超限：manifest.json")
            if total + len(raw_manifest) > MAX_TOTAL:
                raise ValueError("字体展开大小超限")
            z.writestr("manifest.json", raw_manifest)
        # Never overwrite an existing publication, even if another process won the race.
        os.link(tmp, path)
        return m
    finally:
        Path(tmp).unlink(missing_ok=True)


def to_user(source, output):
    font = FontPackage(source)
    m = {
        k: v
        for k, v in font.manifest.items()
        if k not in ("members", "content_hash", "core_hash", "core_members")
    }
    m.update(
        package_kind="user",
        package_id=str(uuid.uuid4()),
        derived_from_package={
            "package_id": font.manifest["package_id"],
            "content_hash": font.manifest["content_hash"],
        },
    )
    with tempfile.TemporaryDirectory() as d, zipfile.ZipFile(font.path) as z:
        members = {}
        for i, name in enumerate(font.manifest["core_members"]):
            p = Path(d) / str(i)
            p.write_bytes(font._checked(z, name))
            members[name] = p
        result = write_archive(output, members, m)
    if result["core_hash"] != font.manifest["core_hash"]:
        raise ValueError("转换改变核心身份")
    return result


from functools import lru_cache


@lru_cache(maxsize=2)
def _cached_font(path, stamp):
    font = FontPackage(path)
    font.preview_token = path, stamp, font.manifest["core_hash"]
    return font


def cached_font(path):
    path = Path(path).resolve()
    stat = path.stat()
    stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return _cached_font(str(path), stamp)


def verified_preview_font(path):
    """Only an unchanged, fully verified library file may defer member reads."""
    from ..resource_catalog import FontMetadata
    from .library import fingerprint

    path = Path(path).resolve()
    stamp = fingerprint(path)
    try:
        entry = FontMetadata(path.parent).read().get(path.name, {})
    except (ValueError, OSError, TypeError):
        return None
    if entry.get("verified_stamp") != list(stamp):
        return None
    font = cached_font(path)
    return font if font.preview_token[1] == stamp else None
