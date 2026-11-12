"""Explicit adapters for frozen generated results and recorded symbol samples."""

from __future__ import annotations

import gzip
import tempfile
import uuid
import zipfile
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path

from ..assets.glyph_provider import GlyphMetrics, adapt_glyph
from ..assets.symbol_provider import DEFAULT_SYMBOL_PROFILE, adapt_symbol
from ..punctuation import CHINESE_PUNCTUATION, POLICY, SHARED_PUNCTUATION, shared_characters
from .publication_rules import PublicationRules
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
    if (root / "v63-run.json").is_file():
        from ..v63_package import grouped_records
        yield from grouped_records(root, writer)
        return
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
    from ..generation_variants import MAX_CANDIDATES, POOL_VERSION, candidate_payloads
    limit = 1
    if "candidate_pool" in protocol:
        policy = protocol["candidate_pool"]
        if (not isinstance(policy, dict) or policy.get("version") != POOL_VERSION
                or type(policy.get("limit")) is not int or not 2 <= policy["limit"] <= MAX_CANDIDATES):
            raise ValueError("不支持的生成候选池协议")
        limit = policy["limit"]
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
        profile_hash = protocol.get("profile", {}).get("sha256")
        replay_only = payload.get("replay_only") is True
        if replay_only:
            if not profile_hash or payload.get("source_profile_sha256") != profile_hash:
                raise ValueError("同字原稿与档案不符")
        else:
            if payload["glyph"].get("character") != char or payload["glyph"].get("writer_id") != writer:
                raise ValueError("轨迹身份不符")
            candidates = candidate_payloads(payload, row, writer=writer, character=char,
                                            profile_hash=profile_hash, limit=limit)
        if "connected_candidates" in protocol or "connected_candidates" in payload or replay_only:
            from ..v63_package import verify_connected_candidates
            connected = protocol.get("connected_candidates", {})
            if connected and connected.get("limit") != limit:
                raise ValueError("连笔候选上限与批次不符")
            groups = verify_connected_candidates(payload, row, writer, char,
                                                 connected.get("limit"), connected.get("same_character", False))
            for group in groups:
                yield group, None, {"grouped": True, "legacy_source_hash": sha(encoded(group))}, protocol
            if replay_only or (groups and limit == 1):
                continue
        primary = {k: v for k, v in payload.items() if k != "candidate_pool"} if limit > 1 else payload
        yield primary["glyph"], row, primary, protocol
        for candidate in candidates[1:]:
            strokes = candidate["stroke_sources"]
            record = {"source_strokes": len(strokes), "reference_strokes": 0, "stroke_sources": strokes,
                      "missing": [], "author_only_ready": True}
            yield candidate["glyph"], record, candidate, protocol


def make_generated(glyph, row, payload, protocol):
    if payload.get("grouped") or (protocol and protocol.get("schema_version") == "inkstruct_v63_grouped_run_v1"):
        from ..v63_package import make_grouped
        return make_grouped(glyph)
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
    # Split candidates in a v6.3 batch still use the original cross-character rules.
    same_character_excluded = (
        True if protocol and "connected_candidates" in protocol else
        protocol.get("same_character_sources_excluded") if protocol else None
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
        "same_character_sources_excluded": same_character_excluded,
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


def font_candidate_priority(summary):
    whole_replay = summary.get("generation_mode") == "same_character" and "v63_standard_slots" in summary
    priority = 0 if summary["source_kind"] == "recorded" or whole_replay else 1
    if (summary.get("symbol_construction", {}).get("rule") == "hbar-from-h-and-minus"
            and summary["symbol_construction"]["sources"][1]["character"] == "-"):
        priority += 1
    return priority


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
                if isinstance(v, dict) and v.get("schema_version") == "inkstruct_symbol_sample_v1":
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


def _append_symbols(writer, symbols, groups, append, diagnostics, rules, evidence):
    from ..symbol_reuse import REUSE_POLICY, declarations, reuse_options
    from .publication import symbol_group, symbol_input

    def selected(group):
        return groups is None or group in groups

    def reject(group, character, reason, *, source=None):
        if diagnostics is None:
            raise ValueError(reason)
        diagnostics.append({"group": group, "target": character, "reason": reason,
                            "source": source, "invalid": True})

    by_id = {}
    for raw, value in symbol_records(symbol_input(symbols, writer)):
        if value.get("writer_id") != writer:
            raise ValueError("扩展样本含有其他书写者，请选择同一作者的目录或 ZIP")
        character = value.get("character")
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError("扩展样本含有无效字符身份")
        sample_id = value.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in by_id:
            raise ValueError("扩展样本身份无效或重复，请选择单一采集库")
        by_id[sample_id] = (raw, value)

    prepared = {}

    def prepare(sample_id):
        if sample_id not in prepared:
            raw, value = by_id[sample_id]
            t, m, s = make_symbol(raw, value)
            validate_trajectory(t)
            validate_summary(s, len(t["strokes"]))
            prepared[sample_id] = t, m, s
        return prepared[sample_id]

    recorded = []
    for sid, (raw, value) in by_id.items():
        character = value["character"]
        style = value.get("variant", {}).get("letter_style", "unspecified")
        group = symbol_group(character, style)
        if selected(group):
            try:
                t, m, s = prepare(sid)
            except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as error:
                reject(group, character, str(error), source=sid)
                continue
            recorded.append((raw, value, style, t, m, s))
    direct = {t["character"] for _, _, _, t, _, _ in recorded}
    styles = {(t["character"], style) for _, _, style, t, _, _ in recorded}
    for raw, value, style, t, m, s in recorded:
        append(t, m, s, value, sha(raw), style if latin(t["character"]) else "not_applicable")
        for target in shared_characters(t["character"]):
            full = target if target in SHARED_PUNCTUATION else t["character"]
            if target in direct or not rules.allows(("shared", full)):
                continue
            sharing = {"policy": POLICY, "source_character": t["character"],
                       "source_sample_id": value["sample_id"], "source_sha256": sha(raw)}
            target_metrics = dict(m)
            target_metrics["advance"] = (max(1.0, m["advance"]) if target in SHARED_PUNCTUATION
                                         else adapt_symbol(raw).metrics.advance)
            append({**t, "character": target}, target_metrics,
                   {**s, "shared_punctuation": sharing,
                    "evidence_scope": "same recorded strokes shared by explicit punctuation policy; not a separate recording"},
                   {"shared_punctuation": sharing, "original_sample": value},
                   sha(encoded([POLICY, sha(raw), target])))

    mappings = {(group, target): source for group, target, source in reuse_options()}
    choices = {choice.target: choice for choice in rules.donors}
    if choices.keys() - mappings.keys() or len(choices) != len(rules.donors):
        raise ValueError("本次选用的笔迹供体不在规则目录内")
    upright = {}
    for sid, (raw, value) in by_id.items():
        char = value["character"]
        if latin(char) and value.get("variant", {}).get("letter_style") == "upright":
            upright.setdefault(char, []).append(sid)
    if evidence is not None:
        for char, ids in upright.items():
            for sid in ids:
                try:
                    prepare(sid)
                except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
                    continue
                raw, value = by_id[sid]
                evidence.donors.setdefault(char, {})[sid] = (sha(raw), value)

    def target_styles(group):
        return ("italic", "italic") if group == "latin_italic" else ("not_applicable", "unspecified")

    def emit(target, target_style, metadata, marker, policy, sid, raw, value, shape):
        t, m, s = shape
        sharing = {**metadata, "policy": policy, "source_sample_id": sid, "source_sha256": sha(raw)}
        scope = ("user-confirmed reuse of recorded upright ink" if marker == "confirmed_reuse"
                 else "enabled whitelist mapping of recorded upright ink")
        append({**t, "character": target}, m,
               {**s, marker: sharing, "evidence_scope": scope + "; no independent target recording or synthetic slant"},
               {marker: sharing, "original_sample": value},
               sha(encoded([policy, sha(raw), target, target_style])), target_style)

    reuse_records = [item for item in declarations(symbols, writer)
                     if (item["group"], item["target"]) not in choices]
    reuse_records.extend({"group": group, "target": target, "source": mappings[group, target],
                          "source_style": "upright", "sample_ids": [choice.sample_id], "confirmed": True}
                         for (group, target), choice in choices.items())
    confirmed = {(item["group"], item["target"]) for item in reuse_records}
    if evidence is not None:
        evidence.confirmed.update(confirmed)
    for reuse in reuse_records:
        group, target = reuse["group"], reuse["target"]
        rule = group, target
        if not selected(group) or not rules.allows(rule, confirmed=True):
            continue
        target_style, capture_style = target_styles(group)
        if (target, capture_style) in styles:
            continue
        sources = []
        for sid in reuse["sample_ids"]:
            try:
                if sid not in by_id:
                    raise ValueError("借用来源已缺失或已重录，请重新选择供体：" + target)
                raw, value = by_id[sid]
                if rule in choices and sha(raw) != choices[rule].sha256:
                    raise ValueError("借用来源笔迹已变化，请重新选择供体：" + target)
                if (value["character"] != reuse["source"]
                        or value.get("variant", {}).get("letter_style") != reuse["source_style"]):
                    raise ValueError("复用来源身份或写法不匹配")
                sources.append((sid, raw, value, prepare(sid)))
            except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as error:
                reject(group, target, str(error), source=sid)
                break
        else:
            for sid, raw, value, shape in sources:
                emit(target, target_style, reuse, "confirmed_reuse", REUSE_POLICY, sid, raw, value, shape)

    for (group, target), source in mappings.items():
        key = group, target
        if key in confirmed or not selected(group) or not rules.allows(key):
            continue
        target_style, capture_style = target_styles(group)
        if (target, capture_style) in styles:
            continue
        for sid in upright.get(source, ()):
            try:
                shape = prepare(sid)
            except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
                continue
            raw, value = by_id[sid]
            metadata = {"group": group, "target": target, "source": source, "source_style": "upright"}
            emit(target, target_style, metadata, "mapped_reuse", "mapped-symbol-share-v1", sid, raw, value, shape)


def build_font(
    output, *, writer, name, run=None, symbols=None, package_kind="developer", progress=None,
    symbol_groups=None, diagnostics=None, phase=None, rules=PublicationRules(), rule_evidence=None,
):
    """Prepare the same candidates for review (output=None) or for packaging."""
    from .publication import symbol_group

    preview = output is None
    if not run and not symbols and not preview:
        raise ValueError("请选择生成结果或符号样本")
    if package_kind not in {"user", "developer"}:
        raise ValueError("无效包类型")
    font_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "inkstruct-font:" + writer + ":" + name))
    candidates = []
    trajectories = {}
    metrics = {}
    provenance = {}
    members = {}
    protocol_record = None
    seen = set()
    with (nullcontext() if preview else tempfile.TemporaryDirectory()) as directory:
        folder = Path(directory) if directory else None

        def append(t, m, s, source, source_hash, letter_style="not_applicable"):
            validate_trajectory(t)
            validate_summary(s, len(t["strokes"]))
            cid = str(uuid.uuid5(uuid.UUID(font_id), source_hash))
            if cid in seen:
                return
            seen.add(cid)
            h = trajectory_hashes(t)
            file = "glyphs/" + h["trajectory_hash"] + ".json"
            if preview:
                trajectories[file] = t
            else:
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
                "confirmed-reuse" if 'confirmed_reuse' in s else "mapped-reuse" if 'mapped_reuse' in s else "capture-declared"
                if letter_style in ("upright", "italic")
                else "unknown",
                "enabled": True,
                "priority": font_candidate_priority(s),
            }
            candidates.append(r)
            metrics[cid] = m
            provenance[cid] = s
            if package_kind == "developer" and not preview:
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
            _append_symbols(writer, symbols, symbol_groups, append, diagnostics, rules, rule_evidence)
        from .symbol_rules import POLICY as CONSTRUCTION_POLICY
        from .symbol_rules import constructions

        def load_candidate(record):
            cid = record['candidate_id']
            path = record['file']
            trajectory = trajectories[path] if preview else decode(members[path].read_bytes())
            return trajectory, metrics[cid], provenance[cid]

        disabled = {target for kind, target in rules.disabled if kind == "constructed"}
        for t, m, s, key in constructions(candidates, load_candidate, diagnostics=diagnostics,
                                          skip_invalid=diagnostics is not None, disabled=disabled):
            style = s['symbol_construction'].get('base_letter_style', 'not_applicable')
            if symbol_groups is not None and symbol_group(t['character'], style) not in symbol_groups:
                continue
            try:
                append(t, m, s, {'symbol_construction': s['symbol_construction']},
                       sha(encoded([CONSTRUCTION_POLICY, key])), style)
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                if diagnostics is None:
                    raise
                diagnostics.append({'target': t['character'], 'reason': str(error), 'invalid': True})
        if preview:
            return candidates, provenance
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
        if phase:
            phase("封装")
        return write_archive(output, members, manifest)
