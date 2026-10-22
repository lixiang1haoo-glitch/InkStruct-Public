"""Explicit adapters for frozen generated results and recorded symbol samples."""

from __future__ import annotations

import gzip
import tempfile
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path

from ..assets.glyph_provider import GlyphMetrics, adapt_glyph
from ..assets.symbol_provider import DEFAULT_SYMBOL_PROFILE, adapt_symbol
from ..punctuation import CHINESE_PUNCTUATION, POLICY, SHARED_PUNCTUATION, shared_characters
from .core import (
    FEATURES,
    FORMAT,
    MAX_MEMBER,
    VERSION,
    decode,
    encoded,
    latin,
    semantic_hash,
    sha,
    trajectory_hashes,
    validate_summary,
    validate_trajectory,
    write_archive,
)


def _read(path):
    path = Path(path)
    if path.stat().st_size > MAX_MEMBER:
        raise ValueError("源记录过大")
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            raw = f.read(MAX_MEMBER + 1)
    else:
        raw = path.read_bytes()
    if len(raw) > MAX_MEMBER:
        raise ValueError("源记录展开过大")
    return decode(raw)


def public_development(value):
    """Keep technical provenance while removing host and device identifiers."""
    private = {
        "capture",
        "device",
        "device_id",
        "device_name",
        "hostname",
        "username",
        "serial_number",
    }
    if isinstance(value, dict):
        return {
            public_development(k): public_development(v)
            for k, v in value.items()
            if k not in private
        }
    if isinstance(value, list):
        return [public_development(v) for v in value]
    if isinstance(value, str) and (
        value.startswith(("/", "\\")) or (len(value) > 2 and value[1:3] in (":/", ":\\"))
    ):
        return "external-ref:" + sha(value.encode())
    return value


def generated_records(run, writer):
    root = Path(run)
    if (root / "trajectories").is_dir():
        for path in sorted((root / "trajectories").glob("U+*.json")):
            glyph = _read(path)
            if glyph.get("writer_id") != writer:
                raise ValueError("生成结果书写者不一致")
            identity_path = root / "application-generation.json"
            generation = _read(identity_path) if identity_path.is_file() else None
            yield glyph, None, {"legacy_source_hash": sha(path.read_bytes()), "application_generation": generation}, generation
        return
    protocol = _read(root / "protocol.json")
    if writer not in protocol.get("writers", []):
        raise ValueError("运行中没有此书写者")
    for char in protocol["characters"]:
        stem = root / writer / f"{ord(char):04X}"
        row = _read(stem.with_suffix(".json"))
        if row.get("writer") != writer or row.get("character") != char:
            raise ValueError("逐字身份与运行不符")
        if row.get("status") == "failed":
            raise ValueError(f"生成任务失败：{char}；请先明确排除后再发布")
        for name, h in row["files"].items():
            target = (root / name).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                raise ValueError("非法产物引用")
            if sha(target.read_bytes()) != h:
                raise ValueError("产物哈希不符：" + char)
        payload = _read(stem.with_suffix(".json.gz"))
        if payload["glyph"].get("character") != char or payload["glyph"].get("writer_id") != writer:
            raise ValueError("轨迹身份不符")
        yield payload["glyph"], row, payload, protocol


def make_generated(glyph, row, payload, protocol):
    # Strict legacy generated protocol; new font protocol never relaxes it.
    adapt_glyph(glyph, metrics=GlyphMetrics())
    n = len(glyph["strokes"])
    author = []
    reference = []
    unknown = []
    missing = []
    kinds = {}
    if row is None:
        unknown = list(range(1, n + 1))
    elif "stroke_sources" in payload:
        sources = payload["stroke_sources"]
        missing = payload["missing"]
        if sources != row["stroke_sources"] or missing != row["missing"] or len(sources) != n:
            raise ValueError("来源侧记录不一致")
        for i, (s, g) in enumerate(zip(sources, glyph["strokes"], strict=True), 1):
            if s["order"] != i or s["standard_id"] != g["standard_stroke_id"]:
                raise ValueError("标准笔画映射矛盾")
            k = s["kind"]
            kinds[i] = k
            if k == "explicit_gap":
                reference.append(i)
            elif k in {
                "author_complete_component",
                "author_hybrid_retained",
                "author_hybrid_key",
                "author_single_stroke",
            }:
                author.append(i)
            else:
                unknown.append(i)
        if {r["order"] for r in missing} != set(reference):
            raise ValueError("缺口分区不符")
        if {int(k) + 1 for k in payload["provenance"]} != set(author):
            raise ValueError("作者笔画分区不符")
        if row["author_only_ready"] != (not reference):
            raise ValueError("来源完整性标记矛盾")
    else:
        for p in payload.get("provenance", []):
            author.extend(i + 1 for i in p["indices"])
        reference = [i for i in range(1, n + 1) if i not in author]
        missing = [
            {"order": i, "reason": "reference fallback in original generation"} for i in reference
        ]
    if row:
        if row["source_strokes"] != len(author) or row["reference_strokes"] != len(reference):
            raise ValueError("来源统计与笔画不符")
        if payload.get("checks", {}).get("protocol") or payload.get("checks", {}).get(
            "source_integrity"
        ):
            # Old output's source_integrity is a result dict, not a list of errors.
            integrity = payload.get("checks", {}).get("source_integrity")
            if (
                isinstance(integrity, dict)
                and integrity.get("full_source_geometry_pressure_time_exact") is not True
            ):
                raise ValueError("来源完整性检查未通过")
            if (
                payload.get("checks", {}).get("protocol")
                or isinstance(integrity, list)
                and integrity
            ):
                raise ValueError("源协议或来源检查失败")
    status = (
        "unknown"
        if unknown
        else "reference_only"
        if len(reference) == n
        else "partial"
        if reference
        else "complete"
    )
    summary = {
        "source_kind": "generated",
        "task_status": "completed",
        "author_source_status": status,
        "protocol_status": "valid",
        "review_status": "unreviewed",
        "author_strokes": sorted(author),
        "reference_strokes": reference,
        "unknown_strokes": unknown,
        "gaps": [
            {"order": g["order"], "reason": g.get("reason", "no admitted author stroke")}
            for g in missing
        ],
        "generator": glyph["generator"],
        "generation_method": protocol.get("method") if protocol else None,
        "generation_version": protocol.get("version") if protocol else None,
        "generation_mode": protocol.get("generation_mode", "cross_character_review"
            if protocol.get("same_character_sources_excluded") else "unknown") if protocol else "unknown",
        "same_character_sources_excluded": protocol.get("same_character_sources_excluded")
        if protocol
        else None,
        "evidence_scope": "source run report; trajectory and source partition checked on import",
        "warnings": ["作者来源记录不完整"] if unknown else ["含参考替代笔画"] if reference else [],
    }
    t = {
        "schema_version": "inkfont_trajectory_v1",
        "character": glyph["character"],
        "coordinate_space": "em-y-down-baseline-0.88",
        "strokes": [],
    }
    for i, s in enumerate(glyph["strokes"], 1):
        dynamic = (
            {"pressure": "inherited", "time": "inherited_retimed", "pen_state": "synthesized"}
            if i in author
            else {
                k: "synthesized" if i in reference else "unknown"
                for k in ("pressure", "time", "pen_state")
            }
        )
        t["strokes"].append(
            {
                "order": i,
                "stroke_ref": f"stroke-{i}",
                "points": [
                    {k: p[k] for k in ("x", "y", "pressure", "t_ms", "pen_state")}
                    for p in s["points"]
                ],
                "dynamic_origin": dynamic,
            }
        )
    return t, asdict(GlyphMetrics()), summary


def symbol_records(path):
    path = Path(path)
    if path.is_dir():
        files = sorted(path.rglob("*.json"))
        for f in files:
            raw = f.read_bytes()
            if len(raw) > MAX_MEMBER:
                raise ValueError("样本过大")
            v = decode(raw)
            if isinstance(v, dict) and v.get("schema_version") == "inkstruct_symbol_sample_v1":
                yield raw, v
    else:
        with zipfile.ZipFile(path) as z:
            items = [
                i
                for i in z.infolist()
                if i.filename.endswith(".json") and not i.filename.startswith("__MACOSX/")
            ]
            if len(items) > 10_000 or sum(i.file_size for i in items) > 256 * 1024**2:
                raise ValueError("符号包过大")
            for item in sorted(items, key=lambda i: i.filename):
                if item.file_size > MAX_MEMBER:
                    raise ValueError("样本过大")
                with z.open(item) as f:
                    raw = f.read(MAX_MEMBER + 1)
                if len(raw) > MAX_MEMBER:
                    raise ValueError("样本过大")
                v = decode(raw)
                if v.get("schema_version") == "inkstruct_symbol_sample_v1":
                    yield raw, v


def make_symbol(raw, value):
    asset = adapt_symbol(raw)
    t = {
        "schema_version": "inkfont_trajectory_v1",
        "character": asset.character,
        "coordinate_space": "em-y-down-baseline-0.88",
        "strokes": [],
    }
    for i, (source, xy) in enumerate(zip(value["strokes"], asset.strokes, strict=True), 1):
        pts = []
        for p, (x, y) in zip(source["points"], xy, strict=True):
            pts.append(
                {"x": x, "y": y, **{k: p[k] for k in ("pressure", "t_ms", "pen_state") if k in p}}
            )
        t["strokes"].append(
            {
                "order": i,
                "stroke_ref": f"stroke-{i}",
                "points": pts,
                "dynamic_origin": {
                    name: "measured" if any(k in p for p in pts) else "absent"
                    for name, k in [
                        ("pressure", "pressure"),
                        ("time", "t_ms"),
                        ("pen_state", "pen_state"),
                    ]
                },
            }
        )
    summary = {
        "source_kind": "recorded",
        "task_status": "completed",
        "author_source_status": "complete",
        "protocol_status": "valid",
        "review_status": "unreviewed",
        "author_strokes": list(range(1, len(t["strokes"]) + 1)),
        "reference_strokes": [],
        "unknown_strokes": [],
        "gaps": [],
        "warnings": [],
        "generator": None,
        "evidence_scope": "recorded sample; fixed guide-to-em adaptation",
    }
    if 'math_axis_em' in value['guides']:
        # The source summary is part of the hashed core, including user exports
        # and frozen documents; development-only data cannot supply layout.
        summary['capture_guides'] = {'math_axis_em': value['guides']['math_axis_em']}
    metrics = asdict(asset.metrics)
    if asset.character in CHINESE_PUNCTUATION or asset.character in SHARED_PUNCTUATION:
        metrics['advance'] = max(1.0, metrics['advance'])
    return t, metrics, summary


def build_font(
    output, *, writer, name, run=None, symbols=None, package_kind="developer", progress=None
):
    if not run and not symbols:
        raise ValueError("请选择生成结果或符号样本")
    if package_kind not in {"user", "developer"}:
        raise ValueError("无效包类型")
    font_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "inkstruct-font:" + writer + ":" + name))
    candidates = []
    metrics = {}
    provenance = {}
    members = {}
    protocol_record = None
    seen = set()
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)

        def append(t, m, s, source, source_hash, letter_style="not_applicable"):
            validate_trajectory(t)
            validate_summary(s, len(t["strokes"]))
            cid = str(uuid.uuid5(uuid.UUID(font_id), source_hash))
            if cid in seen:
                return
            seen.add(cid)
            h = trajectory_hashes(t)
            file = "glyphs/" + h["trajectory_hash"] + ".json"
            dest = folder / h["trajectory_hash"]
            dest.write_bytes(encoded(t))
            members[file] = dest
            r = {
                "candidate_id": cid,
                "character": t["character"],
                "file": file,
                **h,
                "metrics_id": semantic_hash(m),
                "source_summary_hash": semantic_hash(s),
                "letter_style": letter_style,
                "style_evidence": "explicit-construction" if 'symbol_construction' in s else
                "confirmed-reuse" if 'confirmed_reuse' in s else "capture-declared"
                if letter_style in ("upright", "italic")
                else "unknown",
                "enabled": True,
                "priority": 0 if s["source_kind"] == "recorded" else 1,
            }
            candidates.append(r)
            metrics[cid] = m
            provenance[cid] = s
            if package_kind == "developer":
                p = folder / (cid + ".source")
                p.write_bytes(encoded(public_development(source)))
                members["development/" + cid + ".json"] = p
            if progress and len(candidates) % 100 == 0:
                progress(f"已适配 {len(candidates)} 份字形")

        if run:
            for glyph, row, payload, protocol in generated_records(run, writer):
                t, m, s = make_generated(glyph, row, payload, protocol)
                append(
                    t,
                    m,
                    s,
                    payload,
                    sha(
                        encoded(
                            [glyph, payload.get("provenance"), payload.get("legacy_source_hash")]
                        )
                    ),
                    "unspecified" if latin(t["character"]) else "not_applicable",
                )
                protocol_record = protocol
        if symbols:
            recorded = list(symbol_records(symbols))
            provided_characters = {value['character'] for _, value in recorded}
            provided_styles = {(v['character'], v.get('variant', {}).get('letter_style', 'unspecified'))
                               for _, v in recorded}
            for raw, value in recorded:
                if value["writer_id"] != writer:
                    raise ValueError("符号样本书写者与字体不一致")
                t, m, s = make_symbol(raw, value)
                ls = (
                    value.get("variant", {}).get("letter_style", "unspecified")
                    if latin(t["character"])
                    else "not_applicable"
                )
                append(t, m, s, value, sha(raw), ls)
                for target in shared_characters(t['character']):
                    if target == t['character'] or target in provided_characters:
                        continue
                    sharing = {'policy': POLICY, 'source_character': t['character'],
                               'source_sample_id': value['sample_id'], 'source_sha256': sha(raw)}
                    target_metrics = dict(m)
                    if target in SHARED_PUNCTUATION:
                        target_metrics['advance'] = max(1.0, target_metrics['advance'])
                    else:
                        # When an old full-width capture supplies the ASCII form,
                        # retain its original ink-based advance instead of the CJK cell.
                        target_metrics['advance'] = adapt_symbol(raw).metrics.advance
                    append({**t, 'character': target}, target_metrics,
                           {**s, 'shared_punctuation': sharing,
                            'evidence_scope': 'same recorded strokes shared by explicit punctuation policy; not a separate recording'},
                           {'shared_punctuation': sharing, 'original_sample': value},
                           sha(encoded([POLICY, sha(raw), target])))
            from ..symbol_reuse import REUSE_POLICY, declarations
            by_id = {value['sample_id']: (raw, value) for raw, value in recorded}
            if len(by_id) != len(recorded):
                raise ValueError('符号样本身份重复，请选择单一采集库')
            for reuse in declarations(symbols, writer):
                target_style = 'italic' if reuse['group'] == 'latin_italic' else 'not_applicable'
                source_style = 'italic' if reuse['group'] == 'latin_italic' else 'unspecified'
                # A separately recorded target always takes precedence over reuse.
                if (reuse['target'], source_style) in provided_styles:
                    continue
                for sid in reuse['sample_ids']:
                    if sid not in by_id:
                        raise ValueError('复用来源样本已缺失或已重录，请重新确认复用：' + reuse['target'])
                    raw, value = by_id[sid]
                    if (value['character'] != reuse['source'] or value['writer_id'] != writer
                            or value.get('variant', {}).get('letter_style') != reuse['source_style']):
                        raise ValueError('复用来源身份或写法不匹配')
                    t, m, s = make_symbol(raw, value)
                    sharing = {**reuse, 'policy': REUSE_POLICY, 'source_sample_id': sid,
                               'source_sha256': sha(raw)}
                    append({**t, 'character': reuse['target']}, m,
                           {**s, 'confirmed_reuse': sharing,
                            'evidence_scope': 'user-confirmed reuse of recorded upright ink; no independent target recording or synthetic slant'},
                           {'confirmed_reuse': sharing, 'original_sample': value},
                           sha(encoded([REUSE_POLICY, sha(raw), reuse['target'], target_style])), target_style)
        from .symbol_rules import POLICY as CONSTRUCTION_POLICY
        from .symbol_rules import constructions

        def load_candidate(record):
            cid = record['candidate_id']
            return decode(members[record['file']].read_bytes()), metrics[cid], provenance[cid]

        for t, m, s, key in constructions(candidates, load_candidate):
            append(t, m, s, {'symbol_construction': s['symbol_construction']},
                   sha(encoded([CONSTRUCTION_POLICY, key])))
        if not candidates:
            raise ValueError("没有可用字形")
        candidates.sort(
            key=lambda r: (ord(r["character"]), r["letter_style"], r["priority"], r["candidate_id"])
        )
        members.update(
            {
                "index.json": encoded(
                    {"selection_policy": "style-priority-uniform-v1", "candidates": candidates}
                ),
                "metrics.json": encoded(metrics),
                "provenance.json": encoded(provenance),
                "license.txt": "个人字体；由提供者确认使用与分享范围。\n".encode(),
            }
        )
        if package_kind == "developer":
            members["development/dependencies.json"] = encoded(
                {
                    "source_protocol": public_development(protocol_record),
                    "raw_dependencies": "external; original capture archives and structure database not embedded",
                    "independently_reproducible": False,
                    "adapter": "inkfont-import-v1",
                    "symbol_profile": asdict(DEFAULT_SYMBOL_PROFILE),
                }
            )
        release_id = str(
            uuid.uuid5(uuid.UUID(font_id), semantic_hash([candidates, metrics, provenance]))
        )
        manifest = {
            "format": FORMAT,
            "format_version": VERSION,
            "package_kind": package_kind,
            "font_id": font_id,
            "release_id": release_id,
            "package_id": str(uuid.uuid4()),
            "font_version": "0.1",
            "name": name,
            "writer_alias": writer,
            "required_features": FEATURES,
            "derived_from_package": None,
            "adapter": "inkfont-import-v1",
        }
        return write_archive(output, members, manifest)
